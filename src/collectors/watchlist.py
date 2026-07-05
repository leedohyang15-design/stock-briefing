"""[섹션 2] 주도 섹터 & 주목 종목 수집 (yfinance).

config/watchlist.yaml 에 정의된 우량 테마주(AI·반도체·우주방산 등)의
전일 대비 등락률을 가져와 '테마 그룹'으로 묶는다. 매일 그날 강한 섹터
순서로 정렬해 반환하므로, 선두 섹터·수치·해설이 매일 바뀐다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .. import _ssl_bootstrap  # noqa: F401  (yfinance import 전에 SSL 경로 보정)
import yaml
import yfinance as yf

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "watchlist.yaml",
)


@dataclass
class Stock:
    name: str
    ticker: str
    close: Optional[float] = None
    change_pct: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.close is not None and self.change_pct is not None


@dataclass
class ThemeGroup:
    name: str
    emoji: str
    stocks: List[Stock] = field(default_factory=list)
    summary: Optional[str] = None  # summarizer 가 채우는 급등/흐름 원인 1줄

    @property
    def avg_change(self) -> float:
        vals = [s.change_pct for s in self.stocks if s.ok]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    @property
    def is_mixed(self) -> bool:
        vals = [s.change_pct for s in self.stocks if s.ok]
        return any(v > 0 for v in vals) and any(v < 0 for v in vals)

    @property
    def label(self) -> str:
        """섹터 헤더에 붙는 등락 표기 ('+3.20%' / '-1.10%' / '혼조세')."""
        if self.is_mixed:
            return "혼조세"
        a = self.avg_change
        return f"{'+' if a >= 0 else ''}{a:.2f}%"


def _fill_quote(stock: Stock) -> None:
    try:
        hist = yf.Ticker(stock.ticker).history(period="5d", interval="1d")
        closes = hist["Close"].dropna() if hist is not None else []
        if len(closes) >= 2:
            last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
            stock.close = round(last)
            stock.change_pct = round((last - prev) / prev * 100, 2) if prev else 0.0
    except Exception as e:  # noqa: BLE001
        print(f"[watchlist] {stock.name}({stock.ticker}) 조회 실패: {e}")


def fetch_theme_groups() -> List[ThemeGroup]:
    """워치리스트 테마 그룹을 시세와 함께 반환. 그날 강한 섹터 순으로 정렬."""
    if not os.path.exists(_CONFIG_PATH):
        print(f"[watchlist] watchlist.yaml 없음: {_CONFIG_PATH}")
        return []
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    groups: List[ThemeGroup] = []
    for t in data.get("themes", []) or []:
        g = ThemeGroup(name=t.get("name", "기타"), emoji=t.get("emoji", "•"))
        for s in t.get("stocks", []) or []:
            stock = Stock(name=s["name"], ticker=s["ticker"])
            _fill_quote(stock)
            if stock.ok:
                g.stocks.append(stock)
        if g.stocks:
            groups.append(g)

    # 그날 강한 섹터(평균 등락률 높은 순)로 정렬 → 선두 섹터가 매일 바뀜
    groups.sort(key=lambda g: g.avg_change, reverse=True)
    return groups


def to_plain_lines(groups: List[ThemeGroup]) -> List[str]:
    """LLM 입력/폴백용 원본 라인 (테마별)."""
    lines = []
    for g in groups:
        members = ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        lines.append(f"[{g.name}] 평균 {g.label} — {members}")
    return lines


if __name__ == "__main__":
    for line in to_plain_lines(fetch_theme_groups()):
        print(line)
