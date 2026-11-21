"""16. 주문 실행·포지션 관리 — 지정가 매수, 체결 확인, ATR 손절, 청산 시각 전량 정리 (자동, 승인 불필요)."""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from .journal import Journal
from .models import Position, now_kst
from .ticks import round_trip_cost


class Executor:
    def __init__(self, broker, journal: Journal, costs: Dict, notify: Callable[[str], None] = print,
                 fill_wait_sec: float = 20.0, poll_sec: float = 1.0):
        self.broker = broker
        self.j = journal
        self.costs = costs
        self.notify = notify
        self.fill_wait = fill_wait_sec
        self.poll = poll_sec
        self.positions: Dict[str, Position] = {}
        self.trade_ids: Dict[str, int] = {}

    @property
    def mode(self) -> str:
        return self.broker.mode

    def _wait_fill(self, order_no: str, qty: int, timeout: float):
        filled, avg, remain = 0, 0.0, qty
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            filled, avg, remain = self.broker.order_status(order_no)
            if filled >= qty:
                break
            time.sleep(self.poll)
        return filled, avg, remain

    # ── 진입 ──
    def enter(self, code: str, name: str, qty: int, limit_price: int, stop: float,
              signal_id: Optional[int]) -> int:
        res = self.broker.buy_limit(code, qty, limit_price)
        oid = self.j.order(signal_id, code, "buy", qty, limit_price, res.order_no,
                           "sent" if res.ok else "failed", self.mode, res.message)
        if not res.ok:
            self.j.event("오류", f"매수 주문 실패: {res.message}", code)
            self.notify(f"⚠️ {name} 매수 주문 실패: {res.message}")
            return 0
        filled, avg, remain = self._wait_fill(res.order_no, qty, self.fill_wait)
        if filled < qty:
            self.broker.cancel(res.order_no, code)
            filled, avg, _ = self.broker.order_status(res.order_no)
        self.j.update_order(oid, "filled" if filled >= qty else ("partial" if filled else "cancelled"), filled, avg)
        if filled <= 0:
            self.j.event("정보", f"{name} 매수 미체결 → 취소 ({limit_price:,}원)", code)
            return 0
        pos = Position(code=code, name=name, qty=filled, avg_price=avg or limit_price, stop=stop,
                       entry_time=now_kst().strftime("%H%M"), signal_id=signal_id)
        self.positions[code] = pos
        self.trade_ids[code] = self.j.open_trade(code, name, signal_id, pos.avg_price, filled, stop, self.mode)
        self.j.event("체결", f"{name} {filled}주 @{pos.avg_price:,.0f}원 매수 체결 · 손절 {stop:,.0f}", code)
        self.notify(f"✅ 매수 체결: {name} {filled}주 @{pos.avg_price:,.0f}원\n손절 {stop:,.0f}원 · 15:15 자동 청산\n"
                    f"(PC가 꺼질 때를 대비해 증권사 앱에 손절 예약을 걸어두세요)")
        return filled

    # ── 청산 ──
    def exit(self, code: str, reason: str, price_hint: float = 0.0) -> float:
        pos = self.positions.get(code)
        if not pos:
            return 0.0
        res = self.broker.sell(code, pos.qty, None)  # 손절·청산은 시장가로 확실히
        oid = self.j.order(pos.signal_id, code, "sell", pos.qty, 0, res.order_no, "sent" if res.ok else "failed",
                           self.mode, res.message)
        if not res.ok:
            self.j.event("오류", f"매도 주문 실패: {res.message} → 다음 루프에서 재시도", code)
            self.notify(f"⚠️ {pos.name} 매도 실패: {res.message} (재시도함, 필요하면 앱에서 직접 매도)")
            return 0.0
        filled, avg, _ = self._wait_fill(res.order_no, pos.qty, self.fill_wait)
        self.j.update_order(oid, "filled" if filled >= pos.qty else "partial", filled, avg)
        if filled <= 0:
            return 0.0
        px = avg or price_hint
        gross = (px - pos.avg_price) * filled
        cost = round_trip_cost(pos.avg_price * filled, px * filled, self.costs.get("fee_pct", 0.015),
                               self.costs.get("sell_tax_pct", 0.2))
        net = gross - cost
        if code in self.trade_ids:
            self.j.close_trade(self.trade_ids[code], px, reason, gross, cost)
        pos.qty -= filled
        if pos.qty <= 0:
            self.positions.pop(code, None)
            self.trade_ids.pop(code, None)
        self.j.event("매도", f"{pos.name} {filled}주 @{px:,.0f} {reason} · 손익 {net:+,.0f}원 (비용 {cost:,.0f})", code)
        self.notify(f"{'🔺' if net > 0 else '🔻'} {reason}: {pos.name} {filled}주 @{px:,.0f}원 · {net:+,.0f}원")
        return net

    def check_stops(self, prices: Dict[str, float]) -> float:
        realized = 0.0
        for code, pos in list(self.positions.items()):
            p = prices.get(code)
            if p and pos.stop and p <= pos.stop:
                realized += self.exit(code, "손절", p)
        return realized

    def flatten(self, prices: Dict[str, float], reason: str = "장마감 청산") -> float:
        return sum(self.exit(code, reason, prices.get(code, 0.0)) for code in list(self.positions))

    def unrealized(self, prices: Dict[str, float]) -> float:
        tot = 0.0
        for code, pos in self.positions.items():
            p = prices.get(code, pos.avg_price)
            tot += (p - pos.avg_price) * pos.qty - round_trip_cost(
                pos.avg_price * pos.qty, p * pos.qty, self.costs.get("fee_pct", 0.015), self.costs.get("sell_tax_pct", 0.2))
        return tot

    # ── 재시작 복원 ──
    def restore(self, stop_fn: Callable[[Position], float]) -> List[Position]:
        """잔고의 보유 종목을 다시 불러온다. 일지에 열린 거래가 있으면 그 손절가를 쓴다."""
        _, held, _ = self.broker.balance()
        open_trades = {t["code"]: t for t in self.j.open_trades()}
        for p in held:
            t = open_trades.get(p.code)
            if t:
                p.stop, p.signal_id = t["stop"], t["signal_id"]
                self.trade_ids[p.code] = t["id"]
            else:
                p.stop = stop_fn(p)
                self.trade_ids[p.code] = self.j.open_trade(p.code, p.name, None, p.avg_price, p.qty, p.stop, self.mode)
            self.positions[p.code] = p
            self.j.event("정보", f"보유 복원: {p.name} {p.qty}주 @{p.avg_price:,.0f} · 손절 {p.stop:,.0f}", p.code)
        return held
