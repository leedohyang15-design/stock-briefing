"""[핵심 대형주] 시총 상위 벨웨더 종목의 전일 등락률 (yfinance).

config/megacaps.yaml 의 고정 종목(삼성전자·SK하이닉스·엔비디아·구글·테슬라 등)의
전일 대비 등락률을 가져온다.

'주도 섹터'(sectors.py)는 그날 거래대금 상위로 종목이 매일 바뀌므로 삼성전자·엔비디아
라도 그날 순위에서 밀리면 아예 안 뜰 수 있다. 이 패널은 시총 상위 핵심주를 '항상 고정'
으로 보여줘 같은 종목의 흐름을 매일 추적하도록 한다. watchlist 의 시세 로직(_fill_quote)
을 그대로 재사용해 formatter 와 호환한다.
"""
from __future__ import annotations

import os
from typing import List

import yaml

from .watchlist import Stock, _fill_quote

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "megacaps.yaml",
)


def fetch_megacaps() -> List[Stock]:
    """megacaps.yaml 의 고정 대형주 시세를 yaml 순서대로 반환. 실패 종목은 건너뛴다.

    통화(currency: KRW/USD)로 국내/미국이 구분되며, 포맷터가 이를 기준으로 묶는다.
    """
    if not os.path.exists(_CONFIG_PATH):
        print(f"[megacaps] megacaps.yaml 없음: {_CONFIG_PATH}")
        return []
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    out: List[Stock] = []
    for s in data.get("stocks", []) or []:
        stock = Stock(name=s["name"], ticker=s["ticker"])
        _fill_quote(stock)  # yfinance 전일 대비 등락 채움 (currency 자동 설정)
        if stock.ok:
            out.append(stock)
    return out


if __name__ == "__main__":
    # 스모크 테스트 (yfinance 접근 가능한 환경에서만 데이터가 나온다)
    print("[핵심 대형주]")
    for s in fetch_megacaps():
        print(f"- {s.name}({s.ticker}): {s.close} {s.change_pct:+.2f}% [{s.currency}]")
