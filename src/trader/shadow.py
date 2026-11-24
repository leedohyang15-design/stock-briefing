"""그림자 거래: 에이전트가 거부했거나 사용자가 승인하지 않은 신호를 '샀다면 어땠을지' 끝까지 추적.

실제 주문은 없다. 같은 규칙(미끄러짐, 손절가, 청산 시각, 비용)을 적용해 결과를 일지에 남긴다.
→ 필터(에이전트)가 실제로 손실을 막았는지, 수익을 놓쳤는지 데이터로 판단할 수 있다.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .journal import Journal
from .ticks import add_ticks, fmt_px


class ShadowBook:
    def __init__(self, journal: Journal, slippage_ticks: int, cost_pct: float, log: Callable[[str, str], None]):
        self.j = journal
        self.slip = int(slippage_ticks)
        self.cost = cost_pct
        self.log = log            # log(code, text)

    def has(self, code: str, date: str) -> bool:
        return bool(self.j.query("SELECT 1 FROM shadow WHERE date=? AND code=? LIMIT 1", (date, code)))

    def open(self, code: str, name: str, signal_id: Optional[int], reason_no: int, reason: str,
             price: float, stop: float, date: str) -> Optional[int]:
        if self.has(code, date):
            return None          # 종목당 하루 1건 (실제 규칙과 동일)
        entry = add_ticks(price, self.slip) if self.slip else price
        sid = self.j.open_shadow(code, name, signal_id, reason_no, reason, entry, stop)
        self.log(code, f"👻 그림자 거래 시작: {name} 를 샀다면 {fmt_px(entry)} 진입 · 손절 {fmt_px(stop)} (실제 주문 없음)")
        return sid

    def _close(self, row: Dict, price: float, why: str) -> float:
        exit_px = add_ticks(price, -self.slip) if self.slip else price
        ret = (exit_px / row["entry_price"] - 1) * 100 - self.cost
        self.j.close_shadow(row["id"], exit_px, why, ret)
        verdict = "거부가 손실을 막았어요" if ret < 0 else "거부 때문에 수익을 놓쳤어요"
        self.log(row["code"], f"👻 그림자 결과: {row['name']} {why} {ret:+.2f}% → {verdict} ({row['reason_no']}번 거부)")
        return ret

    def update(self, prices: Dict[str, float]) -> None:
        for row in self.j.open_shadows():
            p = prices.get(row["code"])
            if p and row["stop"] and p <= row["stop"]:
                self._close(row, min(p, row["stop"]), "손절")

    def flatten(self, prices: Dict[str, float]) -> List[float]:
        out = []
        for row in self.j.open_shadows():
            p = prices.get(row["code"])
            if p:
                out.append(self._close(row, p, "장마감 청산"))
        return out
