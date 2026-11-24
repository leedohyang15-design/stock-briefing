"""미장(미국) 모드: 시장 전환, 호가·통화, 해외 API 파싱, 하루 흐름(가짜 시세·뉴욕 시각)."""
import datetime as dt

import pytest

from src.trader import market as mk
from src.trader import strategy as st
from src.trader import ticks


@pytest.fixture
def us():
    m = mk.activate("us")
    yield m
    mk.activate("kr")


def test_activate_switches_globals(us):
    from src.trader import models
    assert us.key == "us" and st.SESSION_OPEN == "0930" and ticks.MARKET == "us"
    assert models.now_kst().utcoffset() in (dt.timedelta(hours=-5), dt.timedelta(hours=-4))
    assert ticks.add_ticks(182.34, 1) == 182.35 and ticks.add_ticks(182.34, -2) == 182.32
    assert ticks.fmt_px(182.3) == "$182.30" and ticks.fmt_signed(-1.5) == "-$1.50"
    assert us.is_holiday(dt.date(2026, 11, 26))            # 추수감사절
    assert not us.is_holiday(dt.date(2026, 11, 24))
    mk.activate("kr")
    assert ticks.add_ticks(10_000, 1) == 10_010 and st.SESSION_OPEN == "0900"


def test_us_stop_floor_in_cents(us):
    cfg = {"stop_atr_mult": 0.1, "min_stop_ticks": 5, "min_stop_cost_mult": 2.0}
    assert round(st.stop_for(100.0, 0.3, cfg, 0.19), 4) == round(100.0 - 0.38, 4)   # 비용×2 = 0.38 > 5센트 > 0.03


def test_overseas_adapter_parsing(monkeypatch, tmp_path, us):
    from .test_weekly_and_io import _kis_with
    from src.trader.kis_overseas import KISOverseas
    today = dt.datetime.now(us.tz).strftime("%Y%m%d")
    c, sess = _kis_with(monkeypatch, tmp_path, [
        {"rt_cd": "0", "output": {"last": "0"}},                                         # NAS 에 없음
        {"rt_cd": "0", "output": {"last": "182.35", "base": "180.00", "rate": "1.31", "tvol": "1000"}},  # NYS
        {"rt_cd": "0", "output2": [{"xymd": "20261120", "clos": "180", "open": "179", "high": "181", "low": "178", "tvol": "5"},
                                   {"xymd": today, "clos": "182", "open": "1", "high": "1", "low": "1", "tvol": "1"}]},
        {"rt_cd": "0", "output2": [{"symb": "AAPL", "excd": "NAS", "knam": "애플", "last": "182", "rate": "1.2",
                                    "tvol": "100", "tamt": "18200"}]},
        {"rt_cd": "1", "msg1": "x"},
        {"rt_cd": "0", "outblock1": [{"title": "Apple announces offering", "data_dt": today, "data_tm": "093000"}]},
    ])
    o = KISOverseas(c)
    q = o.quote("XYZ")
    assert q.price == 182.35 and q.prev_close == 180.0 and o.excd["XYZ"] == "NYS"
    assert sess.seen[1][2]["tr_id"] == "HHDFS00000300" and sess.seen[2][3]["EXCD"] == "NYS"
    d = o.daily_bars("XYZ")
    assert [b.date for b in d] == ["20261120"]                                        # 오늘(미완성) 일봉 제외
    r = o.volume_rank("increase")
    assert r[0]["code"] == "AAPL" and o.excd["AAPL"] == "NAS" and r[0]["value_krw"] == 18200
    assert sess.seen[4][2]["tr_id"] == "HHDFS76270000"
    n = o.news_titles("AAPL")
    assert n[0]["title"] == "Apple announces offering" and sess.seen[6][2]["tr_id"] == "HHPSTH60100C1"


def test_us_full_day_paper(tmp_path, us):
    from src.trader.agents import premarket
    from src.trader.broker import PaperBroker
    from src.trader.journal import Journal
    from src.trader.models import AgentResult
    from src.trader.run_day import DayTrader
    from src.trader.settings import Settings
    from src.trader.simulator import FakeClock, FakeKIS, FakeLLM
    from src.trader.telegram_bot import NullTelegram
    clock = FakeClock("0850")
    path = lambda h: 101.0 if h < "1000" else (103.0 if h < "1100" else 104.0)
    kis = FakeKIS(clock, path, code="AAPL", name="Apple", base=100.0, open_="0930", close="1600")
    pool = [{"code": "AAPL", "name": "Apple", "price": 100.0, "change_pct": 1.0, "value_krw": 5e9}]
    inputs = premarket.PremarketInputs(indices=lambda: [], headlines=lambda: [], themes=lambda: [],
                                       pool=lambda: pool, notices=lambda c: [])
    s = Settings.load(us.config_path)
    j = Journal(tmp_path / "us.db")
    t = DayTrader(s, kis, PaperBroker(lambda c: kis.quote(c).price, cash=1000, slippage_ticks=1), j, FakeLLM(),
                  NullTelegram(), now_fn=clock.now, sleep_fn=clock.sleep, premarket_inputs=inputs)
    t.ex.poll = 0
    t._news = lambda ip: AgentResult(12, "실시간 뉴스·공시", "pass", "악재 없음")
    t.run(1000)
    tr = j.query("SELECT * FROM trades")
    assert len(tr) == 1, j.query("SELECT kind, text FROM events")
    tr = tr[0]
    assert tr["entry_price"] == 103.01 and tr["exit_price"] == 103.99 and tr["exit_reason"] == "장마감 청산"
    assert tr["qty"] == int(300 // 103.01) and tr["net_pnl"] > 0                     # 1회 한도 $300
    assert t.index and all("SPY" in k or "QQQ" in k for k in t.index)
    phase = j.get_snapshot("phase")
    assert phase["history"]["scan"][11:16] == "09:30" and phase["key"] == "done"
