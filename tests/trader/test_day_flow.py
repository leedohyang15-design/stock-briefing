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
    assert tr["qty"] == 9 and tr["entry_price"] == 10300 and tr["exit_price"] == 10400
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
