"""하루 전체 흐름 (가짜 시세·가짜 시계): 장전 → Stocks in Play → 신호 → 승인 → 체결 → 청산/손절 → 복기."""

from src.trader.agents import premarket
from src.trader.broker import PaperBroker
from src.trader.journal import Journal
from src.trader.models import AgentResult
from src.trader.run_day import DayTrader
from src.trader.settings import Settings
from src.trader.telegram_bot import NullTelegram

from .fakes import FakeClock, FakeKIS, FakeLLM, today


def _inputs():
    pool = [{"code": "111111", "name": "샘플반도체", "price": 10000, "change_pct": 2.0, "value_krw": 5e10}]
    return premarket.PremarketInputs(indices=lambda: ["나스닥 1 (+1.00%)"], headlines=lambda: [], themes=lambda: [],
                                     pool=lambda: pool, notices=lambda c: [])


def _trader(tmp_path, path, tg=None):
    clock = FakeClock("0750")
    kis = FakeKIS(clock, path)
    j = Journal(tmp_path / "t.db")
    broker = PaperBroker(lambda c: kis.quote(c).price, cash=1_000_000)
    t = DayTrader(Settings.load(), kis, broker, j, FakeLLM(), tg or NullTelegram(),
                  now_fn=clock.now, sleep_fn=clock.sleep, premarket_inputs=_inputs())
    t.ex.poll = 0
    t._news = lambda ip: AgentResult(12, "실시간 뉴스·공시", "pass", "악재 없음 (테스트)")
    return t, j, kis


def test_full_day_breakout_then_eod_flatten(tmp_path):
    path = lambda t: 10100 if t < "0935" else (10300 if t < "1000" else 10400)
    t, j, kis = _trader(tmp_path, path)
    t.run(1_000_000)
    sig = j.query("SELECT * FROM signals")
    assert len(sig) == 1 and sig[0]["status"] == "filled"
    tr = j.query("SELECT * FROM trades")
    assert len(tr) == 1
    tr = tr[0]
    # 모의 체결은 미끄러짐 1호가: 매수 10,300+10, 매도 10,400-10
    assert tr["qty"] == 9 and tr["entry_price"] == 10310 and tr["exit_price"] == 10390
    assert tr["exit_reason"] == "장마감 청산" and tr["net_pnl"] > 0
    agents = {r["no"] for r in j.query("SELECT no FROM agent_results WHERE signal_id=?", (sig[0]["id"],))}
    assert agents == {9, 10, 11, 12, 13, 14, 15, 16, 18}
    tm = j.query("SELECT decision FROM agent_results WHERE no=18")[0]
    assert tm["decision"] == "pass"
    daily = j.query("SELECT * FROM daily")[0]
    assert daily["date"] == today() and daily["trades"] == 1 and daily["ret_pct"] > 0
    assert j.get_snapshot("status")["mode"] == "paper"
    assert not t.ex.positions


def test_stop_loss_exit(tmp_path):
    path = lambda t: 10100 if t < "0935" else (10300 if t < "0950" else 10200)
    t, j, _ = _trader(tmp_path, path)
    t.run(1_000_000)
    tr = j.query("SELECT * FROM trades")[0]
    assert tr["exit_reason"] == "손절" and tr["net_pnl"] < 0
    # 같은 종목 재진입 금지
    assert len(j.query("SELECT * FROM trades")) == 1


def test_rejected_approval_means_no_order(tmp_path):
    class RejectTG(NullTelegram):
        def approval_status(self, sid, timeout_sec):
            return "rejected"

    path = lambda t: 10100 if t < "0935" else 10300
    t, j, _ = _trader(tmp_path, path, RejectTG())
    t.run(1_000_000)
    assert j.query("SELECT * FROM trades") == []
    assert j.query("SELECT status FROM signals")[0]["status"] == "rejected"


def test_user_stop_command_blocks_new_entries(tmp_path):
    path = lambda t: 10100 if t < "0935" else 10300
    t, j, _ = _trader(tmp_path, path)
    t.start(1_000_000)
    t._cmd_stop()
    t.premarket()
    t.now.__self__.t = t.now().replace(hour=9, minute=6)
    t.scan()
    t.now.__self__.t = t.now().replace(hour=9, minute=40)
    t.tick()
    assert j.query("SELECT * FROM signals") == []


def test_after_hours_run_only_checks_connection(tmp_path):
    t, j, kis = _trader(tmp_path, lambda t: 10300)
    t.now.__self__.t = t.now().replace(hour=15, minute=50)
    t.run(1_000_000)
    assert j.query("SELECT * FROM signals") == [] and j.query("SELECT * FROM orders") == []
    assert any("장 시간이 아니어서" in e["text"] for e in j.query("SELECT text FROM events"))
    assert not any("첫 30분" in e["text"] for e in j.query("SELECT text FROM events"))


def test_late_start_weak_market_blocks_quietly(tmp_path):
    t, j, kis = _trader(tmp_path, lambda h: 10100 if h < "0935" else 10300)
    kis.index_change = lambda m="KOSPI": (2500.0, -2.3)
    t.start(1_000_000)
    t.premarket()
    t.now.__self__.t = t.now().replace(hour=13, minute=25)
    t.scan()
    for _ in range(30):
        t.tick()
        t.now.__self__.t += __import__("datetime").timedelta(seconds=61)
    texts = [e["text"] for e in j.query("SELECT text FROM events")]
    assert any("뚜렷한 약세" in x for x in texts)                       # -2.3% < -1% 기준
    assert sum("신규 매수 중단 중" in x for x in texts) == 1               # 알림은 한 번만
    sig = j.query("SELECT * FROM signals")                              # 매분 남발 없이, 그림자 거래용 1건만
    assert len(sig) == 1 and sig[0]["status"] == "rejected"
    assert len(j.query("SELECT * FROM shadow")) == 1
    kis.index_change = lambda m="KOSPI": (2500.0, -0.4)                # -1% 위로 회복하면 재개
    t._last_index = 0
    t.tick()
    assert t._regime_blocked is False
    assert len(j.query("SELECT * FROM signals")) == 2                   # 회복되면 실제 검사


def test_paper_fill_slippage_and_gap_stop():
    from src.trader.broker import PaperBroker
    px = {"A": 10_000}
    b = PaperBroker(lambda c: px[c], cash=1_000_000, slippage_ticks=1)
    assert b.order_status(b.buy_limit("A", 5, 10_000).order_no)[0] == 0          # 10,010 > 지정가 → 미체결
    o = b.buy_limit("A", 5, 10_010)
    assert b.order_status(o.order_no)[:2] == (5, 10_010)
    px["A"] = 9_800                                                              # 손절가(9,950) 아래로 갭
    o = b.sell("A", 5)
    assert b.order_status(o.order_no)[:2] == (5, 9_790)                          # 갭 아래 - 1호가에 체결


def test_paper_auto_approve_sends_notice_only():
    from src.trader.telegram_bot import AutoApprove, NullTelegram
    sent = []

    class TG(NullTelegram):
        def send(self, text):
            sent.append(text)
    a = AutoApprove(TG())
    a.request_approval(1, "[매수 승인 요청] A\n9주\n3분 안에 응답이 없으면 취소됩니다.")
    assert a.approval_status(1, 180) == "approved"
    assert sent and "자동 승인" in sent[0] and "3분" not in sent[0]


def test_restart_restores_paper_position_and_counts(tmp_path):
    path = lambda h: 10100 if h < "0935" else (10300 if h < "1000" else 10400)
    t, j, kis = _trader(tmp_path, path)
    t.start(1_000_000)
    t.premarket()
    t.now.__self__.t = t.now().replace(hour=9, minute=6)
    t.scan()
    t.now.__self__.t = t.now().replace(hour=9, minute=40)
    t.tick()
    t.tick()
    assert t.ex.positions                                                        # 매수됨
    # 프로그램이 죽었다가 다시 켜짐 (같은 DB, 새 브로커)
    from src.trader.broker import PaperBroker
    from src.trader.run_day import DayTrader
    from src.trader.settings import Settings
    from src.trader.telegram_bot import NullTelegram
    from .fakes import FakeLLM
    clock = t.now.__self__
    t2 = DayTrader(Settings.load(), kis, PaperBroker(lambda c: kis.quote(c).price, cash=1_000_000), j, FakeLLM(),
                   NullTelegram(), now_fn=clock.now, sleep_fn=clock.sleep)
    t2.start(1_000_000)
    assert "111111" in t2.ex.positions and t2.state.entries == 1 and "111111" in t2.state.traded_codes
    assert t2.state.start_equity == 1_000_000


def test_launcher_restarts_at_most_three_times():
    from src.trader.launch import run_with_restart
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("일시 오류")
    assert run_with_restart(flaky, sleep=lambda s: None) == 2

    def always():
        raise RuntimeError("계속 오류")
    import pytest
    with pytest.raises(RuntimeError):
        run_with_restart(always, max_restarts=3, sleep=lambda s: None)


def test_rejected_signal_tracked_as_shadow_trade(tmp_path):
    class RejectTG(NullTelegram):
        def approval_status(self, sid, timeout_sec):
            return "rejected"
    path = lambda h: 10100 if h < "0935" else (10300 if h < "1000" else 10500)
    t, j, _ = _trader(tmp_path, path, RejectTG())
    t.run(1_000_000)
    assert j.query("SELECT * FROM trades") == []                       # 실제(모의) 매수는 없음
    sh = j.query("SELECT * FROM shadow")
    assert len(sh) == 1 and sh[0]["reason"] == "승인 안 됨" and sh[0]["exit_reason"] == "장마감 청산"
    assert sh[0]["entry_price"] == 10310 and sh[0]["exit_price"] == 10490 and sh[0]["ret_pct"] > 0
    assert any("그림자 거래 1건" in e["text"] or "그림자" in e["kind"] for e in j.query("SELECT kind, text FROM events"))


def test_regime_block_still_records_shadow(tmp_path):
    path = lambda h: 10100 if h < "0935" else (10300 if h < "0950" else 10100)
    t, j, kis = _trader(tmp_path, path)
    kis.index_change = lambda m="KOSPI": (2500.0, -2.5)
    t.run(1_000_000)
    sh = j.query("SELECT * FROM shadow")
    assert len(sh) == 1 and sh[0]["reason_no"] == 13 and sh[0]["exit_reason"] == "손절" and sh[0]["ret_pct"] < 0
    sig = j.query("SELECT status FROM signals")
    assert len(sig) == 1 and sig[0]["status"] == "rejected"
