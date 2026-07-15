"""[섹션 2] 주도 섹터 & 주목 종목 — 후보 풀에서 '거래대금 상위'만 자동 선별.

config/sectors.yaml 의 섹터별 후보(국내 4 + 해외 4) 중, 그날 거래대금이 가장 높은
국내 2 + 해외 2 종목만 뽑아 ThemeGroup 으로 반환한다. (거래대금 = 종가 × 거래량)
무료·무키 소스(yfinance)만 사용. 그날 강한 섹터 순으로 정렬.
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

import yaml

from .. import _ssl_bootstrap  # noqa: F401  (yfinance import 전에 SSL 경로 보정)
import yfinance as yf

from .watchlist import Stock, ThemeGroup

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "sectors.yaml",
)


def _load_sectors() -> List[dict]:
    if not os.path.exists(_CONFIG_PATH):
        print(f"[sectors] sectors.yaml 없음: {_CONFIG_PATH}")
        return []
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("sectors", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"[sectors] yaml 파싱 실패: {e}")
        return []


def _quote_map(tickers: List[str]) -> Dict[str, Tuple[float, float, float]]:
    """티커 → (종가, 등락률%, 거래대금). yfinance 배치 다운로드."""
    out: Dict[str, Tuple[float, float, float]] = {}
    if not tickers:
        return out
    try:
        data = yf.download(tickers, period="5d", interval="1d", group_by="ticker",
                           auto_adjust=False, progress=False, threads=True)
    except Exception as e:  # noqa: BLE001
        print(f"[sectors] yfinance 다운로드 실패: {e}")
        return out
    for t in tickers:
        try:
            df = data[t]  # group_by='ticker': 티커별 OHLCV 서브프레임
            closes = df["Close"].dropna()
            vols = df["Volume"].dropna()
            if len(closes) < 2:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            vol = float(vols.iloc[-1]) if len(vols) else 0.0
            chg = round((last - prev) / prev * 100, 2) if prev else 0.0
            out[t] = (round(last, 2), chg, last * vol)
        except Exception:  # noqa: BLE001
            continue
    return out


def _is_krw(ticker: str) -> bool:
    return ticker.endswith((".KS", ".KQ"))


def fetch_sector_groups(top_domestic: int = 2, top_overseas: int = 2) -> List[ThemeGroup]:
    """섹터별로 거래대금 상위 국내 top_domestic + 해외 top_overseas 종목을 담은
    ThemeGroup 목록을 그날 강한 섹터 순으로 반환."""
    sectors = _load_sectors()
    if not sectors:
        return []

    # 전 종목 티커를 모아 한 번에 시세 조회
    all_tickers = []
    for sec in sectors:
        for grp in ("domestic", "overseas"):
            for s in sec.get(grp, []) or []:
                if s.get("ticker"):
                    all_tickers.append(s["ticker"])
    quotes = _quote_map(sorted(set(all_tickers)))

    def _pick(cands: List[dict], n: int) -> List[Stock]:
        rows = []
        for s in cands:
            q = quotes.get(s.get("ticker", ""))
            if not q:
                continue
            close, chg, tval = q
            rows.append((tval, Stock(
                name=s.get("name", s["ticker"]), ticker=s["ticker"],
                close=close, change_pct=chg,
                currency="KRW" if _is_krw(s["ticker"]) else "USD",
                trade_value=tval)))
        rows.sort(key=lambda r: r[0], reverse=True)  # 거래대금 큰 순
        return [st for _, st in rows[:n]]

    groups: List[ThemeGroup] = []
    for sec in sectors:
        stocks = (_pick(sec.get("domestic", []) or [], top_domestic)
                  + _pick(sec.get("overseas", []) or [], top_overseas))
        if stocks:
            groups.append(ThemeGroup(name=sec.get("name", "기타"),
                                     emoji=sec.get("emoji", "•"), stocks=stocks))

    groups.sort(key=lambda g: g.avg_change, reverse=True)  # 그날 강한 섹터 먼저
    return groups


if __name__ == "__main__":
    for g in fetch_sector_groups():
        members = ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        print(f"{g.emoji} {g.name} ({g.label}) — {members}")
