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
    theme_groups: list              # 섹션2 🏢 빅 섹터(국내+미국 큐레이션) (ThemeGroup)
    trending_themes: list = field(default_factory=list)  # 섹션2 ⚡ 트렌딩 스몰 섹션 (ThemeGroup)
    small_movers: list = field(default_factory=list)     # 섹션2 💡 기타 강세 종목 (Stock)
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


def _arrow(v: float) -> str:
    """등락 방향 이모지 — 한눈에 상승/하락 구분."""
    return "📈" if v > 0 else ("📉" if v < 0 else "➖")


def _stock_price(s) -> str:
    """종목 가격 표기: 국내(KRW)는 '원', 해외(USD)는 '$'."""
    if getattr(s, "currency", "KRW") == "USD":
        return f"${s.close:,.2f}"
    return f"{s.close:,.0f}원"


def _flag(s) -> str:
    """종목 국적 국기: 국내=🇰🇷, 미국=🇺🇸."""
    return "🇺🇸" if getattr(s, "currency", "KRW") == "USD" else "🇰🇷"


def _pct_html(v: float) -> str:
    """📈/📉 이모지 + 색상 등락률 (HTML)."""
    return (f"{_arrow(v)} <span style='color:{_pct_color(v)};font-weight:600;'>"
            f"{_sign(v)}{v:.2f}%</span>")


def _pct_text(v: float) -> str:
    """📈/📉 이모지 + 등락률 (텍스트)."""
    return f"{_arrow(v)} {_sign(v)}{v:.2f}%"


def _fmt_index(q) -> str:
    unit = "원" if q.group == "환율" else ""
    return f"{q.name} {q.value:,.2f}{unit} ({_arrow(q.change_pct)} {_sign(q.change_pct)}{q.change_pct:.2f}%)"


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
        f"{_arrow(q.change_pct)} <span style='color:{col};font-weight:700;'>"
        f"{_sign(q.change_pct)}{q.change_pct:.2f}%</span>"
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
    L.append("🔥 [2] 오늘의 주도 섹터 & 국내외 핵심 종목")
    L.append("")
    L.append("🏢 시장 주도 빅 섹션 (국내+미국 핵심주)")
    if b.theme_groups:
        for g in b.theme_groups:
            L.append("")
            L.append(f"{g.emoji} {g.name} ({g.label})")
            for s in g.stocks:
                reason = f" · {s.reason}" if s.reason else ""
                L.append(f"- {_flag(s)} {s.name}: {_stock_price(s)} {_pct_text(s.change_pct)}{reason}")
            if g.summary:
                L.append(f"💬 이유 & 관전 포인트: {g.summary}")
    else:
        L.append("- 데이터 없음")
    if b.trending_themes:
        L.append("")
        L.append("⚡ 당일 트렌딩 스몰 섹션 (단기 이슈/테마)")
        for g in b.trending_themes:
            members = ", ".join(f"{s.name} {_pct_text(s.change_pct)}" for s in g.stocks)
            L.append(f"{g.emoji} {g.name} ({g.label}) — {members}")
            if g.summary:
                L.append(f"  💬 {g.summary}")
    if b.small_movers:
        L.append("")
        L.append("💡 기타 당일 강세 종목 (단기 급등·소형주)")
        for s in b.small_movers:
            reason = f" · {s.reason}" if s.reason else ""
            L.append(f"- {_flag(s)} {s.name}: {_stock_price(s)} {_pct_text(s.change_pct)}{reason}")
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

    # 섹션 2-A · 🏢 시장 주도 빅 섹션 (국내+미국 큐레이션)
    big_blocks = []
    for g in b.theme_groups:
        col = _sector_color(g.label, g.avg_change)
        stock_lis = "".join(
            f"<li style='margin:4px 0;'>{_flag(s)} {_esc(s.name)}: {_stock_price(s)} {_pct_html(s.change_pct)}"
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
    big_html = "".join(big_blocks) or "<div style='color:#888;'>데이터 없음</div>"

    # 섹션 2-B · ⚡ 당일 트렌딩 스몰 섹션 (실시간 네이버 핫테마)
    trend_blocks = []
    for g in b.trending_themes:
        members = " · ".join(f"{_esc(s.name)} {_pct_html(s.change_pct)}" for s in g.stocks)
        cause = (f"<div style='color:#8a6d00;font-size:12px;margin-top:3px;'>💬 {_esc(g.summary)}</div>"
                 if g.summary else "")
        trend_blocks.append(
            f"<div style='margin:10px 0;padding:9px 11px;background:#fff9e6;border:1px solid #ffe08a;border-radius:8px;'>"
            f"<div style='font-size:14px;font-weight:bold;'>{g.emoji} {_esc(g.name)} "
            f"<span style='color:#e03131;'>({_esc(g.label)})</span></div>"
            f"<div style='color:#333;font-size:13px;margin-top:3px;'>{members}</div>{cause}</div>"
        )
    trend_html = (
        "<div style='margin-top:18px;'><div style='font-size:14px;font-weight:bold;color:#555;'>"
        "⚡ 당일 트렌딩 스몰 섹션 <span style='font-weight:normal;color:#888;font-size:12px;'>"
        "(실시간 급등 테마)</span></div>" + "".join(trend_blocks) + "</div>"
    ) if b.trending_themes else ""

    # 섹션 2-C · 💡 기타 당일 강세 종목 (상한가성 소형주)
    if b.small_movers:
        mover_lis = "".join(
            f"<li style='margin:3px 0;'>{_flag(s)} {_esc(s.name)}: {_stock_price(s)} {_pct_html(s.change_pct)}"
            + (f"<span style='color:#888;font-size:12px;'> · {_esc(s.reason)}</span>" if s.reason else "")
            + "</li>"
            for s in b.small_movers
        )
        movers_html = (
            "<div style='margin-top:16px;'><div style='font-size:14px;font-weight:bold;color:#555;'>"
            "💡 기타 당일 강세 종목 <span style='font-weight:normal;color:#888;font-size:12px;'>"
            "(단기 급등·소형주)</span></div>"
            f"<ul style='padding-left:18px;margin:6px 0 0;color:#333;line-height:1.5;font-size:13px;'>{mover_lis}</ul></div>"
        )
    else:
        movers_html = ""

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

  {h2("🔥 [2] 오늘의 주도 섹터 &amp; 국내외 핵심 종목")}
  <div style="color:#888;font-size:13px;">시장을 움직이는 거대한 축(빅 섹션)과 당일 핫했던 틈새 테마(스몰 섹션)의 국내외 흐름입니다.</div>
  <div style="font-size:14px;font-weight:bold;color:#555;margin-top:12px;">🏢 시장 주도 빅 섹션 <span style="font-weight:normal;color:#888;font-size:12px;">(국내+미국 핵심주)</span></div>
  {big_html}
  {trend_html}
  {movers_html}

  {h2("📰 [3] 전일 주요 이슈 &amp; 뉴스")}
  <ul style="padding-left:18px;margin:0;line-height:1.5;">{issue_html}</ul>

  {h2("🚨 [4] 오늘의 주요 일정 &amp; 리스크")}
  <div style="color:#333;line-height:1.6;">{_nl2br(b.calendar_summary)}</div>

  <div style="margin-top:26px;border-top:1px solid #ddd;padding-top:12px;color:#aaa;font-size:12px;line-height:1.5;">
    ※ 본 브리핑은 정보 제공용이며 투자 판단과 책임은 본인에게 있습니다.
  </div>
</div>"""
