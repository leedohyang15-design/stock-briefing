"""시장 프로필: 국장(한국투자증권 국내주식) / 미장(한국투자증권 해외주식, 미국).

한 프로세스는 한 시장만 돈다. activate() 가 시간대·장 시작·호가단위 등 전역 설정을 바꾼다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

from .settings import CONFIG_PATH, DATA_DIR, ROOT


@dataclass(frozen=True)
class Market:
    key: str                   # kr | us
    name: str                  # 국장 | 미장
    tz: dt.tzinfo
    open: str                  # 장 시작 HHMM (현지)
    close: str
    currency: str
    config_path: Path
    db_name: str
    indices: Tuple[Tuple[str, str], ...]   # (코드, 표시명)
    tg_prefix: str

    @property
    def db_path(self) -> Path:
        return DATA_DIR / self.db_name

    def is_holiday(self, day: dt.date) -> bool:
        if self.key == "kr":
            from ..holidays_kr import is_market_holiday
            return is_market_holiday(day)
        import holidays
        return day.weekday() >= 5 or day in holidays.financial_holidays("NYSE", years=day.year)

    def today(self) -> dt.date:
        return dt.datetime.now(self.tz).date()


KR = Market("kr", "국장", ZoneInfo("Asia/Seoul"), "0900", "1530", "KRW", CONFIG_PATH, "trader.db",
            (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")), "")
US = Market("us", "미장", ZoneInfo("America/New_York"), "0930", "1600", "USD", ROOT / "config" / "trader_us.yaml",
            "trader_us.db", (("SPY", "S&P500(SPY)"), ("QQQ", "나스닥100(QQQ)")), "[미장] ")
MARKETS = {"kr": KR, "us": US}
CURRENT = KR


def activate(key: str) -> Market:
    """전역 설정을 해당 시장으로 바꾼다."""
    global CURRENT
    from . import models, strategy, ticks
    m = MARKETS[key]
    models.MARKET_TZ = m.tz
    strategy.SESSION_OPEN = m.open
    ticks.MARKET = m.key
    CURRENT = m
    return m


def all_markets() -> List[Market]:
    return [KR, US]
