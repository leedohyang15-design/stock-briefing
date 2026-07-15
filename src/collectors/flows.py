"""[섹션 2 보강] 수급 & 거래대금 — 개인 투자자 관점 (네이버 금융).

기존엔 pykrx(KRX 공개데이터)를 썼으나, GitHub Actions 러너(해외/데이터센터 IP)
에서는 data.krx.co.kr 접근이 차단돼 빈 응답("Expecting value...")만 돌아온다.
러너에서 접근 가능한 네이버 금융(finance.naver.com) 스크래핑으로 전환한다.
(무료·무키, hot_sectors.py 와 동일한 방식)

- fetch_trading_value_top(): 거래대금 상위 종목 (sise_quant) — 정상 동작
- fetch_investor_flows():   외국인·기관 순매매 상위 — 종목별 frgn.naver 표를 파싱

기존 watchlist.Stock 모델을 재사용해 formatter/summarizer 와 호환한다.
trade_value 단위는 '원'(포맷터가 억으로 환산). 순매매(수량 기준) 항목은
금액을 알 수 없어 trade_value=None 으로 두고 종목명만 노출한다.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, List, Optional, Tuple

import requests
import yaml
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
# 종목별 외국인·기관 순매매 페이지(서버렌더, table.type2)
_FRGN_URL = "https://finance.naver.com/item/frgn.naver?code={code}"
_SECTORS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "sectors.yaml",
)


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


# ── 외국인·기관 순매매 상위 (종목별 frgn.naver 파싱) ──────
def _domestic_universe() -> List[Tuple[str, str]]:
    """sectors.yaml 의 국내(.KS/.KQ) 종목 → (종목명, 6자리 코드) 목록. 중복 제거."""
    if not os.path.exists(_SECTORS_PATH):
        print(f"[flows] sectors.yaml 없음: {_SECTORS_PATH}")
        return []
    try:
        with open(_SECTORS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[flows] sectors.yaml 파싱 실패: {e}")
        return []
    out, seen = [], set()
    for sec in data.get("sectors", []) or []:
        for s in sec.get("domestic", []) or []:
            tk = str(s.get("ticker", ""))
            if tk.endswith((".KS", ".KQ")) and tk[:6].isdigit() and tk[:6] not in seen:
                seen.add(tk[:6])
                out.append((s.get("name", tk[:6]), tk[:6]))
    return out


def _signed_num(td) -> Optional[float]:
    """순매매량 셀 → 부호 있는 float. frgn.naver 는 셀 텍스트에 +/- 부호를 그대로 담는다
    (예: '+5,326,105' 순매수 / '-1,128,775' 순매도) → _num 이 부호를 보존한다."""
    return _num(td.get_text(strip=True))


def _row_cells(tr):
    """행의 셀(th+td)을 문서 순서대로. 날짜가 th 로 오는 표도 대응."""
    return tr.find_all(["th", "td"])


def _parse_frgn_latest(code: str) -> Optional[Tuple[float, float, float]]:
    """종목의 최근 거래일 (종가, 기관 순매매량, 외국인 순매매량) 반환. 실패 시 None.

    frgn.naver 일별 표 데이터 행 컬럼 순서:
      0 날짜 · 1 종가 · 2 전일비 · 3 등락률 · 4 거래량
      · 5 기관 순매매량 · 6 외국인 순매매량 · 7 외국인 보유주수 · 8 보유율
    (type2 표가 여러 개일 수 있어 날짜 행이 나오는 표를 찾아 파싱한다.)
    """
    soup = _soup(_FRGN_URL.format(code=code))
    if soup is None:
        return None
    for table in soup.select("table.type2"):
        for tr in table.select("tr"):
            cells = _row_cells(tr)
            if len(cells) < 7:
                continue
            date_txt = cells[0].get_text(strip=True)
            if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_txt):
                continue
            close = _num(cells[1].get_text(strip=True))
            if close is None:
                continue
            inst = _signed_num(cells[5]) or 0.0
            foreign = _signed_num(cells[6]) or 0.0
            return (close, inst, foreign)  # 가장 최근(맨 위) 데이터 행만
    return None


def fetch_investor_flows(trade_day: dt.date, n: int = 3,
                         market: str = "KOSPI") -> Dict[str, object]:
    """추적 종목(sectors.yaml 국내)의 외국인·기관·개인 순매매 상위를 반환.

    종목별 frgn.naver(서버렌더) 표에서 최근 거래일의 기관/외국인 순매매량을 읽고,
    순매매 '금액'(≈ 순매매량 × 종가)이 큰 순으로 순매수/순매도 top n 을 뽑는다.
    개인 순매매는 -(외국인 + 기관)으로 근사한다(기타법인·프로그램 제외 오차 있음).
    반환 Stock.trade_value = |순매매 금액|(원). 금액을 몰라도 종목명은 노출된다.
    """
    recs: List[Tuple[str, float, float, float]] = []  # (종목명, 종가, 기관량, 외국인량)
    for name, code in _domestic_universe():
        parsed = _parse_frgn_latest(code)
        if parsed is None:
            continue
        close, inst_q, for_q = parsed
        recs.append((name, close, inst_q, for_q))

    def _mk(name: str, close: float, qty: float) -> Stock:
        return Stock(name=name, ticker="", close=close, change_pct=0.0,
                     currency="KRW", trade_value=abs(qty) * close)

    def _top(pick, positive: bool) -> List[Stock]:
        pool = [(name, close, pick(inst_q, for_q))
                for (name, close, inst_q, for_q) in recs]
        pool = [(nm, cl, q) for (nm, cl, q) in pool
                if q != 0 and (q > 0) == positive]
        pool.sort(key=lambda r: abs(r[2] * r[1]), reverse=True)  # 금액 큰 순
        return [_mk(nm, cl, q) for nm, cl, q in pool[:n]]

    foreign_buy = _top(lambda i, f: f, positive=True)
    foreign_sell = _top(lambda i, f: f, positive=False)
    inst_buy = _top(lambda i, f: i, positive=True)
    inst_sell = _top(lambda i, f: i, positive=False)

    # 개인 순매매 ≈ -(외국인 + 기관). 순매수 금액 큰 순.
    retail = [(nm, cl, -(iq + fq)) for (nm, cl, iq, fq) in recs]
    retail = [(nm, cl, q) for (nm, cl, q) in retail if q > 0]
    retail.sort(key=lambda r: r[2] * r[1], reverse=True)
    retail_buy = [_mk(nm, cl, q) for nm, cl, q in retail[:n]]

    return {"buy": {"외국인": foreign_buy, "기관": inst_buy},
            "sell": {"외국인": foreign_sell, "기관": inst_sell},
            "retail_buy": retail_buy}


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
        for who, rows in fl[side_key].items():  # type: ignore[union-attr]
            body = ", ".join(f"{s.name}({(s.trade_value or 0)/1e8:,.0f}억)" for s in rows)
            print(f"- {who} {label_ko}: {body or '(없음)'}")
    retail = fl.get("retail_buy", [])  # type: ignore[union-attr]
    print("- 개인 순매수: " + (", ".join(
        f"{s.name}({(s.trade_value or 0)/1e8:,.0f}억)" for s in retail) or "(없음)"))
