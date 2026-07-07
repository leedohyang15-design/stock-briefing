"""[섹션 3] 오늘의 주요 일정 & 리스크 수집.

- 매크로 경제 일정: config/macro_calendar.yaml 에서 오늘 날짜에 해당하는 항목
  (CPI/FOMC/옵션만기 등). 무료·무키 정책상 안정적 크롤링 소스가 없어
  유지보수 가능한 설정 파일로 관리한다.
- 락업(보호예수) 해제: 네이버 금융에서 best-effort 로 시도하며, 실패 시 빈 목록.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import List, Optional

import yaml

from ..holidays_kr import today_kst

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "macro_calendar.yaml",
)


@dataclass
class CalendarEvent:
    title: str
    category: str  # "매크로" | "락업해제" | "기타"
    note: Optional[str] = None
    days_until: int = 0  # 오늘로부터 며칠 뒤 (0=오늘)

    @property
    def dlabel(self) -> str:
        return "오늘" if self.days_until == 0 else f"D-{self.days_until}"


def _match_recurring(rule: dict, day: dt.date) -> bool:
    """반복 규칙(recurring)이 오늘 날짜에 해당하는지 판정.

    지원 형태:
      - {month: 4, day: 10}          # 매년 4/10
      - {day: 15}                    # 매월 15일
      - {weekday: 4}                 # 매주 금요일 (0=월 ... 6=일)
      - {month: 3, week: 2, weekday: 4}  # 3월 둘째 주 금요일 (옵션만기 등)
    """
    if "month" in rule and rule["month"] != day.month:
        return False
    if "day" in rule and rule["day"] != day.day:
        return False
    if "weekday" in rule and rule["weekday"] != day.weekday():
        return False
    if "week" in rule:
        # 해당 월에서 몇 번째 요일인지 계산
        week_of_month = (day.day - 1) // 7 + 1
        if rule["week"] != week_of_month:
            return False
    return True


_LOOKAHEAD_DAYS = 7  # 오늘 포함 향후 며칠까지 미리 보여줄지


def fetch_macro_events(day: Optional[dt.date] = None) -> List[CalendarEvent]:
    """오늘부터 향후 _LOOKAHEAD_DAYS 일 내의 매크로 일정을 D-n 과 함께 반환."""
    day = day or today_kst()
    events: List[CalendarEvent] = []
    if not os.path.exists(_CONFIG_PATH):
        print(f"[calendar] macro_calendar.yaml 없음: {_CONFIG_PATH}")
        return events
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[calendar] yaml 파싱 실패: {e}")
        return events

    window = [day + dt.timedelta(days=n) for n in range(_LOOKAHEAD_DAYS + 1)]

    # 1) 고정일 이벤트: {date: 2026-07-10, title: ...}
    for item in data.get("fixed", []) or []:
        try:
            d = item["date"]
            if isinstance(d, str):
                d = dt.date.fromisoformat(d)
            if d in window:
                events.append(CalendarEvent(
                    title=item["title"], category="매크로",
                    note=item.get("note"), days_until=(d - day).days))
        except Exception as e:  # noqa: BLE001
            print(f"[calendar] fixed 항목 처리 실패: {e}")

    # 2) 반복 이벤트: {title: ..., recurring: {...}} — 창(window) 내 첫 매칭일만
    for item in data.get("recurring", []) or []:
        try:
            rule = item.get("recurring", {})
            for d in window:
                if _match_recurring(rule, d):
                    events.append(CalendarEvent(
                        title=item["title"], category="매크로",
                        note=item.get("note"), days_until=(d - day).days))
                    break  # 창 내 가장 가까운 1회만
        except Exception as e:  # noqa: BLE001
            print(f"[calendar] recurring 항목 처리 실패: {e}")

    events.sort(key=lambda e: e.days_until)  # 가까운 일정 먼저
    return events


def fetch_lockup_releases(day: Optional[dt.date] = None) -> List[CalendarEvent]:
    """락업(보호예수) 해제 일정 — best effort.

    안정적인 무료·무키 소스가 없어 현재는 자리표시(placeholder)로 두고
    빈 목록을 반환한다. 유료 API/전용 소스 확보 시 이 함수만 교체하면 된다.
    """
    # TODO: Seibro(증권정보포털) 또는 유료 API 연동 지점.
    return []


def fetch_calendar(day: Optional[dt.date] = None) -> List[CalendarEvent]:
    """섹션 3 통합 수집: 매크로 일정 + 락업 해제."""
    day = day or today_kst()
    events = fetch_macro_events(day)
    events.extend(fetch_lockup_releases(day))
    return events


def to_plain_lines(events: List[CalendarEvent]) -> List[str]:
    lines = []
    for e in events:
        line = f"[{e.dlabel}] {e.title}"
        if e.note:
            line += f" — {e.note}"
        lines.append(line)
    return lines


if __name__ == "__main__":
    todays = fetch_calendar()
    if todays:
        for line in to_plain_lines(todays):
            print(line)
    else:
        print("오늘 등록된 주요 일정 없음")
