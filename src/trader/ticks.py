"""호가 단위·비용 계산 (KRX 2023년 이후 코스피·코스닥 공통 호가단위)."""
from __future__ import annotations

import math

_TICKS = [
    (2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50),
    (200_000, 100), (500_000, 500), (float("inf"), 1_000),
]


MARKET = "kr"   # market.activate() 가 바꾼다 ("kr" | "us")


def tick_size(price: float):
    if MARKET == "us":
        return 0.01 if price >= 1 else 0.0001   # 미국 주식 호가 단위
    for bound, tick in _TICKS:
        if price < bound:
            return tick
    return 1_000


def _num(x: float):
    return round(x, 4) if MARKET == "us" else int(round(x))


def round_to_tick(price: float, up: bool = False):
    t = tick_size(price)
    f = math.ceil if up else math.floor
    return _num(f(round(price / t, 6)) * t)


def add_ticks(price: float, n: int):
    """price 에서 n 호가 위(+)/아래(-) 가격."""
    p = round_to_tick(price, up=n > 0)
    step = 1 if n > 0 else -1
    for _ in range(abs(n)):
        p += step * tick_size(p if step > 0 else p - tick_size(p) / 2)
    return _num(p)


def fmt_px(p: float) -> str:
    """가격 표시 (국장: 10,300원 / 미장: $182.35)."""
    return f"${p:,.2f}" if MARKET == "us" else f"{p:,.0f}원"


def fmt_amt(v: float) -> str:
    """금액 표시 (국장: 1,234원 / 미장: $12.34)."""
    return f"${v:,.2f}" if MARKET == "us" else f"{v:,.0f}원"


def fmt_signed(v: float) -> str:
    """부호 있는 금액 (국장: +1,234원 / 미장: +$12.34)."""
    return (f"{'+' if v >= 0 else '-'}${abs(v):,.2f}") if MARKET == "us" else f"{v:+,.0f}원"


def fmt_big(v: float) -> str:
    """큰 금액 (국장: 500억 / 미장: $12.3M)."""
    return f"${v / 1e6:,.1f}M" if MARKET == "us" else f"{v / 1e8:,.0f}억"


def round_trip_cost(buy_amt: float, sell_amt: float, fee_pct: float, tax_pct: float) -> float:
    """매수·매도 수수료 + 매도 거래세 (원)."""
    return buy_amt * fee_pct / 100 + sell_amt * (fee_pct + tax_pct) / 100


def cost_pct(fee_pct: float, tax_pct: float) -> float:
    """왕복 비용 (진입금액 대비 %), 근사."""
    return fee_pct * 2 + tax_pct
