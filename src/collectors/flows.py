"""[섹션 2 보강] 수급 & 거래대금 — 개인 투자자 관점 (네이버 금융).

기존엔 pykrx(KRX 공개데이터)를 썼으나, GitHub Actions 러너(해외/데이터센터 IP)
에서는 data.krx.co.kr 접근이 차단돼 빈 응답("Expecting value...")만 돌아온다.
러너에서 접근 가능한 네이버 금융(finance.naver.com) 스크래핑으로 전환한다.
(무료·무키, hot_sectors.py 와 동일한 방식)

- fetch_trading_value_top(): 거래대금 상위 종목 (sise_quant)
- fetch_investor_flows():   외국인·기관 순매매 상위 (frgn.naver)

기존 watchlist.Stock 모델을 재사용해 formatter/summarizer 와 호환한다.
trade_value 단위는 '원'(포맷터가 억으로 환산). 순매매(수량 기준) 항목은
금액을 알 수 없어 trade_value=None 으로 두고 종목명만 노출한다.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .watchlist import Stock

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}
# sosok: 0=코스피, 1=코스닥
_QUANT_URL = "https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
# 외국인·기관 순매매 상위 후보 URL (frgn.naver 는 404 확인됨 → deal_rank 계열 시도)
_DEAL_URLS = [
    "https://finance.naver.com/sise/sise_deal_rank.naver",
    "https://finance.naver.com/sise/sise_deal_rank.naver?sosok=0&investor_gubun=1000&type=buy",
]


def _num(text) -> Optional[float]:
    """'1,234' · '+1.20%' · '-56' → float. 부호(-)는 보존, +/%/콤마는 제거."""
    try:
        return float(str(text).replace(",", "").replace("%", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return None


def _soup(url: str) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:  # noqa: BLE001
        print(f"[flows] 네이버 요청 실패({url}): {e}")
        return None


def _number_cells(tr) -> List[str]:
    """행에서 class에 'number'가 있는 td 텍스트만 순서대로."""
    return [td.get_text(strip=True) for td in tr.find_all("td")
            if "number" in (td.get("class") or [])]


# ── 거래대금 상위 (sise_quant) ────────────────────────────
def fetch_trading_value_top(trade_day: dt.date, n: int = 5,
                            market: str = "ALL") -> List[Stock]:
    """거래대금 상위 종목. 네이버 '거래상위' 페이지(코스피+코스닥)에서 거래대금 기준 재정렬.

    trade_value = 거래대금(원). (네이버는 백만원 단위 → ×1e6)
    trade_day/market 인자는 하위호환용이며 네이버는 최신 종가 기준으로 조회한다.
    number 셀 상대 순서: 0=현재가, 1=전일비, 2=등락률, 3=거래량, 4=거래대금.
    """
    out: List[Stock] = []
    for sosok in (0, 1):  # 코스피 + 코스닥
        soup = _soup(_QUANT_URL.format(sosok=sosok))
        if soup is None:
            continue
        table = soup.select_one("table.type_2")
        if table is None:
            print(f"[flows] 거래대금: table.type_2 없음 (sosok={sosok})")
            continue
        rows_parsed = 0
        for tr in table.select("tr"):
            a = tr.select_one("a.tltle")
            if a is None:
                continue
            nums = _number_cells(tr)
            if len(nums) < 5:
                continue
            name = a.get_text(strip=True)
            price = _num(nums[0])
            chg = _num(nums[2])
            val_m = _num(nums[4])  # 거래대금(백만원)
            if name and val_m is not None:
                out.append(Stock(name=name, ticker="", close=price,
                                 change_pct=chg or 0.0, currency="KRW",
                                 trade_value=val_m * 1e6))  # 백만원 → 원
                rows_parsed += 1
        if rows_parsed == 0:
            # 파싱 구조가 바뀐 경우 러너 로그로 진단할 수 있게 헤더를 남긴다
            ths = [th.get_text(strip=True) for th in table.select("thead th")]
            print(f"[flows] 거래대금 파싱 0건 (sosok={sosok}). thead={ths}")
    # 이름 중복 제거(코스피/코스닥 합산) 후 거래대금 큰 순 top n
    seen, uniq = set(), []
    for s in sorted(out, key=lambda s: s.trade_value or 0, reverse=True):
        if s.name in seen:
            continue
        seen.add(s.name)
        uniq.append(s)
        if len(uniq) >= n:
            break
    return uniq


# ── 외국인·기관 순매매 상위 (frgn.naver) ──────────────────
def fetch_investor_flows(trade_day: dt.date, n: int = 3,
                         market: str = "KOSPI") -> Dict[str, object]:
    """외국인·기관 순매매 상위(수량 기준)를 네이버 frgn.naver 에서 조회.

    반환:
      {
        "buy":  {"외국인": [Stock], "기관": [Stock]},   # 순매수 상위(순매매량 큰 순)
        "sell": {"외국인": [Stock], "기관": [Stock]},   # 순매도 상위(순매매량 작은 순)
        "retail_buy": [],                                # 개인은 네이버 미제공 → 빈 리스트
      }
    frgn.naver number 셀 상대 순서(추정):
      0=현재가,1=전일비,2=등락률,3=거래량,4=외국인 순매매량,...,기관 순매매량은 마지막.
    금액을 알 수 없어 Stock.trade_value=None (종목명만 노출). 순매매량은 정렬에만 사용.
    """
    empty = {"buy": {"외국인": [], "기관": []},
             "sell": {"외국인": [], "기관": []},
             "retail_buy": []}
    def _stock_table(sp):
        """종목 상세 링크(code=)가 들어있는 테이블(=데이터 표)을 찾는다."""
        if sp is None:
            return None
        return next((t for t in sp.select("table")
                     if t.select_one("a[href*='code=']")), None)

    table = None
    for url in _DEAL_URLS:
        sp = _soup(url)
        table = _stock_table(sp)
        if table is not None:
            print(f"[flows] 순매매: 표 발견 → {url}")
            break
        if sp is not None:
            print(f"[flows] 순매매: 표 없음 @ {url} "
                  f"(table수={len(sp.select('table'))}) snippet={sp.get_text(strip=True)[:80]!r}")
    if table is None:
        return empty

    # (종목명, 외국인순매매량, 기관순매매량) 수집
    recs = []
    for tr in table.select("tr"):
        a = tr.select_one("a[href*='code=']")
        if a is None:
            continue
        nums = _number_cells(tr)
        if len(nums) < 5:
            continue
        name = a.get_text(strip=True)
        frgn = _num(nums[4])                       # 외국인 순매매량
        inst = _num(nums[-1]) if len(nums) >= 6 else None  # 기관 순매매량(마지막 추정)
        if name and frgn is not None:
            recs.append((name, frgn, inst))

    if not recs:
        # 러너 로그로 frgn 실제 컬럼 구조를 진단 (다음 라운드 인덱스 보정용)
        ths = [th.get_text(strip=True) for th in table.select("th")]
        first = next((tr for tr in table.select("tr")
                      if tr.select_one("a[href*='code=']")), None)
        cells = [td.get_text(strip=True) for td in first.find_all("td")] if first else []
        print(f"[flows] 순매매 파싱 0건. th={ths} | 첫행셀={cells}")
        return empty

    def _stock(name: str) -> Stock:
        return Stock(name=name, ticker="", currency="KRW", trade_value=None)

    def _top(idx: int, positive: bool) -> List[Stock]:
        pool = [r for r in recs if r[idx] is not None and
                (r[idx] > 0 if positive else r[idx] < 0)]
        pool.sort(key=lambda r: r[idx], reverse=positive)
        return [_stock(r[0]) for r in pool[:n]]

    inst_ok = any(r[2] is not None for r in recs)
    return {
        "buy":  {"외국인": _top(1, True),
                 "기관":  _top(2, True) if inst_ok else []},
        "sell": {"외국인": _top(1, False),
                 "기관":  _top(2, False) if inst_ok else []},
        "retail_buy": [],
    }


def fetch_investor_net_buy(trade_day: dt.date, n: int = 3,
                           market: str = "KOSPI") -> Dict[str, List[Stock]]:
    """(하위호환) 외국인·기관 순매수 상위만 반환."""
    return fetch_investor_flows(trade_day, n, market)["buy"]  # type: ignore[return-value]


if __name__ == "__main__":
    # 스모크 테스트 (네이버 접근 가능한 환경에서만 데이터가 나온다)
    day = dt.date.today()
    print("\n[거래대금 상위]")
    for s in fetch_trading_value_top(day, 5):
        print(f"- {s.name}: 거래대금 {(s.trade_value or 0) / 1e8:,.0f}억 · {s.change_pct:+.2f}%")

    print("\n[외국인·기관 순매매 상위]")
    fl = fetch_investor_flows(day, 3)
    for side_key, label_ko in (("buy", "순매수"), ("sell", "순매도")):
        for who, rows in fl[side_key].items():
            print(f"- {who} {label_ko}: " + ", ".join(s.name for s in rows))
