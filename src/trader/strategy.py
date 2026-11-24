"""전략 계산 (순수 함수, 테스트 대상).

출처
- ORB·Stocks in Play·ATR 손절·위험 고정 비중: Zarattini, Barbon, Aziz (Swiss Finance Institute RP 24-98)
- 주문 불균형(tick rule): Chordia & Subrahmanyam (JFE 2004)
- 지수 장 초반 모멘텀: Gao, Han, Li, Zhou (JFE 2018)
- 정적 VI: KRX 제도 / 안일찬·라성채
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .models import Bar, Trade
from .ticks import tick_size


def hhmm_add(hhmm: str, minutes: int) -> str:
    t = dt.datetime.strptime(hhmm, "%H%M") + dt.timedelta(minutes=minutes)
    return t.strftime("%H%M")


def atr(daily: Sequence[Bar], n: int = 14) -> Optional[float]:
    """단순 평균 True Range (최근 n일)."""
    if len(daily) < 2:
        return None
    trs = []
    for prev, cur in zip(daily[:-1], daily[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    trs = trs[-n:]
    return sum(trs) / len(trs) if trs else None


def avg_volume(daily: Sequence[Bar], n: int = 14) -> float:
    xs = [b.volume for b in daily[-n:]]
    return sum(xs) / len(xs) if xs else 0.0


def avg_value(daily: Sequence[Bar], n: int = 14) -> float:
    xs = [b.volume * b.close for b in daily[-n:]]
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class OpeningRange:
    high: float
    low: float
    open: float
    close: float
    volume: float
    end: str  # 범위가 끝나는 시각 HHMM (이 시각부터 진입 가능)

    @property
    def bullish(self) -> bool:
        return self.close > self.open


SESSION_OPEN = "0900"   # market.activate() 가 바꾼다 (국장 09:00, 미장 09:30 뉴욕시각)


def opening_range(bars: Sequence[Bar], minutes: int, start: Optional[str] = None) -> Optional[OpeningRange]:
    start = start or SESSION_OPEN
    end = hhmm_add(start, minutes)
    rng = [b for b in bars if start <= b.time < end]
    if not rng:
        return None
    return OpeningRange(high=max(b.high for b in rng), low=min(b.low for b in rng), open=rng[0].open,
                        close=rng[-1].close, volume=sum(b.volume for b in rng), end=end)


def relative_volume(or_volume: float, daily_avg_volume: float, open_share: float) -> float:
    """시가범위 거래량 / (14일 평균 일거래량 × 시가범위 평균 비중) ≈ 논문의 상대거래량."""
    expected = daily_avg_volume * open_share
    return or_volume / expected if expected > 0 else 0.0


def orb_long_trigger(price: float, rng: OpeningRange, require_bullish: bool = True) -> bool:
    if require_bullish and not rng.bullish:
        return False
    return price > rng.high


def stop_price(entry: float, atr_value: float, mult: float) -> float:
    return entry - atr_value * mult


def stop_for(entry: float, atr_value: float, cfg: dict, cost_pct: float) -> float:
    """손절가 = 진입가 - max(ATR×배수(논문), 최소 호가 수, 왕복 비용×배수).

    논문 그대로(ATR×0.1)면 한국 1만원대 종목은 손절폭이 호가 몇 칸·비용 수준이라 잡음에 털린다.
    그래서 호가·비용 기준 하한을 둔다 (주간 복기 레버 min_stop_ticks 로 검증).
    """
    dist = max(atr_value * cfg.get("stop_atr_mult", 0.1),
               tick_size(entry) * cfg.get("min_stop_ticks", 0),
               entry * cost_pct / 100 * cfg.get("min_stop_cost_mult", 0))
    return entry - dist


def open_volume_avg(days: Sequence[Sequence[Bar]], minutes: int) -> Tuple[float, int]:
    """과거 각 거래일 시가범위 구간(09:00~+minutes) 거래량의 평균과 일수. 실측 상대거래량의 분모."""
    vols = []
    for bars in days:
        r = opening_range(bars, minutes)
        if r and r.volume > 0:
            vols.append(r.volume)
    return (sum(vols) / len(vols) if vols else 0.0), len(vols)


def position_size(equity: float, risk_pct: float, entry: float, stop: float,
                  max_order_krw: float, cash: float) -> int:
    """손절 시 손실이 계좌의 risk_pct% 가 되는 수량, 단 1회 주문 한도·예수금 이내."""
    per_share_risk = entry - stop
    if entry <= 0 or per_share_risk <= 0:
        return 0
    by_risk = math.floor(equity * risk_pct / 100 / per_share_risk)
    by_cap = math.floor(max_order_krw / entry)
    by_cash = math.floor(cash / entry)
    return max(0, min(by_risk, by_cap, by_cash))


def order_imbalance(trades: Sequence[Trade]) -> Tuple[float, float, float]:
    """tick rule 로 매수/매도 주도 체결량 분류. trades 는 최신이 앞.

    가격이 직전 체결보다 오르면 매수 주도, 내리면 매도 주도, 같으면 직전 분류를 따른다.
    반환: (매수 주도량, 매도 주도량, 불균형 = (매수-매도)/(매수+매도))
    """
    seq = list(reversed(trades))
    buy = sell = 0.0
    side = 0
    for prev, cur in zip(seq[:-1], seq[1:]):
        if cur.price > prev.price:
            side = 1
        elif cur.price < prev.price:
            side = -1
        if side > 0:
            buy += cur.qty
        elif side < 0:
            sell += cur.qty
    tot = buy + sell
    return buy, sell, ((buy - sell) / tot if tot else 0.0)


def static_vi_upper(reference: float, pct: float) -> float:
    return reference * (1 + pct / 100)


def vi_room_pct(price: float, reference: float, pct: float) -> float:
    """현재가에서 정적 VI 상단 발동가까지 남은 % (음수면 이미 넘음)."""
    upper = static_vi_upper(reference, pct)
    return (upper - price) / price * 100 if price else 0.0
