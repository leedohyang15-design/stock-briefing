"""18. 타임머신 — 진입 전에 그날 남은 장을 10,000번 재생 (day-trader-skill 방식 응용).

1) 몬테카를로: 남은 각 분마다, 같은 종목의 과거 거래일 '같은 시각' 1분 수익률·저가를 무작위로 골라 경로를 만든다.
   손절가에 먼저 닿는지, 청산 시각까지 수익/손실인지 집계한다.
2) 과거 재현: 과거 거래일마다 같은 ORB 규칙이 발동했는지 보고 실제 결과를 센다.
판정: 비용 차감 기대수익(%)이 기준 이하이면 거부. 과거 데이터가 부족하면 '참고'만 한다.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .. import strategy as st
from ..models import AgentResult, Bar


def _minute_grid(start: str, end: str) -> List[str]:
    out, t = [], start
    while t < end:
        out.append(t)
        t = st.hhmm_add(t, 1)
    return out


def simulate(history: Dict[str, List[Bar]], now_hhmm: str, flatten_hhmm: str, entry: float, stop: float,
             paths: int = 10000, seed: int = 19, cost_pct: float = 0.23) -> Optional[Dict[str, float]]:
    minutes = _minute_grid(st.hhmm_add(now_hhmm, 1), flatten_hhmm)
    if not minutes or not history:
        return None
    rets, lows = [], []
    for bars in history.values():
        by_t = {b.time: b for b in bars}
        r_row, l_row = [], []
        before = [b for b in bars if b.time < minutes[0]]
        prev = before[-1].close if before else None
        ok = True
        for t in minutes:
            b = by_t.get(t)
            if not prev:
                ok = False
                break
            if b is None:  # 체결 없는 분 → 가격 변화 없음으로 처리
                r_row.append(0.0)
                l_row.append(0.0)
                continue
            r_row.append(b.close / prev - 1)
            l_row.append(b.low / prev - 1)
            prev = b.close
        if ok:
            rets.append(r_row)
            lows.append(l_row)
    if len(rets) < 2:
        return None
    R, L = np.array(rets), np.array(lows)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, R.shape[0], size=(paths, R.shape[1]))
    step_r = R[pick, np.arange(R.shape[1])]
    step_l = L[pick, np.arange(R.shape[1])]
    closes = entry * np.cumprod(1 + step_r, axis=1)
    prev_close = np.concatenate([np.full((paths, 1), entry), closes[:, :-1]], axis=1)
    low_px = prev_close * (1 + step_l)
    stopped = (low_px <= stop).any(axis=1)
    final = closes[:, -1]
    exit_px = np.where(stopped, stop, final)
    ret = (exit_px / entry - 1) * 100 - cost_pct
    return {
        "days": int(R.shape[0]),
        "p_stop": float(stopped.mean() * 100),
        "p_eod_profit": float(((~stopped) & (final > entry)).mean() * 100),
        "p_eod_loss": float(((~stopped) & (final <= entry)).mean() * 100),
        "ev_pct": float(ret.mean()),
    }


def replay_history(history: Dict[str, List[Bar]], orb_minutes: int, atr_value: float, stop_mult: float,
                   flatten_hhmm: str, require_bullish: bool = True) -> Dict[str, int]:
    """과거 거래일마다 같은 ORB 규칙을 적용했을 때의 결과."""
    res = {"fired": 0, "profit": 0, "stop": 0, "loss": 0}
    for bars in history.values():
        rng = st.opening_range(bars, orb_minutes)
        if rng is None or (require_bullish and not rng.bullish):
            continue
        after = [b for b in bars if rng.end <= b.time < flatten_hhmm]
        entry_i = next((i for i, b in enumerate(after) if b.high > rng.high), None)
        if entry_i is None:
            continue
        res["fired"] += 1
        entry = max(rng.high, after[entry_i].open)
        stp = st.stop_price(entry, atr_value, stop_mult)
        out = None
        for b in after[entry_i + 1:]:
            if b.low <= stp:
                out = "stop"
                break
        if out is None:
            last = after[-1].close if after else entry
            out = "profit" if last > entry else "loss"
        res[out] += 1
    return res


def check(history: Dict[str, List[Bar]], now_hhmm: str, flatten_hhmm: str, entry: float, stop: float,
          atr_value: float, cfg_tm: Dict, cfg_st: Dict, cost_pct: float) -> AgentResult:
    if not cfg_tm.get("enabled", True):
        return AgentResult(18, "타임머신", "info", "사용 안 함")
    days = len(history)
    if days < cfg_tm.get("min_days", 10):
        return AgentResult(18, "타임머신", "info", f"과거 분봉 {days}일뿐 (기준 {cfg_tm.get('min_days', 10)}일) → 참고만, 거부 안 함",
                           {"days": days})
    sim = simulate(history, now_hhmm, flatten_hhmm, entry, stop, cfg_tm.get("paths", 10000),
                   cfg_tm.get("seed", 19), cost_pct)
    hist = replay_history(history, cfg_st["orb_minutes"], atr_value, cfg_st["stop_atr_mult"], flatten_hhmm,
                          cfg_st.get("require_bullish_or", True))
    if sim is None:
        return AgentResult(18, "타임머신", "info", "남은 시간대 데이터 부족 → 참고만", {"history": hist})
    data = {**{k: round(v, 2) for k, v in sim.items()}, "history": hist}
    msg = (f"손절 먼저 {sim['p_stop']:.0f}% · 마감 수익 {sim['p_eod_profit']:.0f}% · 마감 손실 {sim['p_eod_loss']:.0f}% · "
           f"기대 {sim['ev_pct']:+.2f}% (과거 {hist['fired']}회 발동: 수익 {hist['profit']} 손절 {hist['stop']} 손실 {hist['loss']})")
    if sim["ev_pct"] <= cfg_tm.get("reject_if_ev_below_pct", 0.0):
        return AgentResult(18, "타임머신", "reject", "기대수익 부족 → " + msg, data)
    return AgentResult(18, "타임머신", "pass", msg, data)
