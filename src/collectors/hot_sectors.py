"""[섹션 2] 실시간 핫섹터 & 인기 종목 수집.

- 국내: 네이버 금융 '테마별 시세'에서 그날 등락률 상위 테마(섹터)를 뽑고,
  각 테마의 구성종목 중 상위 종목을 대표주로 표출한다. (매일 자동으로 바뀜)
- 해외: 야후 파이낸스 트렌딩(미국에서 실시간 검색이 많은 종목)을 별도로 표출한다.

무료·무키 소스만 사용한다.
"""
from __future__ import annotations

import re
from typing import List

import requests
from bs4 import BeautifulSoup

from .. import _ssl_bootstrap  # noqa: F401  (yfinance 요청 전에 SSL 경로 보정)
import yfinance as yf

from .watchlist import Stock, ThemeGroup  # 포맷터/요약기와 호환되는 모델 재사용

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}
_LIST_URL = "https://finance.naver.com/sise/theme.naver?field=change_rate&ordering=desc"
_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"
_TRENDING_URL = "https://query1.finance.yahoo.com/v1/finance/trending/US?count=25"

_RANK_EMOJI = ["🥇", "🥈", "🥉", "🔥", "🔥", "🔥", "🔥", "🔥"]


def _parse_pct(text: str):
    try:
        return float(text.replace("%", "").replace("+", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_num(text: str):
    try:
        return float(text.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


# ── 국내: 네이버 실시간 핫테마 ────────────────────────────
def _fetch_theme_stocks(no: str, per_sector: int) -> List[Stock]:
    """테마 상세 페이지에서 등락률 상위 구성종목을 per_sector 개 반환."""
    resp = requests.get(_DETAIL_URL.format(no=no), headers=_HEADERS, timeout=10)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "lxml")
    rows: List[Stock] = []
    for tr in soup.select("table.type_5 tr"):
        a = tr.select_one("a")
        tds = tr.select("td")
        if a is None or len(tds) < 6:
            continue
        name = a.get_text(strip=True)
        price = _parse_num(tds[2].get_text(strip=True))   # 현재가
        chg = _parse_pct(tds[4].get_text(strip=True))     # 등락률
        if name and price is not None and chg is not None:
            rows.append(Stock(name=name, ticker="", close=price, change_pct=chg, currency="KRW"))
    rows.sort(key=lambda s: s.change_pct, reverse=True)
    return rows[:per_sector]


def fetch_hot_sectors(top_n: int = 7, per_sector: int = 2) -> List[ThemeGroup]:
    """그날 등락률 상위 테마 top_n 개를 대표 구성종목과 함께 반환 (실시간)."""
    groups: List[ThemeGroup] = []
    try:
        resp = requests.get(_LIST_URL, headers=_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        candidates = []
        for tr in soup.select("table.type_1 tr"):
            a = tr.select_one("td.col_type1 a")
            tds = tr.select("td")
            if a is None or len(tds) < 2:
                continue
            name = a.get_text(strip=True)
            chg = _parse_pct(tds[1].get_text(strip=True))
            m = re.search(r"no=(\d+)", a.get("href", ""))
            if name and chg is not None and m:
                candidates.append((name, chg, m.group(1)))

        for i, (name, chg, no) in enumerate(candidates[:top_n]):
            try:
                stocks = _fetch_theme_stocks(no, per_sector)
            except Exception as e:  # noqa: BLE001
                print(f"[hot_sectors] '{name}' 구성종목 조회 실패: {e}")
                stocks = []
            if stocks:
                emoji = _RANK_EMOJI[i] if i < len(_RANK_EMOJI) else "🔥"
                groups.append(ThemeGroup(name=name, emoji=emoji, stocks=stocks, headline_pct=round(chg, 2)))
    except Exception as e:  # noqa: BLE001
        print(f"[hot_sectors] 테마 목록 조회 실패: {e}")
    return groups


# ── 해외: 야후 트렌딩(미국 인기검색 종목) ─────────────────
def fetch_trending_us(limit: int = 5) -> List[Stock]:
    """미국에서 실시간 검색이 많은 종목 상위 limit 개 (등락률 포함)."""
    out: List[Stock] = []
    try:
        resp = requests.get(_TRENDING_URL, headers=_HEADERS, timeout=10)
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        # 순수 미국 티커만 (KR '.KS' 등, 특수기호 제외)
        syms = [q["symbol"] for q in quotes if q.get("symbol", "").isalpha()]
    except Exception as e:  # noqa: BLE001
        print(f"[hot_sectors] 미국 트렌딩 조회 실패: {e}")
        return out

    for sym in syms:
        if len(out) >= limit:
            break
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            closes = hist["Close"].dropna() if hist is not None else []
            if len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                chg = round((last - prev) / prev * 100, 2) if prev else 0.0
                out.append(Stock(name=sym, ticker=sym, close=round(last, 2),
                                 change_pct=chg, currency="USD"))
        except Exception:  # noqa: BLE001
            continue
    return out


if __name__ == "__main__":
    print("=== 실시간 핫섹터 ===")
    for g in fetch_hot_sectors():
        members = ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        print(f"{g.emoji} {g.name} ({g.label}) — {members}")
    print("\n=== 미국 인기검색 종목 ===")
    for s in fetch_trending_us():
        print(f"{s.name} {s.change_pct:+.2f}% (${s.close})")
