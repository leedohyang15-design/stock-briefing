"""한국투자증권 해외주식(미국) 시세 어댑터 — 국내용 KISClient 와 같은 메서드 이름으로 감싼다.

모의투자(가상 주문) 전용이라 주문 API 는 쓰지 않는다. 시세·분봉·일봉·순위·체결·뉴스만 조회한다.
API 형식은 한국투자증권 공식 샘플(koreainvestment/open-trading-api, examples_llm/overseas_stock)을 따랐다.
시간은 모두 뉴욕 현지 시각 (분봉 xhms, 일자 xymd).

직접 확인:  python -m src.trader.kis_overseas --check
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from .kis_client import KISClient, KISError, _f
from .models import Bar, Quote, Trade, now_kst

EXCHANGES = ("NAS", "NYS", "AMS")
INDEX_SYMBOLS = {"SPY": "AMS", "QQQ": "NAS"}


class KISOverseas:
    def __init__(self, kis: KISClient):
        self.k = kis
        self.excd: Dict[str, str] = dict(INDEX_SYMBOLS)   # 종목 → 거래소 코드
        self.names: Dict[str, str] = {}

    def _call(self, path: str, tr: str, params: Dict[str, str]) -> Dict[str, Any]:
        return self.k._call("GET", path, tr, params)

    def _ok(self, res) -> bool:
        return str(res.get("rt_cd")) == "0"

    # ── 시세 ──
    def _price(self, sym: str, excd: str) -> Dict[str, Any]:
        res = self._call("/uapi/overseas-price/v1/quotations/price", "HHDFS00000300",
                         {"AUTH": "", "EXCD": excd, "SYMB": sym})
        o = res.get("output") or {}
        return o if self._ok(res) and _f(o.get("last")) > 0 else {}

    def quote(self, sym: str) -> Quote:
        tried = [self.excd[sym]] if sym in self.excd else []
        for ex in tried + [e for e in EXCHANGES if e not in tried]:
            o = self._price(sym, ex)
            if o:
                self.excd[sym] = ex
                last = _f(o.get("last"))
                return Quote(code=sym, name=self.names.get(sym, sym), price=last, open=last, high=last, low=last,
                             prev_close=_f(o.get("base")), change_pct=_f(o.get("rate")), volume=_f(o.get("tvol")))
        raise KISError(f"해외 현재가 실패 {sym}")

    def index_change(self, sym: str = "SPY") -> Tuple[float, float]:
        q = self.quote(sym)
        return q.price, q.change_pct

    @staticmethod
    def _bars(rows, date_key="xymd", time_key="xhms") -> List[Bar]:
        out = []
        for r in rows or []:
            if not r.get(time_key):
                continue
            out.append(Bar(time=str(r[time_key])[:4], date=str(r.get(date_key, "")), open=_f(r.get("open")),
                           high=_f(r.get("high")), low=_f(r.get("low")), close=_f(r.get("last")),
                           volume=_f(r.get("evol"))))
        return out

    def _chart(self, sym: str, keyb: str = "", pinc: str = "0", nrec: str = "120") -> List[Bar]:
        res = self._call("/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice", "HHDFS76950200", {
            "AUTH": "", "EXCD": self.excd.get(sym, "NAS"), "SYMB": sym, "NMIN": "1", "PINC": pinc,
            "NEXT": "1" if keyb else "", "NREC": nrec, "FILL": "", "KEYB": keyb})
        return self._bars(res.get("output2")) if self._ok(res) else []

    def _paged(self, sym: str, date: str, open_: str, until: str, pinc: str) -> List[Bar]:
        bars: Dict[str, Bar] = {}
        keyb = ""
        for _ in range(5):                                   # 120개 × 5 = 600분 (정규장 390분)
            rows = self._chart(sym, keyb, pinc)
            day = [b for b in rows if b.date == date and open_ <= b.time <= until[:4]]
            for b in day:
                bars[b.time] = b
            if not rows:
                break
            earliest = min(rows, key=lambda b: (b.date, b.time))
            if (earliest.date, earliest.time) <= (date, open_):
                break
            t = dt.datetime.strptime(earliest.date + earliest.time, "%Y%m%d%H%M") - dt.timedelta(minutes=1)
            keyb, pinc = t.strftime("%Y%m%d%H%M00"), "1"
        return [bars[k] for k in sorted(bars)]

    def minute_bars_today(self, sym: str, until: Optional[str] = None) -> List[Bar]:
        from . import strategy as st
        until = until or now_kst().strftime("%H%M%S")
        return self._paged(sym, now_kst().strftime("%Y%m%d"), st.SESSION_OPEN, until, "0")

    def minute_bars_recent(self, sym: str) -> List[Bar]:
        from . import strategy as st
        today = now_kst().strftime("%Y%m%d")
        return sorted([b for b in self._chart(sym, nrec="30") if b.date == today and b.time >= st.SESSION_OPEN],
                      key=lambda b: b.time)

    def minute_bars_past(self, sym: str, date: str, until: str = "160000") -> List[Bar]:
        """과거 분봉 (전일 포함 조회로 가능한 범위만. 못 받으면 빈 목록 → 쌓인 데이터 사용)."""
        from . import strategy as st
        return self._paged(sym, date, st.SESSION_OPEN, until, "1") if date else []

    def daily_bars(self, sym: str, days: int = 30) -> List[Bar]:
        res = self._call("/uapi/overseas-price/v1/quotations/dailyprice", "HHDFS76240000", {
            "AUTH": "", "EXCD": self.excd.get(sym, "NAS"), "SYMB": sym, "GUBN": "0", "BYMD": "", "MODP": "1"})
        if not self._ok(res):
            raise KISError(f"해외 일봉 실패 {sym}: {res.get('msg1')}")
        out = [Bar(time=r["xymd"], date=r["xymd"], open=_f(r.get("open")), high=_f(r.get("high")),
                   low=_f(r.get("low")), close=_f(r.get("clos")), volume=_f(r.get("tvol")))
               for r in res.get("output2") or [] if r.get("xymd")]
        out.sort(key=lambda b: b.time)
        today = now_kst().strftime("%Y%m%d")
        return [b for b in out if b.date < today][-days:]

    def recent_trades(self, sym: str) -> List[Trade]:
        res = self._call("/uapi/overseas-price/v1/quotations/inquire-ccnl", "HHDFS76200300", {
            "AUTH": "", "EXCD": self.excd.get(sym, "NAS"), "SYMB": sym, "TDAY": "1", "KEYB": ""})
        rows = res.get("output1") or res.get("output") or []
        return [Trade(time=str(r.get("khms", "")), price=_f(r.get("last")), qty=_f(r.get("evol")))
                for r in rows if isinstance(r, dict)] if self._ok(res) else []

    def volume_rank(self, kind: str = "increase") -> List[Dict[str, Any]]:
        """increase: 거래량 급증(최근 10분 대비), value/volume: 거래량 순위. 나스닥·뉴욕 합산."""
        out = []
        for ex in ("NAS", "NYS"):
            if kind == "increase":
                res = self._call("/uapi/overseas-stock/v1/ranking/volume-surge", "HHDFS76270000",
                                 {"AUTH": "", "EXCD": ex, "MINX": "4", "VOL_RANG": "3", "KEYB": ""})
            else:
                res = self._call("/uapi/overseas-stock/v1/ranking/trade-vol", "HHDFS76310010",
                                 {"AUTH": "", "EXCD": ex, "NDAY": "0", "PRC1": "5", "PRC2": "", "VOL_RANG": "4",
                                  "KEYB": ""})
            if not self._ok(res):
                continue
            for r in res.get("output2") or []:
                sym = str(r.get("symb", "")).strip()
                if not sym:
                    continue
                self.excd[sym] = str(r.get("excd") or ex)
                self.names[sym] = r.get("knam") or r.get("name") or sym
                last = _f(r.get("last"))
                out.append({"code": sym, "name": self.names[sym], "price": last, "change_pct": _f(r.get("rate")),
                            "volume": _f(r.get("tvol")), "avg_volume": _f(r.get("n_tvol")),
                            "value_krw": _f(r.get("tamt")) or last * _f(r.get("tvol"))})
        return out

    def news_titles(self, sym: str = "", limit: int = 20) -> List[Dict[str, str]]:
        """해외뉴스종합(제목). 조회 실패 시 KISError (뉴스 확인 에이전트는 거부로 처리)."""
        res = self._call("/uapi/overseas-price/v1/quotations/news-title", "HHPSTH60100C1", {
            "INFO_GB": "", "CLASS_CD": "", "NATION_CD": "US" if sym else "", "EXCHANGE_CD": "", "SYMB": sym,
            "DATA_DT": "", "DATA_TM": "", "CTS": ""})
        if not self._ok(res):
            raise KISError(f"해외 뉴스 조회 실패 {sym}: {res.get('msg1')}")
        rows = res.get("outblock1") or res.get("output") or res.get("output1") or []
        out = [{"title": str(r.get("title", "")).strip(), "date": str(r.get("data_dt", "")),
                "time": str(r.get("data_tm", "")), "source": str(r.get("source", ""))}
               for r in rows if isinstance(r, dict) and r.get("title")]
        return out[:limit]

    # 모의투자 전용: 계좌 조회 없음
    def buyable_cash(self, *a, **k):
        return None


def _check() -> None:
    from . import market
    from .settings import Settings
    market.activate("us")
    o = KISOverseas(KISClient(Settings.load(market.US.config_path)))
    print(f"[뉴욕 시각] {now_kst():%Y-%m-%d %H:%M}")
    q = o.quote("AAPL")
    print(f"[현재가] AAPL ${q.price:,.2f} ({q.change_pct:+.2f}%)  거래소 {o.excd['AAPL']}")
    print(f"[지수 ETF] SPY {o.index_change('SPY')}  QQQ {o.index_change('QQQ')}")
    d = o.daily_bars("AAPL", 20)
    print(f"[일봉] {len(d)}개" + (f" · 마지막 {d[-1].date} 종가 ${d[-1].close:,.2f}" if d else ""))
    b = o.minute_bars_recent("AAPL")
    print(f"[분봉] 오늘 최근 {len(b)}개 (장 시간 전이면 0개가 정상)")
    r = o.volume_rank("value")
    print(f"[거래량 순위] {len(r)}종목" + (f" · 예: {r[0]['code']} {r[0]['name']}" if r else " (0이면 장 시간 외일 수 있음)"))
    try:
        n = o.news_titles("AAPL", 3)
        print(f"[해외 뉴스] {len(n)}건" + (f" · {n[0]['title'][:40]}" if n else ""))
    except KISError as e:
        print(f"[해외 뉴스] 실패: {e} → 화면을 캡처해 보내주세요")
    t = o.recent_trades("AAPL")
    print(f"[체결] {len(t)}건 (0이면 매수세 필터는 '참고'로만 동작)")
    print("미장 시세 연결 확인 끝.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    if ap.parse_args().check:
        _check()
