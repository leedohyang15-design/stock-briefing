"""공통 데이터 구조."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KST = dt.timezone(dt.timedelta(hours=9))


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


@dataclass
class Bar:
    time: str          # "HHMM" (분봉) 또는 "YYYYMMDD" (일봉)
    open: float
    high: float
    low: float
    close: float
    volume: float
    date: str = ""     # 분봉일 때 "YYYYMMDD"


@dataclass
class Quote:
    code: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change_pct: float
    volume: float              # 누적 거래량
    upper_limit: float = 0.0   # 상한가
    vi_active: bool = False    # VI 발동 중(단일가) 여부


@dataclass
class Trade:
    """체결 1건 (틱)."""
    time: str
    price: float
    qty: float


@dataclass
class Position:
    code: str
    name: str
    qty: int
    avg_price: float
    stop: float
    entry_time: str = ""
    signal_id: Optional[int] = None


@dataclass
class OrderResult:
    ok: bool
    order_no: str = ""
    message: str = ""
    filled_qty: int = 0
    avg_price: float = 0.0


@dataclass
class AgentResult:
    """에이전트 1개의 판정. decision: pass | reject | wait | info."""
    no: int
    agent: str
    decision: str
    reason: str
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.decision == "reject"


@dataclass
class Candidate:
    code: str
    name: str
    source: str = ""          # pm | scanner
    pm_note: str = ""
    excluded: bool = False


@dataclass
class Signal:
    code: str
    name: str
    price: float
    or_high: float
    or_low: float
    atr: float
    stop: float
    qty: int = 0
    id: Optional[int] = None
    results: List[AgentResult] = field(default_factory=list)
