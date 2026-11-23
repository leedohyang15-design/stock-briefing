"""시세 데이터 저장: 일봉(ATR·평균거래량), 분봉(차트·타임머신·백테스트).

한국 시장 검증용 데이터는 무료로 구하기 어려워서, 매일 관심종목 분봉을 직접 쌓는다.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List

from .journal import Journal
from .models import Bar, now_kst


def ensure_daily(kis, journal: Journal, code: str, days: int = 40) -> List[Bar]:
    """일봉을 받아 저장 (오늘 이미 받았으면 DB 사용). 오늘 일봉은 제외하고 반환."""
    today = now_kst().strftime("%Y%m%d")
    have = journal.daily_bars(code, before=today, n=days)
    yesterday_ok = have and have[-1].date >= (now_kst() - dt.timedelta(days=4)).strftime("%Y%m%d")
    if len(have) >= min(days, 20) and yesterday_ok:
        return have
    try:
        bars = kis.daily_bars(code, days + 1)
        journal.save_daily_bars(code, bars)
    except Exception as e:  # noqa: BLE001
        print(f"[datalog] 일봉 실패 {code}: {e}")
    return journal.daily_bars(code, before=today, n=days)


def refresh_today(kis, journal: Journal, code: str, full: bool = False) -> List[Bar]:
    """오늘 분봉 갱신. full=False 면 최근 30개만(1회 호출)."""
    try:
        bars = kis.minute_bars_today(code) if full else kis.minute_bars_recent(code)
        journal.save_bars(code, bars)
    except Exception as e:  # noqa: BLE001
        print(f"[datalog] 분봉 실패 {code}: {e}")
    return journal.bars(code, now_kst().strftime("%Y%m%d"))


def ensure_history(kis, journal: Journal, code: str, days: int = 59, budget_calls: int = 300) -> Dict[str, List[Bar]]:
    """과거 분봉 확보 (타임머신용). 일봉 날짜 기준으로 빠진 날만 받는다."""
    today = now_kst().strftime("%Y%m%d")
    dates = [b.date for b in journal.daily_bars(code, before=today, n=days)]
    have = set(journal.bar_dates(code))
    calls = 0
    for d in reversed(dates):
        if d in have:
            continue
        if calls >= budget_calls:
            break
        try:
            bars = kis.minute_bars_past(code, d)
            calls += 4
            if bars:
                journal.save_bars(code, bars)
            else:
                break  # API 가 과거 분봉을 주지 않으면 더 시도하지 않음
        except Exception as e:  # noqa: BLE001
            print(f"[datalog] 과거 분봉 실패 {code} {d}: {e}")
            break
    return {d: journal.bars(code, d) for d in dates if d in set(journal.bar_dates(code))}


def ensure_open_volumes(kis, journal: Journal, code: str, minutes: int, days: int = 14) -> None:
    """실측 상대거래량용: 최근 days 거래일의 09:00~시가범위 끝 분봉을 받아 저장 (날짜당 1회 호출, 캐시)."""
    from . import strategy as st
    today = now_kst().strftime("%Y%m%d")
    until = st.hhmm_add("0900", minutes) + "00"
    for d in [b.date for b in journal.daily_bars(code, before=today, n=days)]:
        if journal.bars(code, d)[:1] and journal.bars(code, d)[0].time <= "0900":
            continue
        try:
            bars = kis.minute_bars_past(code, d, until)
        except Exception as e:  # noqa: BLE001
            print(f"[datalog] 시가 분봉 실패 {code} {d}: {e}")
            return
        if not bars:
            return  # API 가 과거 분봉을 주지 않음
        journal.save_bars(code, bars)


def open_avg_from_db(journal: Journal, code: str, before: str, minutes: int, days: int = 14):
    """(과거 같은 시간대 평균 거래량, 일수)."""
    from . import strategy as st
    dates = [d for d in journal.bar_dates(code) if d < before][-days:]
    return st.open_volume_avg([journal.bars(code, d) for d in dates], minutes)


def history_from_db(journal: Journal, code: str, before: str, days: int = 59) -> Dict[str, List[Bar]]:
    dates = [d for d in journal.bar_dates(code) if d < before][-days:]
    return {d: journal.bars(code, d) for d in dates}


def record_eod(kis, journal: Journal, codes: Iterable[str]) -> None:
    for c in set(codes):
        refresh_today(kis, journal, c, full=True)
