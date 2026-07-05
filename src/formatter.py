"""수집·요약된 데이터를 이메일 본문(HTML + 텍스트)으로 조립.

섹션 구성:
  인사말
  🌐 [1] 마켓 뷰 (지수 & 환율)
  🔥 [2] 오늘의 주도 섹터 & 주목 종목  (테마별 종목 + 흐름 요약)
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
    theme_groups: list              # 섹션 2 (ThemeGroup: .name/.emoji/.stocks/.label/.summary)
    hot_themes: list = field(default_factory=list)  # 섹션 2 상단 🌟 기타 급등 테마 (HotTheme)
    issues: list = field(default_factory=list)   # 섹션 3 (Issue: .title/.url)
    calendar_summary: str = ""      # 섹션 4


def _esc(t: str) -> str:
    return html.escape(t)


def _nl2br(t: str) -> str:
    return html.escape(t).replace("\n", "<br>")


def build_subject(b: Briefing) -> str:
    return f"📈 데일리 주식 브리핑 ({b.today.strftime('%m/%d')} 아침)"


def _sign(v: float) -> str:
    return "+" if v > 0 else ""


def _fmt_index(q) -> str:
    unit = "원" if q.group == "환율" else ""
    return f"{q.name} {q.value:,.2f}{unit} ({q.arrow} {_sign(q.change_pct)}{q.change_pct:.2f}%)"


def _index_lines(quotes) -> List[str]:
    """그룹(국내/해외/환율)별로 한 줄씩 묶어 반환 (텍스트용)."""
    order = ["국내", "해외", "환율"]
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
    unit = "원" if q.group == "환율" else ""
    col = _pct_color(q.change_pct)
    return (
        f"{_esc(q.name)} {q.value:,.2f}{unit} "
        f"<span style='color:{col};font-weight:600;'>"
        f"({q.arrow} {_sign(q.change_pct)}{q.change_pct:.2f}%)</span>"
    )


def _index_html_blocks(quotes) -> str:
    """그룹(국내/해외/환율) 라벨 + 종목당 한 줄로 렌더 (모바일 줄바꿈 방지)."""
    order = ["국내", "해외", "환율"]
    out = []
    for grp in order:
        qs = [q for q in quotes if q.group == grp]
        if not qs:
            continue
        rows = "".join(
            f"<div style='margin:2px 0;white-space:nowrap;'>{_fmt_index_html(q)}</div>"
            for q in qs
        )
        out.append(
            f"<div style='margin:10px 0 4px;'>"
            f"<span style='display:inline-block;font-size:11px;font-weight:600;color:#fff;"
            f"background:#868e96;border-radius:4px;padding:1px 8px;margin-bottom:4px;'>{grp}</span>"
            f"{rows}</div>"
        )
    return "".join(out) or "<div>데이터 없음</div>"


# ── 텍스트 본문 ───────────────────────────────────────────
def build_text(b: Briefing) -> str:
    L: List[str] = []
    L.append(f"📈 데일리 주식 브리핑")
    L.append(f"📅 {b.today.strftime('%Y-%m-%d (%a)')} · 데이터 기준일 {b.trade_day.strftime('%Y-%m-%d')}")
    L.append("")
    L.append(_GREETING)
    L.append("")
    L.append("─" * 20)
    L.append("")
    L.append("🌐 [1] 마켓 뷰 (지수 & 환율)")
    for line in _index_lines(b.index_quotes) or ["- 데이터 없음"]:
        L.append(f"- {line}")
    L.append(f"💡 {b.indices_comment}")
    L.append("")
    L.append("🔥 [2] 오늘의 주도 섹터 & 주목 종목")
    for t in b.hot_themes:
        lead = f" (주도주: {', '.join(t.leaders)})" if t.leaders else ""
        L.append("")
        L.append(f"🌟 [오늘의 급등 테마] {t.name} (+{t.change_pct:.2f}%){lead}")
        if t.cause:
            L.append(f"💬 {t.cause}")
    if b.theme_groups:
        for g in b.theme_groups:
            L.append("")
            L.append(f"{g.emoji} {g.name} 섹터 ({g.label})")
            for s in g.stocks:
                reason = f" · {s.reason}" if s.reason else ""
                L.append(f"- {s.name}: {s.close:,}원 ({_sign(s.change_pct)}{s.change_pct:.2f}%){reason}")
            if g.summary:
                L.append(f"💬 요약: {g.summary}")
    else:
        L.append("- 데이터 없음")
    L.append("")
    L.append("📰 [3] 전일 주요 이슈 & 뉴스")
    if b.issues:
        for i in b.issues:
            L.append(f"- {i.title}\n  {i.url}")
    else:
        L.append("- 수집된 이슈 없음")
    L.append("")
    L.append("🚨 [4] 오늘의 주요 일정 & 리스크")
    L.append(b.calendar_summary)
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

    # 급등 테마 (있으면 최우선)
    if b.hot_themes:
        hot = b.hot_themes[0]
        L.append(f"🌟 급등테마: {hot.name} +{hot.change_pct:.1f}%")

    # 주도 섹터 상위 2개
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

    # 섹션 2
    sector_blocks = []
    for g in b.theme_groups:
        col = _sector_color(g.label, g.avg_change)
        stock_lis = "".join(
            f"<li style='margin:4px 0;'>{_esc(s.name)}: {s.close:,}원 "
            f"<span style='color:{'#e03131' if s.change_pct>0 else ('#1c7ed6' if s.change_pct<0 else '#868e96')};'>"
            f"({_sign(s.change_pct)}{s.change_pct:.2f}%)</span>"
            + (f"<span style='color:#888;font-size:12px;'> · {_esc(s.reason)}</span>" if s.reason else "")
            + "</li>"
            for s in g.stocks
        )
        summary_html = (
            f"<div style='color:#555;font-size:13px;margin:6px 0 0;background:#f8f9fa;"
            f"padding:8px 10px;border-radius:6px;'>💬 <b>요약</b> · {_esc(g.summary)}</div>"
            if g.summary else ""
        )
        sector_blocks.append(
            f"<div style='margin:16px 0;'>"
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:6px;'>"
            f"{g.emoji} {_esc(g.name)} 섹터 <span style='color:{col};'>({_esc(g.label)})</span></div>"
            f"<ul style='padding-left:18px;margin:0;color:#333;line-height:1.5;font-size:14px;'>{stock_lis}</ul>"
            f"{summary_html}</div>"
        )
    sector_html = "".join(sector_blocks) or "<div>데이터 없음</div>"

    # 섹션 2 상단: 🌟 기타 급등 테마 (있을 때만)
    hot_blocks = []
    for t in b.hot_themes:
        lead = f" <span style='color:#999;font-size:12px;'>주도주: {_esc(', '.join(t.leaders))}</span>" if t.leaders else ""
        cause = (
            f"<div style='color:#8a6d00;font-size:13px;margin-top:4px;'>💬 {_esc(t.cause)}</div>"
            if t.cause else ""
        )
        hot_blocks.append(
            f"<div style='margin:12px 0;padding:10px 12px;background:#fff9e6;"
            f"border:1px solid #ffe08a;border-radius:8px;'>"
            f"<div style='font-size:14px;font-weight:bold;'>🌟 오늘의 급등 테마 · "
            f"{_esc(t.name)} <span style='color:#e03131;'>(+{t.change_pct:.2f}%)</span>{lead}</div>"
            f"{cause}</div>"
        )
    hot_html = "".join(hot_blocks)

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

  {h2("🌐 [1] 마켓 뷰 <span style='font-size:13px;color:#888;'>(지수 &amp; 환율)</span>")}
  <div style="color:#333;line-height:1.5;font-size:14px;">{idx_html}</div>
  <div style="color:#555;font-size:13px;margin-top:8px;background:#f8f9fa;padding:8px 10px;border-radius:6px;">
    💡 {_nl2br(b.indices_comment)}</div>

  {h2("🔥 [2] 오늘의 주도 섹터 &amp; 주목 종목")}
  <div style="color:#888;font-size:13px;">시장을 이끈 핵심 테마와 주요 종목의 흐름입니다. (그날 강한 섹터 순)</div>
  {hot_html}
  {sector_html}

  {h2("📰 [3] 전일 주요 이슈 &amp; 뉴스")}
  <ul style="padding-left:18px;margin:0;line-height:1.5;">{issue_html}</ul>

  {h2("🚨 [4] 오늘의 주요 일정 &amp; 리스크")}
  <div style="color:#333;line-height:1.6;">{_nl2br(b.calendar_summary)}</div>

  <div style="margin-top:26px;border-top:1px solid #ddd;padding-top:12px;color:#aaa;font-size:12px;line-height:1.5;">
    ※ 본 브리핑은 정보 제공용이며 투자 판단과 책임은 본인에게 있습니다.
  </div>
</div>"""
