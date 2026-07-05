"""한국 증시(KRX) 휴장일 판정.

주말 + 공휴일(`holidays` 라이브러리) + 증시 특유 휴장일(연말 폐장일 등)을
종합해 해당 날짜에 브리핑을 보낼지 여부를 결정한다.

브리핑은 "직전 거래일" 데이터를 아침에 전달하므로, 이 함수는
'오늘이 거래일인가?'를 기준으로 발송 여부를 판단한다.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import holidays as _holidays

# 매년 12월 31일은 증시 폐장일(공휴일은 아니지만 휴장).
# holidays 라이브러리가 잡지 못하는 KRX 특유 휴장일을 여기서 보완한다.
# (월, 일) 형태로 매년 반복되는 휴장일
_KRX_EXTRA_MMDD = {
    (12, 31),  # 연말 폐장일
}

# 임시 공휴일 등 연도별 일회성 휴장일(선거일, 대체휴일 특례 등)이 있으면 추가.
# 예: dt.date(2025, 6, 3): "대통령 선거일"
_KRX_EXTRA_DATES: dict[dt.date, str] = {}


def _kr_holidays(year: int):
    return _holidays.SouthKorea(years=year)


def is_market_holiday(day: Optional[dt.date] = None) -> bool:
    """`day`(기본: 오늘, KST 기준 날짜)가 KRX 휴장일이면 True."""
    if day is None:
        day = today_kst()

    # 주말
    if day.weekday() >= 5:  # 5=토, 6=일
        return True

    # 법정 공휴일
    if day in _kr_holidays(day.year):
        return True

    # KRX 특유 반복 휴장일
    if (day.month, day.day) in _KRX_EXTRA_MMDD:
        return True

    # 연도별 일회성 휴장일
    if day in _KRX_EXTRA_DATES:
        return True

    return False


def today_kst() -> dt.date:
    """서버 타임존과 무관하게 KST 기준 '오늘' 날짜 반환."""
    kst = dt.timezone(dt.timedelta(hours=9))
    return dt.datetime.now(tz=kst).date()


def holiday_name(day: dt.date) -> Optional[str]:
    """휴장 사유를 사람이 읽을 수 있는 문자열로 반환 (없으면 None)."""
    if day.weekday() == 5:
        return "토요일"
    if day.weekday() == 6:
        return "일요일"
    name = _kr_holidays(day.year).get(day)
    if name:
        return name
    if (day.month, day.day) in _KRX_EXTRA_MMDD:
        return "증시 폐장일"
    if day in _KRX_EXTRA_DATES:
        return _KRX_EXTRA_DATES[day]
    return None


def previous_trading_day(day: Optional[dt.date] = None) -> dt.date:
    """`day`(기본: 오늘) 기준 직전 거래일 반환."""
    if day is None:
        day = today_kst()
    d = day - dt.timedelta(days=1)
    while is_market_holiday(d):
        d -= dt.timedelta(days=1)
    return d


if __name__ == "__main__":
    # 셀프 스모크 테스트
    t = today_kst()
    print(f"오늘(KST): {t} / 휴장? {is_market_holiday(t)} ({holiday_name(t)})")
    print(f"직전 거래일: {previous_trading_day(t)}")
    # 알려진 휴장일 검증
    samples = [
        dt.date(2026, 1, 1),   # 신정
        dt.date(2025, 12, 31),  # 폐장일
        dt.date(2026, 7, 4),   # 토요일
    ]
    for s in samples:
        print(f"{s}: 휴장={is_market_holiday(s)} ({holiday_name(s)})")
