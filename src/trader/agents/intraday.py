"""B. 장중 실행팀 — 에이전트 9~14 (15 리스크는 risk.py, 16 실행은 executor.py, 18 타임머신은 timemachine.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .. import strategy as st
from ..models import AgentResult, Bar, Candidate, Quote, Trade


# ── 9. Stocks in Play 스캐너 ─────────────────────────────
@dataclass
class InPlay:
    code: str
    name: str
    relvol: float
    atr: float
    rng: st.OpeningRange
    avg_value: float
    prev_close: float
    note: str = ""
    relvol_measured: bool = False   # True = 같은 시간대 과거 거래량 실측, False = 일거래량 비율 추정


def scan_stocks_in_play(cands: Sequence[Candidate], or_bars: Dict[str, List[Bar]], daily: Dict[str, List[Bar]],
                        cfg: Dict[str, Any], open_avg: Optional[Dict[str, tuple]] = None) -> (List[InPlay], AgentResult):
    """상대거래량 순위 (Zarattini 외). 필터: 최소 주가, 평균 거래대금, ATR%.

    open_avg: {code: (과거 같은 시간대 평균 거래량, 일수)}. 일수가 relvol_min_days 이상이면 실측, 아니면 추정."""
    open_avg = open_avg or {}
    rows: List[InPlay] = []
    skipped: Dict[str, str] = {}
    for c in cands:
        d = daily.get(c.code) or []
        bars = or_bars.get(c.code) or []
        rng = st.opening_range(bars, cfg["orb_minutes"])
        a = st.atr(d, cfg.get("atr_days", 14))
        if rng is None or a is None or len(d) < 5:
            skipped[c.code] = "데이터 부족"
            continue
        price = rng.close
        avgv = st.avg_value(d, cfg.get("atr_days", 14))
        if price < cfg["min_price"]:
            skipped[c.code] = "주가 기준 미달"
            continue
        if avgv < cfg["min_avg_value_krw"]:
            skipped[c.code] = "평균 거래대금 미달"
            continue
        if a / price * 100 < cfg["min_atr_pct"]:
            skipped[c.code] = "변동성(ATR) 미달"
            continue
        avg_open, n_days = open_avg.get(c.code, (0.0, 0))
        measured = n_days >= cfg.get("relvol_min_days", 10) and avg_open > 0
        rv = (rng.volume / avg_open) if measured else \
            st.relative_volume(rng.volume, st.avg_volume(d, cfg.get("atr_days", 14)), cfg["open_volume_share"])
        if rv < cfg["relvol_min"]:
            skipped[c.code] = f"상대거래량 {rv:.1f} < {cfg['relvol_min']}"
            continue
        rows.append(InPlay(code=c.code, name=c.name, relvol=rv, atr=a, rng=rng, avg_value=avgv,
                           prev_close=d[-1].close, note=c.pm_note, relvol_measured=measured))
    rows.sort(key=lambda r: r.relvol, reverse=True)
    top = rows[: cfg["relvol_top_n"]]
    txt = ", ".join(f"{r.name}({r.relvol:.1f}배{'' if r.relvol_measured else ' 추정'})" for r in top) or "조건을 만족하는 종목 없음"
    return top, AgentResult(9, "Stocks in Play", "info", f"상위 {len(top)}종목: {txt}",
                            {"top": [{"code": r.code, "name": r.name, "relvol": round(r.relvol, 2)} for r in top],
                             "skipped": skipped})


def sip_result(ip: InPlay, rank: int) -> AgentResult:
    how = "같은 시간대 과거 평균 대비 실측" if ip.relvol_measured else "일거래량 비율로 추정"
    return AgentResult(9, "Stocks in Play", "pass", f"상대거래량 {ip.relvol:.1f}배 ({how}), {rank}위",
                       {"relvol": ip.relvol, "measured": ip.relvol_measured})


# ── 10. ORB 신호 ──────────────────────────────────────
def orb_check(price: float, ip: InPlay, require_bullish: bool) -> AgentResult:
    r = ip.rng
    if require_bullish and not r.bullish:
        return AgentResult(10, "ORB 신호", "reject", f"시가범위가 음봉 (시가 {r.open:,.0f} > 종가 {r.close:,.0f}) → 매수 안 함")
    if price > r.high:
        return AgentResult(10, "ORB 신호", "pass", f"현재가 {price:,.0f} > 시가범위 상단 {r.high:,.0f} 돌파",
                           {"or_high": r.high, "or_low": r.low})
    return AgentResult(10, "ORB 신호", "wait", f"시가범위 안 ({r.low:,.0f}~{r.high:,.0f})")


# ── 11. 주문 불균형 ──────────────────────────────────
def imbalance_check(trades: Sequence[Trade], n: int, min_oib: float, require_data: bool = True) -> AgentResult:
    buy, sell, oib = st.order_imbalance(list(trades)[:n])
    pct = buy / (buy + sell) * 100 if buy + sell else 50.0
    data = {"buy": buy, "sell": sell, "oib": round(oib, 3), "buy_pct": round(pct, 1)}
    if buy + sell == 0:
        if not require_data:
            return AgentResult(11, "주문 불균형", "info", "체결 데이터를 못 받아 참고만 (거부 안 함)", data)
        return AgentResult(11, "주문 불균형", "reject", "최근 체결 데이터 없음", data)
    if oib > min_oib:
        return AgentResult(11, "주문 불균형", "pass", f"매수 주도 {pct:.0f}% (불균형 {oib:+.2f})", data)
    return AgentResult(11, "주문 불균형", "reject", f"매도 주도 우세 (매수 {pct:.0f}%, 불균형 {oib:+.2f})", data)


def recent_only(rows: List[Dict[str, str]], now, hours: float) -> List[Dict[str, str]]:
    """date(YYYYMMDD)·time(HHMMSS) 가 있는 항목 중 최근 hours 시간 이내만. 날짜가 없으면 남긴다."""
    import datetime as _dt
    out = []
    for r in rows:
        d, t = r.get("date", ""), (r.get("time", "") or "000000").ljust(6, "0")
        if len(d) != 8:
            out.append(r)
            continue
        try:
            ts = _dt.datetime.strptime(d + t[:6], "%Y%m%d%H%M%S").replace(tzinfo=now.tzinfo)
        except ValueError:
            out.append(r)
            continue
        if (now - ts).total_seconds() <= hours * 3600:
            out.append(r)
    return out


# ── 12. 실시간 뉴스·공시 확인 (Lopez-Lira·Tang: 악재 거부용) ──
def news_check(llm, name: str, news: List[Dict[str, str]], notices: List[Dict[str, str]],
               keywords: List[str], llm_required: bool) -> AgentResult:
    items = [("공시", n) for n in notices[:8]] + [("뉴스", n) for n in news[:10]]
    for kind, n in items:
        hit = next((k for k in keywords if k in n.get("title", "")), None)
        if hit:
            return AgentResult(12, "실시간 뉴스·공시", "reject", f"{kind} 악재 키워드 '{hit}': {n['title']}",
                               {"title": n["title"], "date": n.get("date", "")})
    if not items:
        return AgentResult(12, "실시간 뉴스·공시", "pass", "최근 뉴스·공시 없음")
    if not llm.available:
        if llm_required:
            return AgentResult(12, "실시간 뉴스·공시", "reject", "LLM 없음 → 보수적으로 거부 (llm_required)")
        return AgentResult(12, "실시간 뉴스·공시", "pass", "키워드 악재 없음 (LLM 미사용)")
    lines = "\n".join(f"- [{k}] {n.get('date', '')} {n['title']}" for k, n in items)
    out = llm.json("너는 주식 단타팀의 실시간 뉴스·공시 확인 담당이다. 뉴스가 영어면 영어로 이해하고 한국어로 답한다. 호재 여부가 아니라 '오늘 장중 급락이나 "
                   "거래정지 위험이 있는 악재'가 있는지만 판단한다.",
                   f"종목: {name}\n최근 뉴스·공시:\n{lines}\n\n"
                   '형식: {"verdict": "pass 또는 reject", "reason": "한 문장"}', 300)
    if not out or out.get("verdict") not in ("pass", "reject"):
        if llm_required:
            return AgentResult(12, "실시간 뉴스·공시", "reject", "LLM 판정 실패 → 보수적으로 거부")
        return AgentResult(12, "실시간 뉴스·공시", "pass", "LLM 판정 실패, 키워드 악재 없음")
    return AgentResult(12, "실시간 뉴스·공시", out["verdict"], out.get("reason", ""), {"checked": len(items)})


# ── 13. 시장 분위기 ───────────────────────────────────
def regime_check(index_change_pct: float, block_below_pct: float, market: str = "코스피·코스닥") -> AgentResult:
    """뚜렷한 약세장(지수 평균 등락률 < 기준)에서만 신규 매수 중단. 매수만 하는 전략이라 급락장 회피용.

    참고: Gao 외(JFE 2018)는 '첫 30분이 마지막 30분을 예측'한다는 연구로, 하루 전체 진입 금지의 직접 근거는 아니다.
    기준값은 백테스트로 검증할 수 없어(과거 지수 분봉 미보관) 보수적인 고정값(-1%)으로 둔다."""
    data = {"index_change_pct": index_change_pct, "block_below_pct": block_below_pct}
    if index_change_pct < block_below_pct:
        return AgentResult(13, "시장 분위기", "reject",
                           f"{market} 평균 {index_change_pct:+.2f}% < {block_below_pct:+.1f}% (뚜렷한 약세) → 신규 진입 중단", data)
    return AgentResult(13, "시장 분위기", "pass", f"{market} 평균 {index_change_pct:+.2f}% (기준 {block_below_pct:+.1f}% 이상)", data)


# ── 14. VI 감시 ─────────────────────────────────────
def vi_check(q: Quote, reference: float, static_pct: float, guard_pct: float) -> AgentResult:
    if static_pct <= 0:
        return AgentResult(14, "VI 감시", "pass", "이 시장은 정적 VI 제도가 없어 생략")
    if q.vi_active:
        return AgentResult(14, "VI 감시", "reject", "VI 발동 중 (단일가 매매) → 진입 금지")
    ref = st.vi_reference(reference, q.price, static_pct)     # 이미 발동한 VI 를 반영한 추정 기준가
    room = st.vi_room_pct(q.price, ref, static_pct)
    upper = st.static_vi_upper(ref, static_pct)
    data = {"room_pct": round(room, 2), "upper": upper}
    if room <= guard_pct:
        return AgentResult(14, "VI 감시", "reject", f"정적 VI 발동가(추정) {upper:,.0f}까지 {room:+.1f}% (기준 {guard_pct}%) → 진입 금지", data)
    if q.upper_limit and q.price >= q.upper_limit * 0.97:
        return AgentResult(14, "VI 감시", "reject", "상한가 근접 → 진입 금지", data)
    return AgentResult(14, "VI 감시", "pass", f"정적 VI 발동가(추정 {upper:,.0f})까지 +{room:.1f}%", data)
