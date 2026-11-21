"""쌓인 1분봉으로 ORB 규칙을 재현하는 백테스트 (주간 업데이트용).

재현하는 것: Stocks in Play 순위·필터, 시가범위 돌파 진입, VI 근처 진입 금지, ATR 손절, 청산 시각,
            동시 보유·하루 진입 횟수 한도, 비용.
재현 못 하는 것: 주문 불균형·뉴스 판정·타임머신·시장 분위기 (과거 체결·뉴스 데이터가 없음),
                체결 미끄러짐. 그래서 결과는 '규칙 자체의 성능' 추정치다.
한계: 우리가 저장한 종목(그날 관심·Stocks in Play 후보)만 대상이라 표본 편향이 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import strategy as st
from .journal import Journal
from .settings import Settings
from .ticks import add_ticks, cost_pct


@dataclass
class BTTrade:
    date: str
    code: str
    entry_time: str
    entry: float
    exit: float
    exit_time: str
    reason: str
    ret_pct: float      # 비용 차감 수익률 (%)
    weight: float       # 계좌 대비 비중
    features: Dict = field(default_factory=dict)


@dataclass
class BTResult:
    trades: List[BTTrade]
    daily: Dict[str, float]          # 날짜 → 일 수익률(%)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def mean_daily(self) -> float:
        return sum(self.daily.values()) / len(self.daily) if self.daily else 0.0

    @property
    def win_rate(self) -> float:
        return sum(1 for t in self.trades if t.ret_pct > 0) / self.n * 100 if self.n else 0.0


def _day_candidates(journal: Journal, date: str, s: Settings):
    cfg = s.strategy
    codes = [r["code"] for r in journal.query("SELECT DISTINCT code FROM bars WHERE date=?", (date,))]
    rows = []
    for code in codes:
        bars = journal.bars(code, date)
        daily = journal.daily_bars(code, before=date, n=cfg.get("atr_days", 14) + 1)
        rng = st.opening_range(bars, cfg["orb_minutes"])
        a = st.atr(daily, cfg.get("atr_days", 14))
        if not rng or not a or len(daily) < 5:
            continue
        if rng.close < cfg["min_price"] or st.avg_value(daily) < cfg["min_avg_value_krw"]:
            continue
        if a / rng.close * 100 < cfg["min_atr_pct"]:
            continue
        rv = st.relative_volume(rng.volume, st.avg_volume(daily), cfg["open_volume_share"])
        if rv < cfg["relvol_min"]:
            continue
        rows.append((rv, code, bars, rng, a))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows[: cfg["relvol_top_n"]]


def run(journal: Journal, s: Settings, dates: Sequence[str], equity: float = 1_000_000.0) -> BTResult:
    cfg, risk, costs = s.strategy, s.risk, s.costs
    cpct = cost_pct(costs.get("fee_pct", 0.015), costs.get("sell_tax_pct", 0.2))
    entry_end = risk.get("entry_end", "15:10").replace(":", "")
    flatten = risk.get("flatten_time", "15:15").replace(":", "")
    trades: List[BTTrade] = []
    daily: Dict[str, float] = {}
    for date in dates:
        day_trades: List[BTTrade] = []
        for rv, code, bars, rng, a in _day_candidates(journal, date, s):
            if cfg.get("require_bullish_or", True) and not rng.bullish:
                continue
            after = [b for b in bars if rng.end <= b.time < flatten]
            i = next((k for k, b in enumerate(after) if b.high > rng.high and b.time < entry_end), None)
            if i is None:
                continue
            entry = max(add_ticks(rng.high, 1), after[i].open)
            room = st.vi_room_pct(entry, rng.open, cfg["static_vi_pct"])
            if room <= cfg["vi_guard_pct"]:
                continue
            stop = st.stop_price(entry, a, cfg["stop_atr_mult"])
            qty = st.position_size(equity, risk.get("risk_per_trade_pct", 1.0), entry, stop,
                                   risk.get("max_order_krw", 100000), equity)
            if qty <= 0:
                continue
            exit_px, exit_t, reason = None, after[-1].time, "청산"
            for b in after[i + 1:]:
                if b.low <= stop:
                    exit_px, exit_t, reason = stop, b.time, "손절"
                    break
            if exit_px is None:
                exit_px = after[-1].close
            ret = (exit_px / entry - 1) * 100 - cpct
            day_trades.append(BTTrade(date, code, after[i].time, entry, exit_px, exit_t, reason, ret,
                                      qty * entry / equity,
                                      {"relvol": round(rv, 2), "entry_time": after[i].time, "vi_room": round(room, 2),
                                       "or_width_pct": round((rng.high - rng.low) / rng.low * 100, 2)}))
        # 진입 순서대로 동시 보유·하루 진입 한도 적용
        day_trades.sort(key=lambda t: t.entry_time)
        kept: List[BTTrade] = []
        for t in day_trades:
            if len(kept) >= risk.get("max_entries_per_day", 5):
                break
            open_now = [k for k in kept if k.exit_time > t.entry_time]
            if len(open_now) >= risk.get("max_positions", 2):
                continue
            kept.append(t)
        if kept:
            daily[date] = sum(t.ret_pct * t.weight for t in kept)
        elif _day_has_data(journal, date):
            daily[date] = 0.0
        trades.extend(kept)
    return BTResult(trades, daily)


def _day_has_data(journal: Journal, date: str) -> bool:
    return bool(journal.query("SELECT 1 FROM bars WHERE date=? LIMIT 1", (date,)))


def estimate_open_share(journal: Journal, minutes: int) -> Optional[float]:
    """저장 데이터로 '하루 거래량 중 시가범위 구간 비중' 실측."""
    shares = []
    for r in journal.query("SELECT DISTINCT code, date FROM bars"):
        bars = journal.bars(r["code"], r["date"])
        if len(bars) < 300:
            continue
        rng = st.opening_range(bars, minutes)
        tot = sum(b.volume for b in bars)
        if rng and tot:
            shares.append(rng.volume / tot)
    if len(shares) < 20:
        return None
    shares.sort()
    return round(shares[len(shares) // 2], 4)
