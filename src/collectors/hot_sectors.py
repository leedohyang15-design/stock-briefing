"""[섹션 2] 실시간 주도 섹터 & 국내외 핵심 종목.

국내(네이버 증권 테마시세 JSON — m.stock.naver.com/api/stocks/theme)를 2단계로 분류한다.
  - 빅 섹션: 거래대금이 큰 '주류' 급등 테마 (반도체·정유 등)
  - 스몰(기타) 종목: 상한가 한 방으로 테마 등락률만 튄 소형주는 개별 종목으로 격리
중복 테마(구성 상위종목 70% 이상 일치)는 하나로 병합한다.

해외는 실시간 트렌딩(노이즈 큼) 대신 '미국 시가총액 상위 종목' 시세를 쓴다.

무료·무키 소스만 사용한다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .. import _ssl_bootstrap  # noqa: F401  (yfinance 요청 전에 SSL 경로 보정)
import yfinance as yf

from . import _naver
from .watchlist import Stock, ThemeGroup  # 포맷터/요약기와 호환되는 모델 재사용

_SCAN_THEMES = 20          # 등락률 상위 몇 개 테마를 훑을지
_MERGE_RATIO = 0.7         # 구성 상위종목 겹침 비율이 이 이상이면 병합
_LIMITUP_PCT = 20.0        # 이 이상 급등은 '상한가성 스파이크'로 보고 기타 종목으로 격리
_MEMBER_TOP = 5            # 병합 판정에 쓰는 테마별 핵심종목 수
_RANK_EMOJI = ["🥇", "🥈", "🥉", "🔥", "🔥", "🔥", "🔥", "🔥"]

# 미국 시가총액 상위 핵심 종목 (수기 관리 — 분기별로 확인)
_US_MEGACAPS = [
    ("엔비디아", "NVDA"), ("애플", "AAPL"), ("마이크로소프트", "MSFT"),
    ("알파벳(구글)", "GOOGL"), ("아마존", "AMZN"), ("메타", "META"),
    ("브로드컴", "AVGO"), ("테슬라", "TSLA"), ("일라이릴리", "LLY"), ("버크셔", "BRK-B"),
]


class _RawTheme:
    def __init__(self, name, headline, stocks):
        self.names = [name]                 # 병합 시 여러 테마명 누적
        self.headline = headline            # 테마 등락률
        self.stocks = stocks                # List[Stock] (전체 구성종목)
        self.memberset = {s.name for s in sorted(
            stocks, key=lambda s: (s.trade_value or 0), reverse=True)[:_MEMBER_TOP]}

    @property
    def display_name(self):
        return "·".join(self.names)

    @property
    def max_value(self):
        return max((s.trade_value or 0) for s in self.stocks) if self.stocks else 0

    def top_by_change(self, n):
        return sorted(self.stocks, key=lambda s: s.change_pct, reverse=True)[:n]


def _parse_theme_stocks(rows: List[Dict[str, Any]]) -> List[Stock]:
    """테마 상세 구성종목 dict → Stock (trade_value 단위: 백만원, 기존과 동일)."""
    stocks: List[Stock] = []
    for r in rows:
        name = str(r.get("stockName", "")).strip()
        price = _naver.num(r.get("closePrice"))            # 현재가
        chg = _naver.num(r.get("fluctuationsRatio"))       # 등락률
        tval = _naver.num(r.get("accumulatedTradingValue"))  # 거래대금(백만원)
        if name and price is not None and chg is not None:
            stocks.append(Stock(name=name, ticker=str(r.get("itemCode", "")), close=price,
                                change_pct=chg, currency="KRW", trade_value=tval))
    return stocks


def _fetch_theme_detail(no: str) -> List[Stock]:
    return _parse_theme_stocks(_naver.fetch_theme_stocks(no))


def _merge_overlaps(themes: List[_RawTheme]) -> List[_RawTheme]:
    """구성 상위종목이 _MERGE_RATIO 이상 겹치는 테마를 하나로 병합."""
    merged: List[_RawTheme] = []
    for th in themes:
        dup = None
        for m in merged:
            inter = len(th.memberset & m.memberset)
            denom = min(len(th.memberset), len(m.memberset)) or 1
            if inter / denom >= _MERGE_RATIO:
                dup = m
                break
        if dup:
            dup.names.append(th.names[0])       # 테마명 합치기 (예: 정유·윤활유)
            dup.memberset |= th.memberset
        else:
            merged.append(th)
    return merged


def fetch_trending(themes_n: int = 3, per_sector: int = 2,
                   movers_n: int = 6) -> Tuple[List[ThemeGroup], List[Stock]]:
    """실시간 핫테마를 (트렌딩 테마 목록, 기타 강세 종목 목록)으로 반환.

    - 트렌딩 테마: 등락률 상위 테마(중복 병합) 상위 themes_n 개.
      각 테마의 대표주는 상한가성 스파이크를 뺀 '거래대금 상위' 종목으로 표시.
    - 기타 강세 종목: +{_LIMITUP_PCT}% 이상 급등한 소형주(상한가성)를 개별 종목으로 격리.
    """
    raws: List[_RawTheme] = []
    try:
        for no, name, chg in _naver.fetch_theme_list():
            try:
                stocks = _fetch_theme_detail(no)
            except Exception as e:  # noqa: BLE001
                print(f"[hot_sectors] '{name}' 상세 실패: {e}")
                continue
            if stocks:
                raws.append(_RawTheme(name, round(chg, 2), stocks))
            if len(raws) >= _SCAN_THEMES:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[hot_sectors] 테마 목록 조회 실패: {e}")
        return [], []

    raws = _merge_overlaps(raws)
    raws.sort(key=lambda t: t.headline, reverse=True)

    # 트렌딩 테마: 대표주는 상한가성 종목을 제외한 '거래대금 상위' 로 (없으면 등락률 상위)
    themes: List[ThemeGroup] = []
    for i, t in enumerate(raws[:themes_n]):
        core = [s for s in t.stocks if s.change_pct < _LIMITUP_PCT] or t.stocks
        core.sort(key=lambda s: (s.trade_value or 0), reverse=True)
        emoji = _RANK_EMOJI[i] if i < len(_RANK_EMOJI) else "🔥"
        themes.append(ThemeGroup(
            name=t.display_name, emoji=emoji, stocks=core[:per_sector],
            headline_pct=t.headline, trade_value=t.max_value))

    # 기타 강세 종목: 상한가성 소형주 격리 (전체 테마에서 수집, 이름 중복 제거)
    seen, movers = set(), []
    spikes = [s for t in raws for s in t.stocks if s.change_pct >= _LIMITUP_PCT]
    for s in sorted(spikes, key=lambda s: s.change_pct, reverse=True):
        if s.name in seen:
            continue
        seen.add(s.name)
        movers.append(s)
        if len(movers) >= movers_n:
            break

    return themes, movers


# ── 해외: 미국 시가총액 상위 핵심 종목 ────────────────────
def fetch_us_megacaps(limit: int = 10) -> List[Stock]:
    """미국 시총 상위 종목의 전일 대비 등락률 (트렌딩보다 안정적)."""
    out: List[Stock] = []
    for name, sym in _US_MEGACAPS[:limit]:
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d")
            closes = hist["Close"].dropna() if hist is not None else []
            if len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                chg = round((last - prev) / prev * 100, 2) if prev else 0.0
                out.append(Stock(name=f"{name}({sym})", ticker=sym, close=round(last, 2),
                                 change_pct=chg, currency="USD"))
        except Exception:  # noqa: BLE001
            continue
    return out


if __name__ == "__main__":
    themes, movers = fetch_trending()
    print("=== ⚡ 트렌딩 스몰 섹션 ===")
    for g in themes:
        members = ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        print(f"{g.emoji} {g.name} ({g.label}) — {members}")
    print("\n=== 💡 기타 당일 강세 종목 ===")
    for s in movers:
        print(f"{s.name} {s.change_pct:+.2f}% (거래대금 {s.trade_value or 0:,.0f}백만)")
    print("\n=== 🌎 미국 시총 상위 ===")
    for s in fetch_us_megacaps():
        print(f"{s.name} {s.change_pct:+.2f}% (${s.close})")
