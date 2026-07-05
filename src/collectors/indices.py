"""[섹션 1] 주요 지수 & 환율 수집 (yfinance).

국내(코스피·코스닥), 해외(다우·나스닥·S&P500), 환율(원/달러)의
전일 대비 등락을 가져온다. 무료·무키 소스(Yahoo Finance)만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .. import _ssl_bootstrap  # noqa: F401  (yfinance import 전에 SSL 경로 보정)
import yfinance as yf

# (그룹, 표시명, yfinance 티커, 소수점 자리)
_INDICES = [
    ("국내", "코스피", "^KS11", 2),
    ("국내", "코스닥", "^KQ11", 2),
    ("해외", "다우존스", "^DJI", 2),
    ("해외", "나스닥", "^IXIC", 2),
    ("해외", "S&P 500", "^GSPC", 2),
    ("환율", "원/달러", "KRW=X", 2),
]


@dataclass
class IndexQuote:
    group: str
    name: str
    value: float
    change_pct: float

    @property
    def arrow(self) -> str:
        return "▲" if self.change_pct > 0 else ("▼" if self.change_pct < 0 else "—")


def fetch_indices() -> List[IndexQuote]:
    """주요 지수·환율의 최근 마감/현재 시세를 반환. 실패 항목은 건너뛴다."""
    quotes: List[IndexQuote] = []
    for group, name, ticker, ndigits in _INDICES:
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            closes = hist["Close"].dropna() if hist is not None else []
            if len(closes) < 2:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            change_pct = (last - prev) / prev * 100 if prev else 0.0
            quotes.append(
                IndexQuote(group=group, name=name, value=round(last, ndigits),
                           change_pct=round(change_pct, 2))
            )
        except Exception as e:  # noqa: BLE001
            print(f"[indices] {name}({ticker}) 조회 실패: {e}")
    return quotes


def to_plain_lines(quotes: List[IndexQuote]) -> List[str]:
    """LLM 입력/폴백용 원본 라인."""
    lines = []
    for q in quotes:
        sign = "+" if q.change_pct > 0 else ""
        unit = "원" if q.group == "환율" else ""
        lines.append(
            f"[{q.group}] {q.name}: {q.value:,.2f}{unit} ({q.arrow} {sign}{q.change_pct:.2f}%)"
        )
    return lines


if __name__ == "__main__":
    for line in to_plain_lines(fetch_indices()):
        print(line)
