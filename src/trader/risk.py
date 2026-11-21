"""15. 리스크 매니저 — 거부권만 가진 코드 (LLM 없음). 주간 업데이트로 한도는 바뀌지 않는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set

from . import strategy as st
from .models import AgentResult
from .ticks import add_ticks


@dataclass
class DayState:
    start_equity: float
    cash: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    entries: int = 0
    positions: int = 0
    traded_codes: Set[str] = field(default_factory=set)
    stopped: bool = False          # /stop 또는 손실 한도 도달
    stop_reason: str = ""
    aggression: str = "normal"

    @property
    def pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def ret_pct(self) -> float:
        return self.pnl / self.start_equity * 100 if self.start_equity else 0.0


def max_entries(risk: Dict, aggression: str) -> int:
    n = int(risk.get("max_entries_per_day", 5))
    return max(1, n // 2) if aggression == "low" else n


def check_loss_limit(state: DayState, risk: Dict) -> bool:
    """손실 한도 도달 시 True (그리고 state.stopped 설정)."""
    if state.ret_pct <= -abs(risk.get("daily_loss_limit_pct", 3.0)):
        if not state.stopped:
            state.stopped = True
            state.stop_reason = f"일 손실 한도 {risk.get('daily_loss_limit_pct')}% 도달"
        return True
    return False


def evaluate(code: str, price: float, stop: float, now_hhmm: str, state: DayState, risk: Dict) -> AgentResult:
    """신규 진입 가능 여부와 수량. data: qty, limit_price."""
    def no(msg):
        return AgentResult(15, "리스크 매니저", "reject", msg)

    if state.stopped:
        return no(f"매매 중단 상태 ({state.stop_reason})")
    if check_loss_limit(state, risk):
        return no(state.stop_reason)
    if now_hhmm >= risk.get("entry_end", "15:10").replace(":", ""):
        return no(f"신규 진입 마감 {risk.get('entry_end')} 이후")
    if state.entries >= max_entries(risk, state.aggression):
        return no(f"오늘 매수 {state.entries}회 = 한도 ({max_entries(risk, state.aggression)}회)")
    if state.positions >= risk.get("max_positions", 2):
        return no(f"보유 {state.positions}종목 = 한도")
    if risk.get("one_entry_per_stock", True) and code in state.traded_codes:
        return no("오늘 이미 거래한 종목")
    limit = add_ticks(price, 1)
    if stop >= limit:
        return no("손절가가 진입가 이상 (계산 오류)")
    equity = state.start_equity + state.pnl
    qty = st.position_size(equity, risk.get("risk_per_trade_pct", 1.0), limit, stop,
                           risk.get("max_order_krw", 100000), state.cash)
    if qty <= 0:
        return no(f"수량 0 (1회 한도 {risk.get('max_order_krw'):,}원 / 예수금 {state.cash:,.0f}원으로 1주도 못 삼)")
    loss_at_stop = (limit - stop) * qty
    return AgentResult(15, "리스크 매니저", "pass",
                       f"{qty}주 × {limit:,}원 = {qty * limit:,}원 · 손절 시 -{loss_at_stop:,.0f}원 "
                       f"({loss_at_stop / equity * 100:.2f}%)",
                       {"qty": qty, "limit_price": limit, "loss_at_stop": loss_at_stop})
