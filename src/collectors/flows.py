"""[섹션 2 보강] 수급 & 거래대금 — 개인 투자자 관점 (네이버 금융).

기존엔 pykrx(KRX 공개데이터)를 썼으나, GitHub Actions 러너(해외/데이터센터 IP)
에서는 data.krx.co.kr 접근이 차단돼 빈 응답("Expecting value...")만 돌아온다.
러너에서 접근 가능한 네이버 금융(finance.naver.com) 스크래핑으로 전환한다.
(무료·무키, hot_sectors.py 와 동일한 방식)

- fetch_trading_value_top(): 거래대금 상위 종목 (sise_quant) — 정상 동작
- fetch_investor_flows():   외국인·기관 순매매 상위 — 현재 no-op(빈 결과, 사유는 함수 주석)

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


# ── 외국인·기관 순매매 상위 (미구현) ──────────────────────
def fetch_investor_flows(trade_day: dt.date, n: int = 3,
                         market: str = "KOSPI") -> Dict[str, object]:
    """외국인·기관/개인 순매매 상위 — 현재는 빈 결과(no-op).

    무료·러너접근 가능 소스로는 종목별 투자자 순매매 상위를 안정적으로 얻지 못했다:
      · KRX(pykrx): GitHub Actions 러너의 해외 IP를 차단.
      · 네이버 frgn.naver: 404(존재하지 않는 URL).
      · 네이버 sise_deal_rank.naver: 페이지는 있으나 본문 순매매 표의 DOM 구조를
        헤드리스 환경에서 확정하지 못함(사이드바 표만 잡힘).
    이 함수는 formatter/main 과의 호환을 위해 빈 구조를 반환한다. 향후 정확한
    소스(네이버 deal_rank 정밀 파서 또는 유료·인증 API)가 확정되면 여기만 채우면 된다.
    (거래대금 상위 fetch_trading_value_top 은 네이버 sise_quant 로 정상 동작한다.)
    """
    return {"buy": {"외국인": [], "기관": []},
            "sell": {"외국인": [], "기관": []},
            "retail_buy": []}


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
