"""[섹션 2 보강] 수급 & 거래대금 — 개인 투자자 관점 (네이버 증권 JSON API).

pykrx(data.krx.co.kr)는 GitHub Actions 러너에서 차단되고, 구 finance.naver.com HTML
(sise_quant / frgn.naver)은 2026-11 부로 신규 SPA(stock.naver.com)로 리다이렉트되어
파싱이 불가하다. 모바일 사이트가 쓰는 JSON API(m.stock.naver.com/api, 무료·무키)를 쓴다.

- fetch_trading_value_top(): 거래상위(quantTop) 코스피+코스닥 → 거래대금 순 재정렬
- fetch_investor_flows():   추적 종목별 /stock/{code}/trend 의 외국인·기관 순매매량

기존 watchlist.Stock 모델을 재사용해 formatter/summarizer 와 호환한다.
trade_value 단위는 '원'(포맷터가 억으로 환산).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from . import _naver
from .watchlist import Stock

_MARKETS = ("KOSPI", "KOSDAQ")
_QUANT_PAGE_SIZE = 100  # 거래량 상위 100 종목 안에서 거래대금 순 재정렬
_SECTORS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "sectors.yaml",
)

_num = _naver.num  # 하위호환 (기존 모듈 내부 이름)


def _trade_value_won(row: Dict[str, Any]) -> Optional[float]:
    """거래대금(원). Raw(원) 우선, 없으면 accumulatedTradingValue(백만원) × 1e6."""
    raw = _num(row.get("accumulatedTradingValueRaw"))
    if raw is not None:
        return raw
    val_m = _num(row.get("accumulatedTradingValue"))
    return val_m * 1e6 if val_m is not None else None


def _parse_quant(data: Any) -> List[Stock]:
    """quantTop 응답 → Stock 목록 (trade_value=원)."""
    out: List[Stock] = []
    for row in (data or {}).get("stocks", []) if isinstance(data, dict) else []:
        name = row.get("stockName")
        tval = _trade_value_won(row)
        if not name or tval is None:
            continue
        out.append(Stock(name=name, ticker=str(row.get("itemCode", "")),
                         close=_num(row.get("closePrice")),
                         change_pct=_num(row.get("fluctuationsRatio")) or 0.0,
                         currency="KRW", trade_value=tval))
    return out


# ── 거래대금 상위 (quantTop) ─────────────────────────────
def fetch_trading_value_top(trade_day: dt.date, n: int = 5,
                            market: str = "ALL") -> List[Stock]:
    """거래대금 상위 종목. 코스피+코스닥 '거래상위' 목록을 거래대금 기준으로 재정렬.

    trade_value = 거래대금(원). trade_day/market 인자는 하위호환용이며
    네이버는 최신(장중이면 실시간, 장후면 당일 종가) 기준으로 조회한다.
    """
    out: List[Stock] = []
    for mkt in _MARKETS:
        data = _naver.get_json(f"/stocks/quantTop/{mkt}",
                               {"page": 1, "pageSize": _QUANT_PAGE_SIZE})
        rows = _parse_quant(data)
        if not rows:
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"[flows] 거래대금 파싱 0건 ({mkt}). 응답 keys={keys}")
        out.extend(rows)
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


# ── 외국인·기관 순매매 상위 (종목별 trend JSON) ──────────
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


def _parse_trend_latest(data: Any) -> Optional[Tuple[float, float, float]]:
    """trend 응답(일별 dict 리스트, 최신순) → 최근 거래일 (종가, 기관 순매매량, 외국인 순매매량).

    필드: closePrice · organPureBuyQuant · foreignerPureBuyQuant (예: '+661,271' / '-45,179').
    """
    if isinstance(data, dict):
        data = data.get("trends") or data.get("items") or []
    for row in data or []:
        if not isinstance(row, dict):
            continue
        close = _num(row.get("closePrice"))
        if close is None:
            continue
        inst = _num(row.get("organPureBuyQuant")) or 0.0
        foreign = _num(row.get("foreignerPureBuyQuant")) or 0.0
        return (close, inst, foreign)  # 가장 최근(맨 앞) 행만
    return None


def _parse_frgn_latest(code: str) -> Optional[Tuple[float, float, float]]:
    """종목의 최근 거래일 (종가, 기관 순매매량, 외국인 순매매량). 실패 시 None."""
    return _parse_trend_latest(
        _naver.get_json(f"/stock/{code}/trend", {"pageSize": 5}))


def fetch_investor_flows(trade_day: dt.date, n: int = 3,
                         market: str = "KOSPI") -> Dict[str, object]:
    """추적 종목(sectors.yaml 국내)의 외국인·기관·개인 순매매 상위를 반환.

    종목별 trend JSON 에서 최근 거래일의 기관/외국인 순매매량을 읽고,
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
    # 라이브 확인 (m.stock.naver.com 접근 가능한 환경에서만 데이터가 나온다)
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
