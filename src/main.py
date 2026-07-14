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
from . import formatter, sender, summarizer
from .collectors import calendar as cal_collector
from .collectors import flows, hot_sectors, indices, issues, watchlist


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
    big_sectors = _safe("빅 섹터(국내+미국 큐레이션)", watchlist.fetch_theme_groups, [])
    # 트렌딩 테마만 사용 (기타 강세 소형주 섹션은 제거됨)
    trending_themes, _ = _safe(
        "트렌딩 테마", lambda: hot_sectors.fetch_trending(3, 2, 6), ([], []))
    top_issues = _safe("주요 이슈", lambda: issues.fetch_top_issues(3), [])
    cal_events = _safe("일정/리스크", lambda: cal_collector.fetch_calendar(today), [])
    value_top = _safe("거래대금 상위", lambda: flows.fetch_trading_value_top(trade_day, 5), [])
    # 외국인·기관 순매매(순매수·순매도) 상위 (네이버 frgn)
    flow_data = _safe("투자자 순매매(외국인·기관)",
                      lambda: flows.fetch_investor_flows(trade_day, 3), {})
    net_buy = flow_data.get("buy", {})
    net_sell = flow_data.get("sell", {})
    retail_net_buy = flow_data.get("retail_buy", [])

    # ── 2. 요약 (LLM 또는 폴백) ───────────────────────────
    indices_comment = summarizer.summarize_indices_comment(indices.to_plain_lines(idx_quotes))
    _safe("빅 섹터 원인분석", lambda: summarizer.annotate_theme_summaries(big_sectors, flavor="big"), None)
    _safe("트렌딩 원인분석", lambda: summarizer.annotate_theme_summaries(trending_themes, flavor="trending"), None)
    # 빅 섹터 종목의 개별 등락 원인을 1회 호출로 채움
    _safe("종목별 등락 원인", lambda: summarizer.annotate_stock_reasons(big_sectors), None)
    calendar_summary = summarizer.summarize_calendar(cal_collector.to_plain_lines(cal_events))

    # ── 3. 포맷 ───────────────────────────────────────────
    briefing = formatter.Briefing(
        trade_day=trade_day,
        today=today,
        index_quotes=idx_quotes,
        indices_comment=indices_comment,
        theme_groups=big_sectors,
        trending_themes=trending_themes,
        issues=top_issues,
        calendar_summary=calendar_summary,
        value_top=value_top,
        net_buy=net_buy,
        net_sell=net_sell,
        retail_net_buy=retail_net_buy,
    )
    subject = formatter.build_subject(briefing)
    text_body = formatter.build_text(briefing)
    html_body = formatter.build_html(briefing)

    # ── 4. 발송 (이메일) ──────────────────────────────────
    # 카카오톡 '나에게 보내기'는 푸시 알림이 안 떠 확인이 어려워 비활성화함.
    # (kakao.py 모듈은 남겨둠 — 다시 쓰려면 여기서 send_kakao_memo 를 호출)
    if not config.has_email:
        raise RuntimeError(
            "이메일 발송 설정이 없습니다. SMTP_USER/SMTP_PASSWORD/MAIL_TO 를 확인하세요."
        )
    sender.send_email(subject, text_body, html_body)

    print("[main] 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(run(force="--force" in sys.argv))
