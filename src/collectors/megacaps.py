"""[핵심 대형주] 시총 상위 벨웨더 종목의 전일 등락률 (yfinance).

config/megacaps.yaml 의 고정 종목(삼성전자·SK하이닉스·TSMC·엔비디아·구글 등)을
반도체 밸류체인 그룹(메모리·파운드리 → 설계·플랫폼 → 빅테크 수요처)별로 묶어
전일 대비 등락률을 가져온다.

'주도 섹터'(sectors.py)는 그날 거래대금 상위로 종목이 매일 바뀌므로 삼성전자·엔비디아
라도 그날 순위에서 밀리면 아예 안 뜰 수 있다. 이 패널은 시총 상위 핵심주를 '항상 고정'
으로 보여줘 같은 종목의 흐름을 매일 추적하도록 한다. watchlist 의 시세 로직(_fill_quote)
을 그대로 재사용해 formatter 와 호환한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml

from .watchlist import Stock, _fill_quote

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "megacaps.yaml",
)


@dataclass
class MegaGroup:
    """밸류체인 그룹(예: 메모리·파운드리) + 소속 대형주 시세."""
    name: str
    stocks: List[Stock] = field(default_factory=list)


def fetch_megacaps() -> List[MegaGroup]:
    """megacaps.yaml 의 고정 대형주를 그룹별로 시세와 함께 반환. 실패 종목/빈 그룹은 건너뛴다.

    통화(currency: KRW/USD)는 종목별로 자동 설정되며(국내/미장 혼재 가능),
    포맷터는 그룹명 라벨로 묶어 종목별 통화에 맞게 가격을 표기한다.
    """
    if not os.path.exists(_CONFIG_PATH):
        print(f"[megacaps] megacaps.yaml 없음: {_CONFIG_PATH}")
        return []
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    groups: List[MegaGroup] = []
    for grp in data.get("groups", []) or []:
        g = MegaGroup(name=grp.get("name", "기타"))
        for s in grp.get("stocks", []) or []:
            stock = Stock(name=s["name"], ticker=s["ticker"])
            _fill_quote(stock)  # yfinance 전일 대비 등락 채움 (currency 자동 설정)
            if stock.ok:
                g.stocks.append(stock)
        if g.stocks:
            groups.append(g)
    return groups


if __name__ == "__main__":
    # 스모크 테스트 (yfinance 접근 가능한 환경에서만 데이터가 나온다)
    print("[핵심 대형주]")
    for g in fetch_megacaps():
        body = ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        print(f"· {g.name}: {body}")
