"""호가 단위·비용 계산 (KRX 2023년 이후 코스피·코스닥 공통 호가단위)."""
from __future__ import annotations

import math

_TICKS = [
    (2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50),
    (200_000, 100), (500_000, 500), (float("inf"), 1_000),
]


def tick_size(price: float) -> int:
    for bound, tick in _TICKS:
        if price < bound:
            return tick
    return 1_000


def round_to_tick(price: float, up: bool = False) -> int:
    t = tick_size(price)
    f = math.ceil if up else math.floor
    return int(f(price / t) * t)


def add_ticks(price: float, n: int) -> int:
    """price 에서 n 호가 위(+)/아래(-) 가격."""
    p = round_to_tick(price, up=n > 0)
    step = 1 if n > 0 else -1
    for _ in range(abs(n)):
        p += step * tick_size(p if step > 0 else p - 1)
    return int(p)


def round_trip_cost(buy_amt: float, sell_amt: float, fee_pct: float, tax_pct: float) -> float:
    """매수·매도 수수료 + 매도 거래세 (원)."""
    return buy_amt * fee_pct / 100 + sell_amt * (fee_pct + tax_pct) / 100


def cost_pct(fee_pct: float, tax_pct: float) -> float:
    """왕복 비용 (진입금액 대비 %), 근사."""
    return fee_pct * 2 + tax_pct
