"""[섹션 2 보강] 수급 & 거래대금 — 개인 투자자 관점.

무료·무키 소스(pykrx = KRX 공개데이터)만 사용한다. API 키·로그인 불필요.
(KRX_ID/KRX_PW 환경변수가 없으면 pykrx가 "로그인 실패" 안내를 출력하지만,
 익명으로 정상 조회되므로 무시해도 된다.)

- fetch_trading_value_top(): 거래대금 상위 종목 (그날 돈·관심이 몰린 곳)
- fetch_investor_net_buy(): 외국인·기관 순매수 상위 종목 (수급 주체)

기존 watchlist.Stock 모델을 재사용해 formatter/summarizer 와 호환한다.
값 단위: trade_value 에 '원' 단위 금액을 담는다(거래대금 또는 순매수거래대금).
포맷터에서 억원으로 환산해 표기한다.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from .watchlist import Stock


def _ymd(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def fetch_trading_value_top(trade_day: dt.date, n: int = 5,
                            market: str = "ALL") -> List[Stock]:
    """거래대금 상위 종목 (거래대금 큰 순). trade_value = 거래대금(원)."""
    try:
        from pykrx import stock
    except Exception as e:  # noqa: BLE001
        print(f"[flows] pykrx 미설치 → 거래대금 섹션 생략: {e}")
        return []

    d = _ymd(trade_day)
    try:
        df = stock.get_market_price_change(d, d, market=market)
    except Exception as e:  # noqa: BLE001
        print(f"[flows] 거래대금 조회 실패: {e}")
        return []

    if df is None or df.empty or "거래대금" not in df.columns:
        print("[flows] 거래대금 데이터 없음")
        return []

    df = df.sort_values("거래대금", ascending=False).head(n)
    out: List[Stock] = []
    for _, r in df.iterrows():
        try:
            out.append(Stock(
                name=str(r["종목명"]),
                ticker="",
                close=float(r["종가"]),
                change_pct=float(r["등락률"]),
                currency="KRW",
                trade_value=float(r["거래대금"]),  # 원
            ))
        except Exception:  # noqa: BLE001
            continue
    return out


def fetch_investor_net_buy(trade_day: dt.date, n: int = 3,
                           market: str = "KOSPI") -> Dict[str, List[Stock]]:
    """외국인·기관 순매수 상위 n개씩.

    반환: {"외국인": [Stock, ...], "기관": [Stock, ...]}
    각 Stock 은 name 과 trade_value(=순매수거래대금, 원)만 채운다.
    """
    try:
        from pykrx import stock
    except Exception as e:  # noqa: BLE001
        print(f"[flows] pykrx 미설치 → 수급 섹션 생략: {e}")
        return {}

    d = _ymd(trade_day)
    result: Dict[str, List[Stock]] = {}
    for label, investor in (("외국인", "외국인"), ("기관", "기관합계")):
        try:
            df = stock.get_market_net_purchases_of_equities(d, d, market, investor)
        except Exception as e:  # noqa: BLE001
            print(f"[flows] {label} 순매수 조회 실패: {e}")
            result[label] = []
            continue

        rows: List[Stock] = []
        if df is not None and not df.empty and "순매수거래대금" in df.columns:
            df = df.sort_values("순매수거래대금", ascending=False).head(n)
            for _, r in df.iterrows():
                try:
                    rows.append(Stock(
                        name=str(r["종목명"]),
                        ticker="",
                        currency="KRW",
                        trade_value=float(r["순매수거래대금"]),  # 원
                    ))
                except Exception:  # noqa: BLE001
                    continue
        result[label] = rows
    return result


if __name__ == "__main__":
    # 스모크 테스트: 최근 영업일 기준으로 실제 데이터가 나오는지 확인
    today = dt.date.today()
    day = today
    for i in range(1, 8):
        cand = today - dt.timedelta(days=i)
        if cand.weekday() < 5:  # 월~금
            day = cand
            break

    print(f"=== 기준일 {day} ===")
    print("\n[거래대금 상위]")
    for s in fetch_trading_value_top(day, 5):
        print(f"- {s.name}: 거래대금 {(s.trade_value or 0) / 1e8:,.0f}억 · {s.change_pct:+.2f}%")

    print("\n[투자자 순매수 상위]")
    nb = fetch_investor_net_buy(day, 3)
    for label, rows in nb.items():
        bits = ", ".join(f"{s.name} +{(s.trade_value or 0) / 1e8:,.0f}억" for s in rows)
        print(f"- {label}: {bits}")
