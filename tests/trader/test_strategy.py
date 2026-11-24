from src.trader import strategy as st
from src.trader.models import Bar, Trade
from src.trader.ticks import add_ticks, round_trip_cost, tick_size


def _d(h, l, c):
    return Bar(time="", open=c, high=h, low=l, close=c, volume=100)


def test_atr_simple_mean_of_true_range():
    bars = [_d(110, 90, 100), _d(105, 95, 100), _d(120, 100, 110)]
    # TR: max(10, 5, 5)=10 ; max(20, 20, 0)=20 → 15
    assert st.atr(bars, 14) == 15


def test_opening_range_and_direction():
    bars = [Bar("0900", 100, 105, 99, 101, 10), Bar("0904", 101, 108, 100, 107, 20), Bar("0905", 107, 120, 106, 119, 30)]
    r = st.opening_range(bars, 5)
    assert (r.high, r.low, r.open, r.close, r.volume, r.end) == (108, 99, 100, 107, 30, "0905")
    assert r.bullish
    assert st.orb_long_trigger(109, r) and not st.orb_long_trigger(108, r)


def test_bearish_range_never_triggers_long():
    r = st.OpeningRange(high=110, low=90, open=105, close=95, volume=1, end="0905")
    assert not st.orb_long_trigger(200, r, require_bullish=True)


def test_relative_volume():
    assert st.relative_volume(200_000, 1_000_000, 0.05) == 4.0
    assert st.relative_volume(1, 0, 0.05) == 0.0


def test_position_size_takes_smallest_limit():
    # 위험 기준 1e6*1%/60=166주, 1회 한도 10만원/10000=10주, 예수금 5만원/10000=5주
    assert st.position_size(1_000_000, 1.0, 10_000, 9_940, 100_000, 50_000) == 5
    assert st.position_size(1_000_000, 1.0, 10_000, 10_000, 100_000, 1e9) == 0


def test_order_imbalance_tick_rule():
    trades = [Trade("", 103, 10), Trade("", 102, 10), Trade("", 102, 5), Trade("", 101, 10), Trade("", 102, 10)]
    # 오래된 순: 102,101(↓매도10),102(↑매수5),102(=매수10),103(↑매수10)
    buy, sell, oib = st.order_imbalance(trades)
    assert (buy, sell) == (25, 10)
    assert round(oib, 3) == round(15 / 35, 3)


def test_vi_room():
    assert round(st.vi_room_pct(10_500, 10_000, 10.0), 2) == round(500 / 10_500 * 100, 2)


def test_ticks_and_costs():
    assert tick_size(1999) == 1 and tick_size(2000) == 5 and tick_size(19_990) == 10 and tick_size(60_000) == 100
    assert add_ticks(10_000, 1) == 10_010
    assert add_ticks(19_990, 1) == 20_000 and add_ticks(20_000, 1) == 20_050
    assert add_ticks(10_000, -2) == 9_980
    assert round(round_trip_cost(100_000, 100_000, 0.015, 0.2), 2) == 15 + 215


def test_order_imbalance_same_result_any_order():
    up = [Trade(f"0930{s:02d}", 100 + s, 10) for s in range(10)]           # 과거→최신, 상승
    old_first = st.order_imbalance(up)
    new_first = st.order_imbalance(list(reversed(up)))
    assert old_first == new_first and old_first[2] > 0.9                   # 오르는 종목은 매수 주도


def test_vi_reference_after_earlier_vi():
    ref = st.vi_reference(295_000, 362_500, 10.0)
    assert round(ref) == 356_950                                            # 295,000 → 324,500 → 356,950
    room = st.vi_room_pct(362_500, ref, 10.0)
    assert round(room, 1) == 8.3
    assert st.vi_reference(10_000, 10_500, 10.0) == 10_000                  # 아직 VI 전이면 시가 그대로
    assert st.vi_reference(10_000, 50_000, 0) == 10_000                     # 미장(VI 없음)
