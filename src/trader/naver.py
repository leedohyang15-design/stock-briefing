"""네이버 금융: 종목 코드가 포함된 거래대금 상위, 종목 뉴스·공시 제목."""
from __future__ import annotations

import re
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Referer": "https://finance.naver.com/",
}


def _soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=_HEADERS, timeout=10)
    r.encoding = "euc-kr"
    return BeautifulSoup(r.text, "lxml")


def top_trading_value(n: int = 30) -> List[Dict]:
    """코스피+코스닥 거래상위 (최근 거래일 기준). [{code,name,price,change_pct,value_krw}]"""
    out: List[Dict] = []
    for sosok in (0, 1):
        try:
            soup = _soup(f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}")
        except Exception as e:  # noqa: BLE001
            print(f"[naver] 거래상위 실패: {e}")
            continue
        for tr in soup.select("table.type_2 tr"):
            a = tr.select_one("a.tltle")
            if not a:
                continue
            m = re.search(r"code=(\d{6})", a.get("href", ""))
            nums = [td.get_text(strip=True).replace(",", "").replace("%", "")
                    for td in tr.find_all("td") if "number" in (td.get("class") or [])]
            if not m or len(nums) < 5:
                continue
            try:
                out.append({"code": m.group(1), "name": a.get_text(strip=True), "price": float(nums[0]),
                            "change_pct": float(nums[2]), "value_krw": float(nums[4]) * 1e6})
            except ValueError:
                continue
    seen, uniq = set(), []
    for s in sorted(out, key=lambda x: x["value_krw"], reverse=True):
        if s["code"] not in seen:
            seen.add(s["code"])
            uniq.append(s)
    return uniq[:n]


def stock_news(code: str, limit: int = 10) -> List[Dict]:
    """종목 뉴스 제목·일시. [{title, date}]"""
    try:
        soup = _soup(f"https://finance.naver.com/item/news_news.naver?code={code}&page=1")
    except Exception as e:  # noqa: BLE001
        print(f"[naver] 뉴스 실패 {code}: {e}")
        return []
    out = []
    for tr in soup.select("table.type5 tr"):
        a = tr.select_one("td.title a")
        d = tr.select_one("td.date")
        if a:
            out.append({"title": a.get_text(strip=True), "date": d.get_text(strip=True) if d else ""})
        if len(out) >= limit:
            break
    return out


def stock_notices(code: str, limit: int = 10) -> List[Dict]:
    """종목 공시 제목·일시. [{title, date}]"""
    try:
        soup = _soup(f"https://finance.naver.com/item/news_notice.naver?code={code}&page=1")
    except Exception as e:  # noqa: BLE001
        print(f"[naver] 공시 실패 {code}: {e}")
        return []
    out = []
    for tr in soup.select("table.type6 tr, table.type5 tr"):
        a = tr.select_one("td.title a")
        d = tr.select_one("td.date")
        if a:
            out.append({"title": a.get_text(strip=True), "date": d.get_text(strip=True) if d else ""})
        if len(out) >= limit:
            break
    return out
