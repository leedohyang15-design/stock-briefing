"""수집·요약된 데이터를 이메일 본문(HTML + 텍스트)으로 조립.

섹션 구성:
  인사말
  🐜 오늘의 개미 체크포인트  (출근길 10초 요약 — 이미 모은 데이터만으로 조립)
  🌐 [1] 마켓 뷰 (지수 & 환율)
  🔥 [2] 오늘의 주도 섹터 & 주목 종목  (테마별 종목 + 흐름 요약)
       └ 💰 수급 & 거래대금: 거래대금 상위 / 외국인·기관 순매수·순매도 (네이버)
  📰 [3] 전일 주요 이슈 & 뉴스  (클릭 가능한 링크)
  🚨 [4] 오늘의 주요 일정 & 리스크
"""
from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from typing import List

_GREETING = "안녕하세요, 개인 투자자분들을 위한 출근길 브리핑입니다. 오늘도 성투하세요!"


@dataclass
class Briefing:
    trade_day: dt.date
    today: dt.date
    index_quotes: list              # 섹션 1 원본 (IndexQuote: .group/.name/.value/.change_pct/.arrow)
    indices_comment: str            # 섹션 1 💡 관전 포인트
    megacaps: list = field(default_factory=list)  # 🏢 핵심 대형주 (시총 상위 벨웨더, Stock — 항상 고정 노출)
    theme_groups: list = field(default_factory=list)  # 섹션2 🏢 주도 섹터 (ThemeGroup, 그날 강한 순 정렬)
    trending_themes: list = field(default_factory=list)  # (미사용/하위호환)
    market_oneliner: str = ""       # 🐜 체크포인트 '오늘의 핵심' 한 줄
    value_top: list = field(default_factory=list)   # 섹션2 💰 거래대금 상위 (Stock)
    net_buy: dict = field(default_factory=dict)      # 섹션2 💰 외국인·기관 순매수 {'외국인':[Stock],'기관':[Stock]}
    net_sell: dict = field(default_factory=dict)     # 섹션2 💰 외국인·기관 순매도(스마트머니가 던진 종목)
    retail_net_buy: list = field(default_factory=list)  # 섹션2 💰 개인 순매수(군중 쏠림 — 고점 물림 주의)
    issues: list = field(default_factory=list)   # 섹션 3 (Issue: .title/.url)
    calendar_summary: str = ""      # 섹션 4 (폴백용 텍스트 — 이벤트 없을 때)
    calendar_events: list = field(default_factory=list)  # 섹션4 구조화 일정 (CalendarEvent: .title/.note/.category/.days_until)


def _esc(t: str) -> str:
    return html.escape(t)


def _nl2br(t: str) -> str:
    return html.escape(t).replace("\n", "<br>")


def build_subject(b: Briefing) -> str:
    return f"📈 데일리 주식 브리핑 ({b.today.strftime('%m/%d')} 아침)"


def _sign(v: float) -> str:
    return "+" if v > 0 else ""


def _arrow(v: float) -> str:
    """등락 방향 이모지 — 한눈에 상승/하락 구분."""
    return "📈" if v > 0 else ("📉" if v < 0 else "➖")


def _stock_price(s) -> str:
    """종목 가격 표기: 국내(KRW)는 '원', 해외(USD)는 '$'."""
    if getattr(s, "currency", "KRW") == "USD":
        return f"${s.close:,.2f}"
    return f"{s.close:,.0f}원"


def _rep_stocks(g):
    """섹터에서 대표 국내 1 + 미국 1 종목(첫 유효 종목)을 반환. (없으면 None)"""
    kr = next((s for s in g.stocks
               if getattr(s, "currency", "KRW") != "USD" and getattr(s, "ok", True)), None)
    us = next((s for s in g.stocks
               if getattr(s, "currency", "KRW") == "USD" and getattr(s, "ok", True)), None)
    return kr, us


def _pct_html(v: float) -> str:
    """📈/📉 이모지 + 색상 등락률 (HTML)."""
    return (f"{_arrow(v)} <span style='color:{_pct_color(v)};font-weight:600;'>"
            f"{_sign(v)}{v:.2f}%</span>")
  
def _eok(v) -> str:
    """원 단위 금액 → '1,234억' 문자열."""
    return f"{(v or 0) / 1e8:,.0f}억"


def _amt(v, sign: str) -> str:
    """금액이 있으면 '(+1,234억)', 없으면 빈 문자열(수량 기준 순매매엔 금액 미표기)."""
    return f"({sign}{_eok(v)})" if v else ""

def _pct_text(v: float) -> str:
    """📈/📉 이모지 + 등락률 (텍스트)."""
    return f"{_arrow(v)} {_sign(v)}{v:.2f}%"


# ── 🏢 핵심 대형주 (시총 상위 벨웨더 — 통화로 국내/미국 구분) ──
def _megacaps_split(stocks):
    """대형주 리스트를 (국내, 미국)으로 분리. yaml 순서 유지."""
    kr = [s for s in stocks if getattr(s, "currency", "KRW") != "USD"]
    us = [s for s in stocks if getattr(s, "currency", "KRW") == "USD"]
    return kr, us


def _megacaps_html(stocks) -> str:
    """등락률 색상 포함, 국내/미국 라벨로 묶어 렌더. 없으면 빈 문자열."""
    if not stocks:
        return ""
    kr, us = _megacaps_split(stocks)

    def _grp(label: str, rows) -> str:
        if not rows:
            return ""
        lis = "".join(
            f"<div style='margin:3px 0;'>{_esc(s.name)}: {_stock_price(s)} {_pct_html(s.change_pct)}</div>"
            for s in rows
        )
        return (
            f"<div style='margin:8px 0 4px;'>"
            f"<span style='display:inline-block;font-size:11px;font-weight:600;color:#fff;"
            f"background:#495057;border-radius:4px;padding:1px 8px;margin-bottom:4px;'>{label}</span>"
            f"{lis}</div>"
        )

    return _grp("국내", kr) + _grp("미국", us)


def _megacaps_text_lines(stocks) -> List[str]:
    if not stocks:
        return []
    kr, us = _megacaps_split(stocks)
    lines: List[str] = []
    for label, rows in (("국내", kr), ("미국", us)):
        if rows:
            lines.append(f"· {label}: " + ", ".join(
                f"{s.name} {_stock_price(s)} {_pct_text(s.change_pct)}" for s in rows))
    return lines


_INDEX_ORDER = ["국내", "해외", "환율", "안전자산·원자재"]


def _index_value(q) -> str:
    """지수/자산 값 표기: 환율은 '원' 접미, 안전자산·원자재는 '$' 접두."""
    if q.group == "환율":
        return f"{q.value:,.2f}원"
    if q.group == "안전자산·원자재":
        return f"${q.value:,.2f}"
    return f"{q.value:,.2f}"


def _fmt_index(q) -> str:
    return f"{q.name} {_index_value(q)} ({_arrow(q.change_pct)} {_sign(q.change_pct)}{q.change_pct:.2f}%)"


def _index_lines(quotes) -> List[str]:
    """그룹(국내/해외/환율/안전자산·원자재)별로 한 줄씩 묶어 반환 (텍스트용)."""
    order = _INDEX_ORDER
    lines = []
    for grp in order:
        items = [_fmt_index(q) for q in quotes if q.group == grp]
        if items:
            lines.append(" | ".join(items))
    return lines


def _pct_color(v: float) -> str:
    """등락률 색: 상승=빨강, 하락=파랑, 보합=회색 (국내 증시 관례)."""
    return "#e03131" if v > 0 else ("#1c7ed6" if v < 0 else "#868e96")


def _fmt_index_html(q) -> str:
    """지수 한 종목을 HTML 로 (등락률 부분에 색상)."""
    col = _pct_color(q.change_pct)
    return (
        f"{_esc(q.name)} {_index_value(q)} "
        f"{_arrow(q.change_pct)} <span style='color:{col};font-weight:700;'>"
        f"{_sign(q.change_pct)}{q.change_pct:.2f}%</span>"
    )


def _index_html_blocks(quotes) -> str:
    """그룹(국내/해외/환율/안전자산·원자재) 라벨 + 종목당 한 줄로 렌더."""
    order = _INDEX_ORDER
    out = []
    for grp in order:
        qs = [q for q in quotes if q.group == grp]
        if not qs:
            continue
        rows = "".join(
            f"<div style='margin:2px 0;'>{_fmt_index_html(q)}</div>"
            for q in qs
        )
        out.append(
            f"<div style='margin:10px 0 4px;'>"
            f"<span style='display:inline-block;font-size:11px;font-weight:600;color:#fff;"
            f"background:#868e96;border-radius:4px;padding:1px 8px;margin-bottom:4px;'>{grp}</span>"
            f"{rows}</div>"
        )
    return "".join(out) or "<div>데이터 없음</div>"


# ── 🐜 오늘의 개미 체크포인트 (이미 수집한 데이터만으로 조립, 외부 호출 없음) ──
def _tldr_lines(b: Briefing) -> List[str]:
    """출근길 10초 요약. index_quotes/theme_groups/수급/일정에서 핵심만 뽑는다."""
    out: List[str] = []

    def _q(name: str):
        return next((q for q in b.index_quotes if q.name == name), None)

    # 1) 지수 방향 (코스피·나스닥)
    idx_bits = []
    for nm in ("코스피", "나스닥"):
        q = _q(nm)
        if q is not None:
            idx_bits.append(f"{nm} {_sign(q.change_pct)}{q.change_pct:.1f}%")
    if idx_bits:
        out.append("🌐 지수: " + " · ".join(idx_bits))

    # 2) 오늘의 핵심 (LLM 한 줄 요약, 없으면 주도 섹터로 폴백)
    if b.market_oneliner:
        out.append(f"🔥 오늘의 핵심: {b.market_oneliner}")
    elif b.theme_groups:
        g = b.theme_groups[0]
        out.append(f"🔥 주도 섹터: {g.name} ({g.label})")

    # 3) 외국인 수급 한 줄 (순매수 우선, 없으면 순매도)
    fo_buy = (b.net_buy or {}).get("외국인")
    fo_sell = (b.net_sell or {}).get("외국인")
    if fo_buy:
        out.append(f"🟢 외국인 순매수: {fo_buy[0].name} 등")
    elif fo_sell:
        out.append(f"🔴 외국인 순매도 우위: {fo_sell[0].name} 등")

    # 4) 금일 일정 (중요도 높은 순으로 최대 3개)
    _rank = {"🔥": 0, "⚡": 1, "❄️": 2}
    notable = sorted(
        (e for e in b.calendar_events if e.days_until == 0 and e.category != "시장"),
        key=lambda e: _rank.get(getattr(e, "impact", ""), 3))
    if notable:
        bits = " · ".join(
            f"{getattr(e, 'impact', '')}{e.title.replace('실적발표: ', '실적 ')}".strip()
            for e in notable[:3])
        out.append(f"🗓️ 금일 일정: {bits}")
    else:
        out.append("🗓️ 금일: 예정된 주요 지표·실적 없음")

    return out


# ── 📅 [4] 일정: 날짜별로 묶은 주간 캘린더 ────────────────
_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _cat_icon(cat: str) -> str:
    return {"시장": "🏳️", "실적": "📊", "매크로": "📈", "락업해제": "🔓"}.get(cat, "•")


def _ev_icon(e) -> str:
    """이벤트 아이콘: 중요도(🔥/⚡/❄️)가 있으면 그걸, 없으면 카테고리 아이콘."""
    return getattr(e, "impact", "") or _cat_icon(e.category)


def _time_key(e) -> int:
    """금일 시간표 정렬용: 'HH:MM'을 분으로. (익일)은 +24h, 시간 없으면 맨 뒤."""
    t = getattr(e, "time", "") or ""
    try:
        base = int(t[:2]) * 60 + int(t[3:5])
        return base + (24 * 60 if "익일" in t else 0)
    except (ValueError, IndexError):
        return 9999


def _events_by_day(events):
    """days_until 별로 묶고(오름차순), 각 날짜 안은 시간순으로 정렬."""
    by_day = {}
    for e in events:
        by_day.setdefault(e.days_until, []).append(e)
    for d in by_day:
        by_day[d].sort(key=_time_key)
    return [(d, by_day[d]) for d in sorted(by_day)]


def _calendar_text(b: Briefing) -> List[str]:
    if not b.calendar_events:
        return [b.calendar_summary or "이번 주 예정된 주요 일정이 없습니다. (그래도 뇌동매매는 금물!)"]
    lines: List[str] = []
    for d, evs in _events_by_day(b.calendar_events):
        date = b.today + dt.timedelta(days=d)
        tag = "오늘" if d == 0 else f"D-{d}"
        lines.append(f"📅 {date.month}/{date.day}({_WEEKDAY_KO[date.weekday()]}) · {tag}")
        for e in evs:
            tstr = f"{e.time} " if getattr(e, "time", "") else ""
            note = f" — {e.note}" if getattr(e, "note", None) else ""
            lines.append(f"   {tstr}{_ev_icon(e)} {e.title}{note}")
    return lines


def _calendar_html(b: Briefing) -> str:
    if not b.calendar_events:
        msg = b.calendar_summary or "이번 주 예정된 주요 일정이 없습니다. (그래도 뇌동매매는 금물!)"
        return f"<div style='color:#666;font-size:14px;line-height:1.6;'>{_nl2br(msg)}</div>"
    trs = []
    for d, evs in _events_by_day(b.calendar_events):
        date = b.today + dt.timedelta(days=d)
        is_today = (d == 0)
        bg = "#2b6cb0" if is_today else "#dee2e6"
        fg = "#ffffff" if is_today else "#495057"
        sub = "오늘" if is_today else f"D-{d}"
        items = "".join(
            f"<div style='margin:3px 0;font-size:13px;color:#333;line-height:1.5;'>"
            + (f"<span style='color:#868e96;font-variant-numeric:tabular-nums;'>{_esc(e.time)}</span> "
               if getattr(e, 'time', '') else "")
            + f"{_ev_icon(e)} <b>{_esc(e.title)}</b>"
            + (f"<span style='color:#999;font-size:12px;'> — {_esc(e.note)}</span>"
               if getattr(e, 'note', None) else "")
            + "</div>"
            for e in evs
        )
        trs.append(
            "<tr>"
            "<td style='width:62px;vertical-align:top;padding:9px 6px;text-align:center;"
            "border-bottom:1px solid #f1f3f5;'>"
            f"<div style='background:{bg};color:{fg};font-size:13px;font-weight:700;"
            f"border-radius:6px;padding:4px 0;'>{date.month}/{date.day}</div>"
            f"<div style='font-size:11px;color:#868e96;margin-top:3px;'>"
            f"{_WEEKDAY_KO[date.weekday()]}·{sub}</div></td>"
            f"<td style='vertical-align:top;padding:9px 10px;border-bottom:1px solid #f1f3f5;'>{items}</td>"
            "</tr>"
        )
    return ("<table style='width:100%;border-collapse:collapse;background:#fff;"
            "border:1px solid #e9ecef;border-radius:8px;overflow:hidden;'>"
            + "".join(trs) + "</table>")


# ── 텍스트 본문 ───────────────────────────────────────────
def build_text(b: Briefing) -> str:
    L: List[str] = []
    L.append(f"📈 데일리 주식 브리핑")
    L.append(f"📅 {b.today.strftime('%Y-%m-%d (%a)')} · 데이터 기준일 {b.trade_day.strftime('%Y-%m-%d')}")
    L.append("")
    L.append(_GREETING)
    tldr = _tldr_lines(b)
    if tldr:
        L.append("")
        L.append("🐜 오늘의 개미 체크포인트")
        for t in tldr:
            L.append(f"  {t}")
    L.append("")
    L.append("─" * 20)
    L.append("")
    L.append("🌐 [1] 마켓 뷰 (지수 & 환율)")
    for line in _index_lines(b.index_quotes) or ["- 데이터 없음"]:
        L.append(f"- {line}")
    L.append(f"💡 {b.indices_comment}")
    mega_lines = _megacaps_text_lines(b.megacaps)
    if mega_lines:
        L.append("")
        L.append("🏢 핵심 대형주 (시총 상위 벨웨더 · 전일 등락)")
        L.extend(mega_lines)
    L.append("")
    L.append("🔥 [2] 오늘의 주도 섹터 & 국내외 핵심 종목")
    L.append("")
    L.append("🏢 오늘의 주도 섹터 TOP 3")
    if b.theme_groups:
        for g in b.theme_groups[:3]:
            L.append("")
            L.append(f"{g.emoji} {g.name} ({g.label})")
            for s in g.stocks:
                reason = f" · {s.reason}" if s.reason else ""
                L.append(f"- {s.name}: {_stock_price(s)} {_pct_text(s.change_pct)}{reason}")
            if g.summary:
                L.append(f"💬 이유 & 관전 포인트: {g.summary}")
        rest = b.theme_groups[3:]
        if rest:
            L.append("")
            L.append("💤 기타 섹터 한눈에 보기 (소폭 등락·혼조)")
            for g in rest:
                kr, us = _rep_stocks(g)
                reps = " / ".join(
                    f"{s.name} {_sign(s.change_pct)}{s.change_pct:.2f}%"
                    for s in (kr, us) if s)
                L.append(f"- [{g.name}] {reps}" if reps else f"- [{g.name}] ({g.label})")
    else:
        L.append("- 데이터 없음")
    if b.value_top or b.net_buy or b.net_sell or b.retail_net_buy:
        L.append("")
        L.append("💰 수급 & 거래대금 (돈의 흐름 — 개미 필독)")
        if b.value_top:
            L.append("· 💵 거래대금 상위: " + ", ".join(
                f"{s.name}({_eok(s.trade_value)}, {_sign(s.change_pct)}{s.change_pct:.1f}%)"
                for s in b.value_top))
        for label, rows in (b.net_buy or {}).items():
            if rows:
                L.append(f"· 🟢 {label} 순매수: " + ", ".join(
                    f"{s.name}{_amt(s.trade_value, '+')}" for s in rows))
        for label, rows in (b.net_sell or {}).items():
            if rows:
                L.append(f"· 🔴 {label} 순매도: " + ", ".join(
                    f"{s.name}{_amt(s.trade_value, '-')}" for s in rows))
        if b.retail_net_buy:
            L.append("· 🐜 개인 순매수: " + ", ".join(
                f"{s.name}{_amt(s.trade_value, '+')}" for s in b.retail_net_buy))
        if any((b.net_buy or {}).values()) and any((b.net_sell or {}).values()):
            L.append("  ※ 🟢 순매수(스마트머니가 담는 종목)와 🔴 순매도(던지는 종목)가 갈리는 곳은 특히 주의.")
    L.append("")
    L.append("📰 [3] 전일 주요 이슈 & 뉴스")
    if b.issues:
        for i in b.issues:
            L.append(f"- {i.title}\n  {i.url}")
    else:
        L.append("- 수집된 이슈 없음")
    L.append("")
    L.append("🚨 [4] 금일 & 이번 주 주요 일정")
    L.extend(_calendar_text(b))
    L.append("")
    L.append("※ 본 브리핑은 정보 제공용이며 투자 판단과 책임은 본인에게 있습니다.")
    return "\n".join(L)


# ── 카카오톡 '나에게 보내기' 요약 (200자 제한) ─────────────
def build_kakao_text(b: Briefing) -> str:
    """카톡 텍스트 템플릿용 초압축 요약 (최대 200자). 전문은 이메일 참고."""
    L: List[str] = [f"📈 데일리 브리핑 {b.today.strftime('%m/%d')}"]

    # 지수·환율 (핵심만: 코스피 / 나스닥 / 환율)
    def _find(name: str):
        return next((q for q in b.index_quotes if q.name == name), None)

    idx_bits = []
    for nm in ("코스피", "나스닥", "원/달러"):
        q = _find(nm)
        if q:
            if q.group == "환율":
                idx_bits.append(f"환율 {q.value:,.0f}원")
            else:
                idx_bits.append(f"{nm} {_sign(q.change_pct)}{q.change_pct:.1f}%")
    if idx_bits:
        L.append("🌐 " + " · ".join(idx_bits))

    # 트렌딩 테마 (있으면 최우선)
    if b.trending_themes:
        hot = b.trending_themes[0]
        L.append(f"🌟 트렌딩: {hot.name} ({hot.label})")

    # 빅 섹터 상위 2개
    if b.theme_groups:
        tops = [f"{g.name}({g.label})" for g in b.theme_groups[:2]]
        L.append("🔥 주도: " + ", ".join(tops))

    L.append("👉 아래 [메일 보기] 눌러 전문 확인!")
    text = "\n".join(L)
    return text if len(text) <= 200 else text[:197] + "..."


# ── HTML 본문 ─────────────────────────────────────────────
def _sector_color(label: str, avg: float) -> str:
    if label == "혼조세":
        return "#868e96"
    return "#e03131" if avg > 0 else ("#1c7ed6" if avg < 0 else "#868e96")


def build_html(b: Briefing) -> str:
    # 섹션 1 (그룹 라벨 + 종목당 한 줄, 등락률 색상)
    idx_html = _index_html_blocks(b.index_quotes)

    # 🏢 핵심 대형주 (시총 상위 벨웨더 — 마켓 뷰 바로 아래 고정 노출)
    mega_html = _megacaps_html(b.megacaps)

    # 섹션 2-A · 🏢 오늘의 주도 섹터 TOP 3 (그날 강한 섹터 상위 3개만 상세)
    big_blocks = []
    for g in b.theme_groups[:3]:
        col = _sector_color(g.label, g.avg_change)
        stock_lis = "".join(
            f"<li style='margin:4px 0;'>{_esc(s.name)}: {_stock_price(s)} {_pct_html(s.change_pct)}"
            + (f"<span style='color:#888;font-size:12px;'> · {_esc(s.reason)}</span>" if s.reason else "")
            + "</li>"
            for s in g.stocks
        )
        summary_html = (
            f"<div style='color:#444;font-size:13px;line-height:1.55;margin:8px 0 0;"
            f"background:#f1f5f9;border-left:3px solid #2b6cb0;padding:9px 11px;border-radius:6px;'>"
            f"💬 <b>이유 &amp; 관전 포인트</b><br>{_esc(g.summary)}</div>"
            if g.summary else ""
        )
        big_blocks.append(
            f"<div style='margin:16px 0;'>"
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:6px;'>"
            f"{g.emoji} {_esc(g.name)} <span style='color:{col};'>({_esc(g.label)})</span></div>"
            f"<ul style='padding-left:18px;margin:0;color:#333;line-height:1.5;font-size:14px;'>{stock_lis}</ul>"
            f"{summary_html}</div>"
        )
    # 💤 기타 섹터 한눈에 보기 (대표 국내 1 + 미국 1 종목)
    rest = b.theme_groups[3:]
    if rest:
        rows = ""
        for g in rest:
            kr, us = _rep_stocks(g)
            reps = " · ".join(
                f"{_esc(s.name)} <span style='color:{_pct_color(s.change_pct)};font-weight:600;'>"
                f"{_sign(s.change_pct)}{s.change_pct:.2f}%</span>"
                for s in (kr, us) if s)
            rows += (
                "<div style='margin:5px 0;font-size:13px;color:#555;'>"
                f"<b style='color:#495057;'>{g.emoji} {_esc(g.name)}</b>"
                f"<span style='color:#adb5bd;'> — </span>{reps or _esc(g.label)}</div>"
            )
        rest_html = (
            "<div style='margin-top:14px;padding:10px 12px;background:#f8f9fa;border-radius:8px;'>"
            "<div style='font-size:14px;font-weight:bold;color:#555;margin-bottom:4px;'>"
            "💤 기타 섹터 한눈에 보기 <span style='font-weight:normal;color:#999;font-size:12px;'>"
            "(소폭 등락·혼조)</span></div>" + rows + "</div>"
        )
    else:
        rest_html = ""
    big_html = ("".join(big_blocks) or "<div style='color:#888;'>데이터 없음</div>") + rest_html

    # 섹션 2-C · 💰 수급 & 거래대금 (개인 투자자 관점: 스마트머니 vs 개미)
    flows_parts = []
    if b.value_top:
        vlis = "".join(
            f"<li style='margin:3px 0;'>{_esc(s.name)}: <b>{_eok(s.trade_value)}</b> "
            f"{_pct_html(s.change_pct)}</li>"
            for s in b.value_top
        )
        flows_parts.append(
            "<div style='margin-top:10px;'><div style='font-size:13px;font-weight:bold;color:#555;'>"
            "💵 거래대금 상위 <span style='font-weight:normal;color:#888;font-size:12px;'>(돈이 몰린 종목)</span></div>"
            f"<ul style='padding-left:18px;margin:5px 0 0;color:#333;line-height:1.5;font-size:13px;'>{vlis}</ul></div>"
        )

    def _flow_row(icon: str, label: str, rows, sign: str) -> str:
        bits = " · ".join(
            _esc(s.name) + (f" <b>{sign}{_eok(s.trade_value)}</b>" if s.trade_value else "")
            for s in rows
        )
        return (f"<div style='margin-top:8px;font-size:13px;color:#333;'>"
                f"<span style='color:#555;font-weight:bold;'>{icon} {_esc(label)}</span> {bits}</div>")

    for label, rows in (b.net_buy or {}).items():
        if rows:
            flows_parts.append(_flow_row("🟢", f"{label} 순매수", rows, "+"))
    for label, rows in (b.net_sell or {}).items():
        if rows:
            flows_parts.append(_flow_row("🔴", f"{label} 순매도", rows, "-"))
    if b.retail_net_buy:
        flows_parts.append(_flow_row("🐜", "개인 순매수", b.retail_net_buy, "+"))
    caution_html = (
        "<div style='margin-top:10px;font-size:12px;color:#a33;line-height:1.5;'>"
        "※ 🟢 순매수(스마트머니가 담는 종목)와 🔴 순매도(던지는 종목)가 갈리는 곳은 특히 주의하세요.</div>"
        if (any((b.net_buy or {}).values()) and any((b.net_sell or {}).values())) else ""
    )
    flows_html = (
        "<div style='margin-top:16px;padding:10px 12px;background:#f1f5f9;border-radius:8px;'>"
        "<div style='font-size:14px;font-weight:bold;'>💰 수급 &amp; 거래대금 "
        "<span style='font-weight:normal;color:#888;font-size:12px;'>(돈의 흐름 — 개미 필독)</span></div>"
        + "".join(flows_parts) + caution_html + "</div>"
    ) if (b.value_top or b.net_buy or b.net_sell or b.retail_net_buy) else ""

    # 섹션 3
    if b.issues:
        issue_html = "".join(
            f"<li style='margin:8px 0;'>"
            f"<a href='{_esc(i.url)}' style='color:#1c6fd6;text-decoration:none;'>{_esc(i.title)} ↗</a></li>"
            for i in b.issues
        )
    else:
        issue_html = "<li>수집된 이슈 없음</li>"

    def h2(t: str) -> str:
        return f"<h2 style='font-size:17px;margin:24px 0 8px;'>{t}</h2>"

    # 🐜 오늘의 개미 체크포인트 (상단 요약 박스)
    tldr = _tldr_lines(b)
    tldr_html = (
        "<div style='margin:14px 0;padding:12px 14px;background:#fff4e6;"
        "border:1px solid #ffd8a8;border-radius:10px;'>"
        "<div style='font-size:14px;font-weight:bold;color:#c15400;margin-bottom:6px;'>"
        "🐜 오늘의 개미 체크포인트</div>"
        + "".join(
            f"<div style='font-size:13px;color:#333;margin:3px 0;'>{_esc(t)}</div>"
            for t in tldr
        )
        + "</div>"
    ) if tldr else ""

    return f"""\
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'Malgun Gothic',sans-serif;
            color:#1a1a1a;padding:16px;">
  <div style="border-bottom:2px solid #2b6cb0;padding-bottom:10px;">
    <h1 style="font-size:20px;margin:0;">📈 데일리 주식 브리핑</h1>
    <div style="color:#888;font-size:13px;margin-top:4px;">
      📅 {b.today.strftime('%Y-%m-%d (%a)')} · 데이터 기준일 {b.trade_day.strftime('%Y-%m-%d')}
    </div>
  </div>
  <div style="margin:14px 0;color:#444;font-size:14px;">{_esc(_GREETING)}</div>
  {tldr_html}

  {h2("🌐 [1] 마켓 뷰 <span style='font-size:13px;color:#888;'>(지수 &amp; 환율)</span>")}
  <div style="color:#333;line-height:1.5;font-size:14px;">{idx_html}</div>
  <div style="color:#555;font-size:13px;margin-top:8px;background:#f8f9fa;padding:8px 10px;border-radius:6px;">
    💡 {_nl2br(b.indices_comment)}</div>

  {(h2("🏢 핵심 대형주 <span style='font-size:13px;color:#888;'>(시총 상위 벨웨더 · 전일 등락)</span>")
    + "<div style='color:#888;font-size:13px;margin-bottom:4px;'>주도 섹터와 달리 매일 고정으로 추적하는 시총 최상위 종목입니다.</div>"
    + "<div style='color:#333;line-height:1.5;font-size:14px;'>" + mega_html + "</div>") if mega_html else ""}

  {h2("🔥 [2] 오늘의 주도 섹터 &amp; 주목 종목")}
  <div style="color:#888;font-size:13px;">그날 가장 강했던 주도 섹터 TOP 3와 그 외 섹터 요약입니다.</div>
  <div style="font-size:14px;font-weight:bold;color:#555;margin-top:12px;">🏢 오늘의 주도 섹터 <span style="font-weight:normal;color:#888;font-size:12px;">(강세 TOP 3)</span></div>
  {big_html}
  {flows_html}

  {h2("📰 [3] 전일 주요 이슈 &amp; 뉴스")}
  <ul style="padding-left:18px;margin:0;line-height:1.5;">{issue_html}</ul>

  {h2("🚨 [4] 금일 &amp; 이번 주 주요 일정")}
  {_calendar_html(b)}

  <div style="margin-top:26px;border-top:1px solid #ddd;padding-top:12px;color:#aaa;font-size:12px;line-height:1.5;">
    ※ 본 브리핑은 정보 제공용이며 투자 판단과 책임은 본인에게 있습니다.
  </div>
</div>"""
