"""가짜 한국투자증권·시계·LLM (테스트와 데모용). 실제 주문·네트워크 없음."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from src.trader.models import KST, Bar, Quote, Trade


def today() -> str:
    return dt.datetime.now(KST).strftime("%Y%m%d")


def trading_days(n: int) -> List[str]:
    d = dt.datetime.now(KST).date()
    out = []
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
    return sorted(out)


def minute_grid(start="0900", end="1530"):
    t = dt.datetime.strptime(start, "%H%M")
    e = dt.datetime.strptime(end, "%H%M")
    while t < e:
        yield t.strftime("%H%M")
        t += dt.timedelta(minutes=1)


class FakeClock:
    def __init__(self, hhmm: str):
        d = dt.datetime.now(KST)
        self.t = d.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0, microsecond=0)

    def now(self):
        return self.t

    def sleep(self, sec: float):
        self.t += dt.timedelta(seconds=max(sec, 1.0))


class FakeLLM:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = 0

    @property
    def available(self):
        return bool(self.replies)

    def json(self, system, prompt, max_tokens=800):
        self.calls += 1
        return self.replies.pop(0) if self.replies else None


class FakeKIS:
    """paths: {code: (name, price_fn(hhmm))} 또는 price_fn 하나 (code=111111).
    일봉 ATR≈600(6%), 평균 거래량 100만주, 시가범위 양봉 10000→10100."""

    def __init__(self, clock: FakeClock, paths, code="111111", name="샘플반도체"):
        self.clock = clock
        self.paths = paths if isinstance(paths, dict) else {code: (name, paths)}
        self.calls: Dict[str, int] = {}

    def _c(self, k):
        self.calls[k] = self.calls.get(k, 0) + 1

    def _p(self, code, hhmm):
        return self.paths[code][1](hhmm)

    def quote(self, code):
        self._c("quote")
        p = self._p(code, self.clock.now().strftime("%H%M"))
        return Quote(code=code, name=self.paths[code][0], price=p, open=10000, high=max(p, 10150), low=9950,
                     prev_close=10000, change_pct=(p / 10000 - 1) * 100, volume=500000, upper_limit=13000)

    def index_change(self, market="KOSPI"):
        return 2500.0, 0.5

    def daily_bars(self, code, days=30):
        return [Bar(time=d, date=d, open=10000, high=10300, low=9700, close=10000, volume=1_000_000)
                for d in trading_days(days)]

    def minute_bars_today(self, code, until=None):
        until = (until or self.clock.now().strftime("%H%M%S"))[:4]
        out, prev = [], None
        for i, t in enumerate(minute_grid("0900", "1530")):
            if t > until:
                break
            if t < "0905":
                o = 10000 + i * 20
                out.append(Bar(time=t, date=today(), open=o, high=o + 70 if i == 4 else o + 30, low=o - 10,
                               close=o + 20, volume=40_000))
                prev = o + 20
            else:
                p = self._p(code, t)
                o = prev if prev else p
                out.append(Bar(time=t, date=today(), open=o, high=max(o, p) + 5, low=min(o, p) - 5, close=p,
                               volume=10_000 + (i * 7919) % 9000))
                prev = p
        return out

    def minute_bars_recent(self, code):
        return self.minute_bars_today(code)[-30:]

    def minute_bars_past(self, code, date, until="153000"):
        self._c("past")
        out, p = [], 10000.0
        for t in minute_grid():
            if t > until[:4]:
                break
            nxt = p * 1.0001
            out.append(Bar(time=t, date=date, open=p, high=nxt, low=p * 0.9999, close=nxt, volume=5000))
            p = nxt
        return out

    def news_titles(self, code="", limit=20):
        return []

    def recent_trades(self, code):
        return [Trade(time="", price=10300 - i * 10, qty=100) for i in range(30)]  # 최신이 앞, 상승 중

    def volume_rank(self, kind="increase"):
        rows = [{"code": c, "name": n, "price": 10100, "change_pct": 1.0, "volume": 1, "avg_volume": 1}
                for c, (n, _) in self.paths.items()]
        return rows + [{"code": "999999", "name": "KODEX 레버리지", "price": 10000, "change_pct": 1.0, "volume": 1,
                        "avg_volume": 1}]
