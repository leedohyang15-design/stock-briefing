"""[섹션 2 보조] 기타 주목 테마 (동적 슬롯).

네이버 증권 '테마별 시세'(m.stock.naver.com/api/stocks/theme JSON)에서 당일 급등 테마를 가져오되,
내가 지정한 고정 테마(watchlist.yaml)에 해당하지 않는 '낯선 테마'가
기준치(+5%) 이상 급등한 경우에만 골라낸다.
→ 초전도체·맥신·K-푸드·정치테마 등 갑자기 튀는 단기 테마를 놓치지 않기 위함.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from . import _naver

# 고정 테마(watchlist.yaml)와 겹치는 테마를 걸러내기 위한 키워드.
# 네이버 테마명에 아래 단어가 포함되면 '이미 다루는 테마'로 보고 제외한다.
_COVERED_KEYWORDS = (
    # 고정 테마와 겹치는 키워드
    "반도체", "HBM", "메모리", "AI", "인공지능", "우주", "항공", "방산", "국방",
    "2차전지", "전지", "배터리", "바이오", "제약", "신약", "원자력", "원전", "전력",
    "로봇", "자율주행", "모빌리티", "자동차", "전기차", "가상자산", "비트코인", "코인",
    "STO", "토큰증권", "핀테크",
    # '새 테마'가 아닌 일반 대형주·섹터 묶음 (노이즈 제거)
    "대표주", "삼성전자", "하이닉스", "증권", "지주", "은행", "보험", "우선주",
    "코스피", "대형주",
)
_MIN_PCT = 5.0  # 이 값 이상 급등한 낯선 테마만 노출


def _matches_watchlist(leaders: List[str], exclude_stocks: Set[str]) -> bool:
    """테마 주도주가 내 워치리스트 종목과 겹치면 True (이미 다루는 종목)."""
    for lead in leaders:
        for name in exclude_stocks:
            if lead and name and (lead in name or name in lead):
                return True
    return False


@dataclass
class HotTheme:
    name: str
    change_pct: float
    leaders: List[str] = field(default_factory=list)
    cause: Optional[str] = None  # summarizer 가 채우는 급등 원인 1줄


def _is_covered(name: str) -> bool:
    return any(k in name for k in _COVERED_KEYWORDS)


def fetch_hot_extra_themes(top_n: int = 2, exclude_stocks: Optional[Set[str]] = None) -> List[HotTheme]:
    """고정 테마에 없는 낯선 급등 테마(+5% 이상) 상위 top_n 개.

    exclude_stocks: 워치리스트 종목명 집합 (주도주가 겹치는 테마는 제외).
    """
    exclude_stocks = exclude_stocks or set()
    hot: List[HotTheme] = []
    try:
        for no, name, change in _naver.fetch_theme_list():
            if change < _MIN_PCT:      # 등락률 내림차순이므로 여기서 중단 가능
                break
            if _is_covered(name):      # 고정 테마·일반 섹터와 겹치면 건너뜀
                continue
            # 목록 JSON 엔 주도주가 없어 상세(등락률순 구성종목)에서 상위 2개를 쓴다
            leaders = [str(st.get("stockName", "")).strip()
                       for st in _naver.fetch_theme_stocks(no)][:2]
            leaders = [x for x in leaders if x]
            if _matches_watchlist(leaders, exclude_stocks):  # 워치리스트 종목이 주도주면 제외
                continue
            hot.append(HotTheme(name=name, change_pct=round(change, 2), leaders=leaders))
            if len(hot) >= top_n:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[themes] 기타 테마 조회 실패: {e}")
    return hot

if __name__ == "__main__":
    themes = fetch_hot_extra_themes()
    if themes:
        for t in themes:
            print(f"[{t.name}] +{t.change_pct:.2f}% 주도주: {', '.join(t.leaders) or '-'}")
    else:
        print(f"오늘 +{_MIN_PCT}% 이상 급등한 낯선 테마 없음")
