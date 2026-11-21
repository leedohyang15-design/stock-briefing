import json
import shutil

from src.trader import backtest
from src.trader.agents.review import search_changes, weekly_report
from src.trader.journal import Journal
from src.trader.models import Bar
from src.trader.run_weekly import apply_proposal, hold_proposal, rollback, save_proposal
from src.trader.settings import CONFIG_PATH, Settings
from src.trader.telegram_bot import Telegram

from .fakes import FakeLLM, minute_grid, trading_days


def _mins(t):
    return int(t[:2]) * 60 + int(t[2:])


def _day_bars(d, pattern):
    """early_win: 09:05 돌파 후 종일 상승 / late_lose: 13:00 까지 범위 안 → 돌파 후 급락."""
    bars = []
    for t in minute_grid():
        if t < "0905":
            o = 10000 + int(t[2:]) * 20
            bars.append(Bar(t, o, o + 30, o - 10, o + 20, 50_000, date=d))
            continue
        if pattern == "early_win":
            p = 10150 + (_mins(t) - 545) * 2
        elif t < "1300":
            p = 10050
        else:
            p = 10200 - (_mins(t) - 781) * 3
        bars.append(Bar(t, p, p + 5, p - 5, p, 5_000, date=d))
    return bars


def _seed(j: Journal, days, patterns):
    for code, pattern in patterns.items():
        j.save_daily_bars(code, [Bar(d, 10000, 10300, 9700, 10000, 1_000_000, date=d) for d in trading_days(len(days) + 30)])
        for d in days:
            j.save_bars(code, _day_bars(d, pattern))


WIN3 = {"A00001": "early_win", "A00002": "early_win", "A00003": "early_win"}
MIXED = {"A00001": "early_win", "A00003": "late_lose"}


def test_backtest_runs_rules(tmp_path):
    j = Journal(tmp_path / "t.db")
    days = trading_days(12)[-6:]
    _seed(j, days, WIN3)
    res = backtest.run(j, Settings.load(), days)
    assert res.n == 6 * 2                # 하루 3종목 신호 중 동시 보유 2종목 한도
    assert all(t.ret_pct > 0 for t in res.trades) and res.mean_daily > 0


def test_weekly_search_requires_samples_and_both_periods(tmp_path):
    j = Journal(tmp_path / "t.db")
    days = trading_days(40)[-12:]
    _seed(j, days, MIXED)
    s = Settings.load()
    s.data["weekly"]["min_samples"] = 10
    log = []
    res = search_changes(j, s, FakeLLM(), log)
    assert res["baseline"]["in_days"] == 7 and res["baseline"]["out_days"] == 5
    best = res["best"]
    assert best and best["accepted"] and len(best["changes"]) <= 2
    assert best["in"] > res["baseline"]["in"] and best["out"] > res["baseline"]["out"]
    assert best["changes"].get("entry_end") in ("14:00", "11:00")    # 늦은 진입을 막는 변경이 선택됨
    # 표본 기준을 못 채우면 제안 없음
    strict = s.with_params({})
    strict.data["weekly"]["min_samples"] = 10_000
    assert search_changes(j, strict, FakeLLM(), [])["best"] is None


def test_llm_loss_analysis_changes_are_whitelisted(tmp_path):
    j = Journal(tmp_path / "t.db")
    days = trading_days(40)[-12:]
    _seed(j, days, MIXED)
    llm = FakeLLM([{"cause": "늦은 시간 하락", "changes": {"entry_end": "11:00", "max_order_krw": 999999999}},
                   {"cause": "x", "changes": {"orb_minutes": 7}}])
    log = []
    res = search_changes(j, Settings.load(), llm, log)
    first = res["tried"][0]
    assert first["changes"] == {"entry_end": "11:00"}          # 허용 안 된 파라미터는 버림
    assert all("orb_minutes" not in r["changes"] or r["changes"]["orb_minutes"] in (5, 15, 30) for r in res["tried"])


def test_proposal_apply_hold_rollback(tmp_path):
    cfg = tmp_path / "trader.yaml"
    shutil.copy(CONFIG_PATH, cfg)
    s = Settings.load(cfg)
    j = Journal(tmp_path / "t.db")
    pid = save_proposal(j, {"search": {"best": {"changes": {"vi_guard_pct": 2.0}}}, "calibration": {}})
    msg = apply_proposal(j, s, pid)
    s2 = Settings.load(cfg)
    assert "적용 완료" in msg and s2.version == s.version + 1 and s2.get_param("vi_guard_pct") == 2.0
    assert "이미 처리" in apply_proposal(j, s2, pid)
    pid2 = save_proposal(j, {"search": {"best": {"changes": {"relvol_min": 2.0}}}})
    assert "보류" in hold_proposal(j, pid2)
    assert rollback(j, s2, s.version).startswith("설정을")
    assert Settings.load(cfg).get_param("vi_guard_pct") == s.get_param("vi_guard_pct")
    assert save_proposal(j, {"search": {"best": None}}) is None


def test_weekly_report_end_to_end(tmp_path):
    j = Journal(tmp_path / "t.db")
    days = trading_days(40)[-12:]
    _seed(j, days, MIXED)
    rep = weekly_report(j, Settings.load(), FakeLLM(), panel=False)
    assert "주간 복기" in rep["text"] and rep["search"]["baseline"]["n"] > 0


def test_telegram_callback_only_from_owner(monkeypatch):
    tg = Telegram("TOKEN", "42")
    sent = []
    monkeypatch.setattr(tg, "_post", lambda method, **p: sent.append((method, p)) or {"result": {"message_id": 7}})
    tg.request_approval(5, "승인?")
    assert tg.approval_status(5, 180) == "pending"
    tg.handle_update({"callback_query": {"id": "x", "data": "ok:5", "message": {"chat": {"id": 999}}}})
    assert tg.approval_status(5, 180) == "pending"            # 다른 사람 → 무시
    tg.handle_update({"callback_query": {"id": "x", "data": "ok:5", "message": {"chat": {"id": 42}}}})
    assert tg.approval_status(5, 180) == "approved"
    tg.request_approval(6, "승인?")
    assert tg.approval_status(6, 0) == "expired"
    tg.on("status", lambda a: "상태 OK")
    tg.handle_update({"message": {"chat": {"id": 42}, "text": "/status"}})
    assert sent[-1][1]["text"] == "상태 OK"


class _Resp:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class _Session:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.seen.append(("POST", url, headers, json))
        return _Resp(self.replies.pop(0))

    def get(self, url, headers=None, params=None, timeout=None):
        self.seen.append(("GET", url, headers, params))
        return _Resp(self.replies.pop(0))


def test_kis_order_legacy_tr_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("KIS_APP_KEY", "k" * 10)
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("KIS_ACCOUNT", "12345678-01")
    monkeypatch.setattr("src.trader.kis_client.DATA_DIR", tmp_path)
    from src.trader.kis_client import KISClient
    sess = _Session([{"access_token": "T", "access_token_token_expired": "2099-01-01 00:00:00"},
                     {"rt_cd": "1", "msg1": "TR 없음"},
                     {"rt_cd": "0", "output": {"KRX_FWDG_ORD_ORGNO": "00950", "ODNO": "123"}}])
    c = KISClient(Settings.load(), session=sess)
    r = c.buy_limit("005930", 3, 70000)
    assert r.ok and r.order_no == "00950|123"
    trs = [s[2]["tr_id"] for s in sess.seen[1:]]
    assert trs == ["TTTC0012U", "TTTC0802U"]
    body = sess.seen[-1][3]
    assert body == {"CANO": "12345678", "ACNT_PRDT_CD": "01", "PDNO": "005930", "ORD_DVSN": "00",
                    "ORD_QTY": "3", "ORD_UNPR": "70000"}
    assert json.loads((tmp_path / "kis_token_real.json").read_text())["token"] == "T"
