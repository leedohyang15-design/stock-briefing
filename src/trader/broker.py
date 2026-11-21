"""주문 경로 추상화.

- LiveBroker: 한국투자증권 실제 주문 (KISClient 위임)
- PaperBroker: 드라이런. 실제 시세로 체결을 흉내 내고 주문은 보내지 않는다
"""
from __future__ import annotations

import itertools
from typing import Callable, Dict, Tuple

from .models import OrderResult, Position


class LiveBroker:
    mode = "live"

    def __init__(self, kis):
        self.kis = kis

    def balance(self):
        return self.kis.balance()

    def buy_limit(self, code, qty, price) -> OrderResult:
        return self.kis.buy_limit(code, qty, price)

    def sell(self, code, qty, price=None) -> OrderResult:
        return self.kis.sell(code, qty, price)

    def cancel(self, order_no, code="") -> bool:
        return self.kis.cancel(order_no, code)

    def order_status(self, order_no) -> Tuple[int, float, int]:
        return self.kis.order_status(order_no)


class PaperBroker:
    """가상 계좌. price_fn(code) 로 현재가를 받아 지정가가 현재가 이상이면 즉시 체결."""
    mode = "paper"

    def __init__(self, price_fn: Callable[[str], float], cash: float = 1_000_000.0):
        self.price_fn = price_fn
        self.cash = cash
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Tuple[int, float, int]] = {}
        self._ids = itertools.count(1)

    def balance(self):
        total = self.cash + sum(p.qty * self.price_fn(p.code) for p in self.positions.values())
        return self.cash, list(self.positions.values()), total

    def buy_limit(self, code, qty, price) -> OrderResult:
        oid = f"P|{next(self._ids)}"
        px = self.price_fn(code)
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
        px = self.price_fn(code)
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

    def cancel(self, order_no, code="") -> bool:
        f, a, _ = self.orders.get(order_no, (0, 0.0, 0))
        self.orders[order_no] = (f, a, 0)
        return True

    def order_status(self, order_no) -> Tuple[int, float, int]:
        return self.orders.get(order_no, (0, 0.0, 0))
