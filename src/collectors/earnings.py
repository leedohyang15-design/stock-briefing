"""[섹션 4 보강] 워치리스트 종목의 임박한 실적발표 예정일 (yfinance).

무료·무키 소스(yfinance)로 워치리스트 각 종목의 '다음 실적발표(예정)일'을 조회해,
오늘부터 lookahead 일 이내면 [4] 일정 섹션에 이벤트로 추가한다.
(국내 종목은 yfinance 에 예정일이 없을 때가 많아 조용히 건너뛴다 — 주로 미장 종목이 잡힘.)
"""
from __future__ import annotations

import datetime as dt
import os
from typing import List, Optional, Tuple

import yaml

from .. import _ssl_bootstrap  # noqa: F401  (yfinance import 전에 SSL 경로 보정)
import yfinance as yf

from .calendar import CalendarEvent
from ..holidays_kr import today_kst

_WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "watchlist.yaml",
)


def _watchlist_stocks() -> List[Tuple[str, str]]:
    """watchlist.yaml 에서 (종목명, ticker) 목록을 중복 제거해 반환."""
    if not os.path.exists(_WATCHLIST_PATH):
        return []
    try:
        with open(_WATCHLIST_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[earnings] watchlist.yaml 파싱 실패: {e}")
        return []
    seen, out = set(), []
    for t in data.get("themes", []) or []:
        for s in t.get("stocks", []) or []:
            tk = s.get("ticker")
            if tk and tk not in seen:
                seen.add(tk)
                out.append((s.get("name", tk), tk))
    return out


def _next_earnings_date(ticker: str) -> Optional[dt.date]:
    """yfinance 로 다음 실적발표(예정)일 1건. 없거나 실패 시 None."""
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception:  # noqa: BLE001
        return None

    val = None
    if isinstance(cal, dict):
        val = cal.get("Earnings Date")
    else:  # 구버전 yfinance: DataFrame
        try:
            if cal is not None and "Earnings Date" in list(getattr(cal, "index", [])):
                val = cal.loc["Earnings Date"].tolist()
        except Exception:  # noqa: BLE001
            val = None

    if isinstance(val, (list, tuple)):
        val = val[0] if val else None
    if val is None:
        return None
    if isinstance(val, dt.datetime):
        return val.date()
    if isinstance(val, dt.date):
        return val
    try:
        return dt.date.fromisoformat(str(val)[:10])
    except Exception:  # noqa: BLE001
        return None


def fetch_earnings_events(day: Optional[dt.date] = None,
                          lookahead: int = 8) -> List[CalendarEvent]:
    """워치리스트 종목 중 오늘부터 lookahead 일 내 실적발표 예정 종목을 이벤트로 반환."""
    day = day or today_kst()
    out: List[CalendarEvent] = []
    for name, ticker in _watchlist_stocks():
        ed = _next_earnings_date(ticker)
        if ed is None:
            continue
        diff = (ed - day).days
        if 0 <= diff <= lookahead:
            out.append(CalendarEvent(
                title=f"실적발표 예정: {name}", category="실적",
                note="발표 전후 변동성 확대 가능 — 미리 대응 계획 점검",
                days_until=diff))
    out.sort(key=lambda e: e.days_until)
    return out


if __name__ == "__main__":
    for e in fetch_earnings_events():
        print(f"[{e.dlabel}] {e.title}")
