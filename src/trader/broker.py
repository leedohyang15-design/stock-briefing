"""주문 경로 추상화.

- LiveBroker: 한국투자증권 실제 주문 (KISClient 위임)
- PaperBroker: 드라이런. 실제 시세로 체결을 흉내 내고 주문은 보내지 않는다
"""
from __future__ import annotations

import itertools
from typing import Callable, Dict, Tuple

from .models import OrderResult, Position
from .ticks import add_ticks


class LiveBroker:
    mode = "live"

    def __init__(self, kis):
        self.kis = kis

    def balance(self):
        cash, pos, total = self.kis.balance()
        exact = self.kis.buyable_cash()   # 잔고의 D+2 예수금 대신 '미수 없는 매수 가능 금액'
        return (exact if exact is not None else cash), pos, total

    def buy_limit(self, code, qty, price) -> OrderResult:
        return self.kis.buy_limit(code, qty, price)

    def sell(self, code, qty, price=None) -> OrderResult:
        return self.kis.sell(code, qty, price)

    def cancel(self, order_no, code="") -> bool:
        return self.kis.cancel(order_no, code)

    def order_status(self, order_no) -> Tuple[int, float, int]:
        return self.kis.order_status(order_no)


class PaperBroker:
    """가상 계좌. 체결은 보수적으로 가정한다 (미끄러짐 slippage_ticks).

    - 매수(지정가 L): 현재가 + n호가 ≤ L 일 때만 체결, 체결가 = 현재가 + n호가
    - 매도(시장가): 체결가 = 현재가 - n호가. 손절은 가격이 손절가 아래로 갭이 나도 그 아래 가격에 체결된다.
    """
    mode = "paper"

    def __init__(self, price_fn: Callable[[str], float], cash: float = 1_000_000.0, slippage_ticks: int = 1):
        self.price_fn = price_fn
        self.slip = int(slippage_ticks)
        self.cash = cash
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Tuple[int, float, int]] = {}
        self._ids = itertools.count(1)

    def balance(self):
        total = self.cash + sum(p.qty * self.price_fn(p.code) for p in self.positions.values())
        return self.cash, list(self.positions.values()), total

    def buy_limit(self, code, qty, price) -> OrderResult:
        oid = f"P|{next(self._ids)}"
        px = add_ticks(self.price_fn(code), self.slip) if self.slip else self.price_fn(code)
        if px <= price and qty * px <= self.cash:
            self.cash -= qty * px
            pos = self.positions.get(code)
            if pos:
                pos.avg_price = (pos.avg_price * pos.qty + px * qty) / (pos.qty + qty)
                pos.qty += qty
            else:
                self.positions[code] = Position(code=code, name=code, qty=qty, avg_price=px, stop=0.0)
            self.orders[oid] = (qty, px, 0)
        else:
            self.orders[oid] = (0, 0.0, qty)
        return OrderResult(True, order_no=oid, message="paper")

    def sell(self, code, qty, price=None) -> OrderResult:
        oid = f"P|{next(self._ids)}"
        pos = self.positions.get(code)
        px = add_ticks(self.price_fn(code), -self.slip) if self.slip else self.price_fn(code)
        if not pos or (price is not None and px < price):
            self.orders[oid] = (0, 0.0, qty)
            return OrderResult(True, order_no=oid, message="paper")
        q = min(qty, pos.qty)
        self.cash += q * px
        pos.qty -= q
        if pos.qty <= 0:
            del self.positions[code]
        self.orders[oid] = (q, px, qty - q)
        return OrderResult(True, order_no=oid, message="paper")

    def load_position(self, code: str, name: str, qty: int, avg_price: float) -> None:
        """재시작 시 일지의 열린 거래로 가상 보유를 복원."""
        self.positions[code] = Position(code=code, name=name, qty=qty, avg_price=avg_price, stop=0.0)
        self.cash -= qty * avg_price

    def cancel(self, order_no, code="") -> bool:
        f, a, _ = self.orders.get(order_no, (0, 0.0, 0))
        self.orders[order_no] = (f, a, 0)
        return True

    def order_status(self, order_no) -> Tuple[int, float, int]:
        return self.orders.get(order_no, (0, 0.0, 0))
