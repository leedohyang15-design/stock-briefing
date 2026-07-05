"""오케스트레이터: 수집 → 요약 → 포맷 → 발송.

- 휴장일이면 즉시 종료 (데이터 없음)
- 각 collector 는 try/except 로 감싸 부분 실패 허용
  (한 섹션이 실패해도 나머지 섹션으로 브리핑을 발송)
"""
from __future__ import annotations

import sys

from .config import config
from .holidays_kr import (
    holiday_name,
    is_market_holiday,
    previous_trading_day,
    today_kst,
)
from . import formatter, kakao, sender, summarizer
from .collectors import calendar as cal_collector
from .collectors import indices, issues, themes, watchlist


def _safe(label, fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[main] '{label}' 수집 실패 → 해당 섹션 생략: {e}")
        return default


def run(force: bool = False) -> int:
    today = today_kst()

    if is_market_holiday(today) and not force:
        print(f"[main] 오늘({today})은 휴장일({holiday_name(today)}) — 브리핑을 발송하지 않습니다.")
        return 0

    trade_day = previous_trading_day(today)
    print(f"[main] 브리핑 생성 시작: 발송일={today}, 데이터 기준일={trade_day}, LLM={config.has_llm}")

    # ── 1. 수집 (부분 실패 허용) ──────────────────────────
    idx_quotes = _safe("지수/환율", indices.fetch_indices, [])
    theme_groups = _safe("주도 섹터·주목 종목", watchlist.fetch_theme_groups, [])
    _watch_names = {s.name for g in theme_groups for s in g.stocks}
    hot_themes = _safe(
        "기타 급등 테마", lambda: themes.fetch_hot_extra_themes(2, exclude_stocks=_watch_names), []
    )
    top_issues = _safe("주요 이슈", lambda: issues.fetch_top_issues(3), [])
    cal_events = _safe("일정/리스크", lambda: cal_collector.fetch_calendar(today), [])

    # ── 2. 요약 (LLM 또는 폴백) ───────────────────────────
    indices_comment = summarizer.summarize_indices_comment(indices.to_plain_lines(idx_quotes))
    _safe("테마 요약", lambda: summarizer.annotate_theme_summaries(theme_groups), None)
    _safe("종목별 등락 원인", lambda: summarizer.annotate_stock_reasons(theme_groups), None)
    _safe("급등 테마 원인", lambda: summarizer.annotate_hot_theme_causes(hot_themes), None)
    calendar_summary = summarizer.summarize_calendar(cal_collector.to_plain_lines(cal_events))

    # ── 3. 포맷 ───────────────────────────────────────────
    briefing = formatter.Briefing(
        trade_day=trade_day,
        today=today,
        index_quotes=idx_quotes,
        indices_comment=indices_comment,
        theme_groups=theme_groups,
        hot_themes=hot_themes,
        issues=top_issues,
        calendar_summary=calendar_summary,
    )
    subject = formatter.build_subject(briefing)
    text_body = formatter.build_text(briefing)
    html_body = formatter.build_html(briefing)

    # ── 4. 발송 (이메일 + 카카오 병행, 서로 막지 않음) ─────
    if not config.has_email and not config.kakao_enabled:
        raise RuntimeError(
            "발송 채널이 하나도 설정되지 않았습니다. "
            "이메일(SMTP_*) 또는 카카오(KAKAO_*) 중 최소 하나를 설정하세요."
        )

    if config.has_email:
        _safe("이메일 발송", lambda: sender.send_email(subject, text_body, html_body), None)
    else:
        print("[main] 이메일 미설정 — 이메일 발송 건너뜀.")

    if config.kakao_enabled:
        kakao_text = formatter.build_kakao_text(briefing)
        # 메시지 탭 시 Gmail 받은편지함으로 이동 + [메일 보기]/[뉴스 보기] 버튼
        gmail_url = "https://mail.google.com/mail/u/0/#inbox"
        buttons = [{"title": "메일 보기", "url": gmail_url}]
        if top_issues:
            buttons.append({"title": "뉴스 보기", "url": top_issues[0].url})
        _safe(
            "카카오 발송",
            lambda: kakao.send_kakao_memo(kakao_text, link_url=gmail_url, buttons=buttons),
            None,
        )

    print("[main] 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(run(force="--force" in sys.argv))
