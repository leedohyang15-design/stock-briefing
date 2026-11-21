"""한국투자증권 Open API (REST) 얇은 클라이언트.

- 토큰은 data/kis_token_<env>.json 에 캐시 (발급은 1분 1회 제한, 유효 24시간)
- 호출 속도 제한기(초당 N건) 내장. 초과 오류(EGW00201)는 잠깐 쉬고 재시도
- 주문 TR ID 는 config/trader.yaml 의 kis.tr 에서 읽고, 신규 TR 이 거부되면 구형으로 1회 재시도

직접 확인:  python -m src.trader.kis_client --check
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .models import Bar, OrderResult, Position, Quote, Trade, now_kst
from .settings import DATA_DIR, Settings

BASE = {
    "real": "https://openapi.koreainvestment.com:9443",
    "mock": "https://openapivts.koreainvestment.com:29443",
}
INDEX_CODES = {"KOSPI": "0001", "KOSDAQ": "1001"}


class KISError(RuntimeError):
    pass


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


class _RateLimiter:
    def __init__(self, per_sec: float):
        self.gap = 1.0 / max(per_sec, 0.1)
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self) -> None:
        with self.lock:
            delay = self.gap - (time.monotonic() - self.last)
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


class KISClient:
    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self.s = settings
        sec = settings.secrets
        if not sec.has_kis:
            raise KISError("KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT 가 .env 에 없습니다")
        self.env = sec.kis_env if sec.kis_env in BASE else "real"
        self.base = BASE[self.env]
        self.app_key, self.app_secret = sec.kis_app_key, sec.kis_app_secret
        self.cano, self.acnt = sec.account_parts
        rate = settings.kis.get(f"rate_per_sec_{self.env}", 15 if self.env == "real" else 2)
        self.rl = _RateLimiter(rate)
        self.http = session or requests.Session()
        self.tr = settings.kis.get("tr", {}).get(self.env, {})
        self.tr_legacy = settings.kis.get("tr", {}).get(f"legacy_{self.env}", {})
        self._token: Optional[str] = None
        self._token_path = DATA_DIR / f"kis_token_{self.env}.json"

    # ── 인증 ─────────────────────────────────────────
    def token(self) -> str:
        if self._token:
            return self._token
        try:
            cached = json.loads(self._token_path.read_text(encoding="utf-8"))
            exp = dt.datetime.fromisoformat(cached["expires"])
            if exp - dt.timedelta(minutes=30) > dt.datetime.now() and cached.get("app_key") == self.app_key[:6]:
                self._token = cached["token"]
                return self._token
        except Exception:  # noqa: BLE001
            pass
        r = self.http.post(f"{self.base}/oauth2/tokenP", json={
            "grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret,
        }, timeout=10)
        body = r.json()
        if "access_token" not in body:
            raise KISError(f"토큰 발급 실패: {body}")
        self._token = body["access_token"]
        expires = body.get("access_token_token_expired") or (
            dt.datetime.now() + dt.timedelta(hours=23)).strftime("%Y-%m-%d %H:%M:%S")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps({
            "token": self._token, "expires": expires.replace(" ", "T"), "app_key": self.app_key[:6],
        }), encoding="utf-8")
        return self._token

    def _headers(self, tr_id: str) -> Dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": self.app_key, "appsecret": self.app_secret,
            "tr_id": tr_id, "custtype": "P",
        }

    def _call(self, method: str, path: str, tr_id: str, params: Optional[Dict] = None,
              body: Optional[Dict] = None, retries: int = 3) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        last: Dict[str, Any] = {}
        for attempt in range(retries):
            self.rl.wait()
            try:
                if method == "GET":
                    r = self.http.get(url, headers=self._headers(tr_id), params=params, timeout=10)
                else:
                    r = self.http.post(url, headers=self._headers(tr_id), json=body, timeout=10)
                last = r.json()
            except Exception as e:  # noqa: BLE001
                last = {"rt_cd": "-1", "msg1": str(e)}
                time.sleep(0.5 * (attempt + 1))
                continue
            if last.get("msg_cd") == "EGW00201":  # 초당 거래건수 초과
                time.sleep(1.0)
                continue
            if last.get("msg_cd") in ("EGW00123", "EGW00121"):  # 토큰 만료/무효
                self._token = None
                self._token_path.unlink(missing_ok=True)
                continue
            return last
        return last

    @staticmethod
    def _ok(res: Dict[str, Any]) -> bool:
        return str(res.get("rt_cd")) == "0"

    # ── 시세 ─────────────────────────────────────────
    def quote(self, code: str) -> Quote:
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                         {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        if not self._ok(res):
            raise KISError(f"현재가 실패 {code}: {res.get('msg1')}")
        o = res["output"]
        price = _f(o.get("stck_prpr"))
        prev = price - _f(o.get("prdy_vrss"))
        return Quote(
            code=code, name=o.get("hts_kor_isnm", code), price=price, open=_f(o.get("stck_oprc")),
            high=_f(o.get("stck_hgpr")), low=_f(o.get("stck_lwpr")), prev_close=prev,
            change_pct=_f(o.get("prdy_ctrt")), volume=_f(o.get("acml_vol")),
            upper_limit=_f(o.get("stck_mxpr")),
            vi_active=str(o.get("vi_cls_code", "N")).strip() not in ("", "N", "0"),
        )

    def index_change(self, market: str = "KOSPI") -> Tuple[float, float]:
        """(현재 지수, 전일 대비 %)."""
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-index-price", "FHPUP02100000",
                         {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": INDEX_CODES[market]})
        if not self._ok(res):
            raise KISError(f"지수 실패 {market}: {res.get('msg1')}")
        o = res["output"]
        return _f(o.get("bstp_nmix_prpr")), _f(o.get("bstp_nmix_prdy_ctrt"))

    @staticmethod
    def _bars_from(rows: List[Dict], date_key="stck_bsop_date", time_key="stck_cntg_hour") -> List[Bar]:
        out = []
        for r in rows or []:
            if not r.get(time_key):
                continue
            out.append(Bar(time=r[time_key][:4], date=r.get(date_key, ""), open=_f(r.get("stck_oprc")),
                           high=_f(r.get("stck_hgpr")), low=_f(r.get("stck_lwpr")),
                           close=_f(r.get("stck_prpr")), volume=_f(r.get("cntg_vol"))))
        return out

    def minute_bars_today(self, code: str, until: Optional[str] = None) -> List[Bar]:
        """오늘 09:00 ~ until(HHMMSS) 1분봉. API 는 30개씩 과거로 주므로 반복 호출."""
        until = until or now_kst().strftime("%H%M%S")
        bars: Dict[str, Bar] = {}
        cursor = until
        for _ in range(14):  # 최대 420분
            res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                             "FHKST03010200", {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
                                               "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": cursor,
                                               "FID_PW_DATA_INCU_YN": "Y"})
            rows = self._bars_from(res.get("output2", [])) if self._ok(res) else []
            today = now_kst().strftime("%Y%m%d")
            rows = [b for b in rows if b.date in ("", today) and b.time >= "0900"]
            if not rows:
                break
            for b in rows:
                bars[b.time] = b
            earliest = min(b.time for b in rows)
            if earliest <= "0900":
                break
            t = dt.datetime.strptime(earliest, "%H%M") - dt.timedelta(minutes=1)
            cursor = t.strftime("%H%M") + "00"
        return [bars[k] for k in sorted(bars)]

    def minute_bars_recent(self, code: str) -> List[Bar]:
        """오늘 최근 30개 1분봉 (1회 호출)."""
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice", "FHKST03010200",
                         {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                          "FID_INPUT_HOUR_1": now_kst().strftime("%H%M%S"), "FID_PW_DATA_INCU_YN": "Y"})
        today = now_kst().strftime("%Y%m%d")
        rows = self._bars_from(res.get("output2", [])) if self._ok(res) else []
        return sorted([b for b in rows if b.date in ("", today) and b.time >= "0900"], key=lambda b: b.time)

    def minute_bars_past(self, code: str, date: str) -> List[Bar]:
        """과거 특정일(YYYYMMDD) 09:00~15:30 1분봉 (실전 전용 API, 120개씩)."""
        bars: Dict[str, Bar] = {}
        cursor = "153000"
        for _ in range(5):
            res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
                             "FHKST03010230", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                               "FID_INPUT_HOUR_1": cursor, "FID_INPUT_DATE_1": date,
                                               "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": ""})
            rows = self._bars_from(res.get("output2", [])) if self._ok(res) else []
            rows = [b for b in rows if b.date == date and "0900" <= b.time <= "1530"]
            if not rows:
                break
            for b in rows:
                bars[b.time] = b
            earliest = min(b.time for b in rows)
            if earliest <= "0900":
                break
            t = dt.datetime.strptime(earliest, "%H%M") - dt.timedelta(minutes=1)
            cursor = t.strftime("%H%M") + "00"
        return [bars[k] for k in sorted(bars)]

    def daily_bars(self, code: str, days: int = 30) -> List[Bar]:
        end = now_kst().date()
        start = end - dt.timedelta(days=int(days * 1.6) + 10)
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                         "FHKST03010100", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                           "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                                           "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                                           "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
        if not self._ok(res):
            raise KISError(f"일봉 실패 {code}: {res.get('msg1')}")
        out = []
        for r in res.get("output2", []) or []:
            if not r.get("stck_bsop_date"):
                continue
            out.append(Bar(time=r["stck_bsop_date"], date=r["stck_bsop_date"], open=_f(r.get("stck_oprc")),
                           high=_f(r.get("stck_hgpr")), low=_f(r.get("stck_lwpr")),
                           close=_f(r.get("stck_clpr")), volume=_f(r.get("acml_vol"))))
        out.sort(key=lambda b: b.time)
        return out[-days:]

    def recent_trades(self, code: str) -> List[Trade]:
        """최근 체결 (최신이 앞). 매수/매도 주도 구분은 tick rule 로 계산."""
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-ccnl", "FHKST01010300",
                         {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        if not self._ok(res):
            return []
        return [Trade(time=r.get("stck_cntg_hour", ""), price=_f(r.get("stck_prpr")), qty=_f(r.get("cntg_vol")))
                for r in res.get("output", []) or []]

    def volume_rank(self, kind: str = "increase") -> List[Dict[str, Any]]:
        """거래량 순위 (kind=increase: 거래증가율 순). 최대 30종목."""
        blng = {"volume": "0", "increase": "1", "value": "3"}[kind]
        res = self._call("GET", "/uapi/domestic-stock/v1/quotations/volume-rank", "FHPST01710000", {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171", "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "1", "FID_BLNG_CLS_CODE": blng, "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000001111", "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""})
        if not self._ok(res):
            return []
        return [{"code": r.get("mksc_shrn_iscd"), "name": r.get("hts_kor_isnm"), "price": _f(r.get("stck_prpr")),
                 "change_pct": _f(r.get("prdy_ctrt")), "volume": _f(r.get("acml_vol")),
                 "avg_volume": _f(r.get("avrg_vol"))} for r in res.get("output", []) or [] if r.get("mksc_shrn_iscd")]

    # ── 계좌 ─────────────────────────────────────────
    def balance(self) -> Tuple[float, List[Position], float]:
        """(주문가능 예수금, 보유종목, 총평가금액)."""
        res = self._call("GET", "/uapi/domestic-stock/v1/trading/inquire-balance", self.tr.get("balance", "TTTC8434R"), {
            "CANO": self.cano, "ACNT_PRDT_CD": self.acnt, "AFHR_FLPR_YN": "N", "OFL_YN": "",
            "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
        if not self._ok(res):
            raise KISError(f"잔고 조회 실패: {res.get('msg1')}")
        positions = []
        for r in res.get("output1", []) or []:
            qty = int(_f(r.get("hldg_qty")))
            if qty > 0:
                positions.append(Position(code=r.get("pdno"), name=r.get("prdt_name", ""), qty=qty,
                                          avg_price=_f(r.get("pchs_avg_pric")), stop=0.0))
        o2 = (res.get("output2") or [{}])[0]
        cash = _f(o2.get("prvs_rcdl_excc_amt")) or _f(o2.get("dnca_tot_amt"))
        total = _f(o2.get("tot_evlu_amt")) or _f(o2.get("nass_amt"))
        return cash, positions, total

    def _order(self, kind: str, code: str, qty: int, price: int, market: bool) -> OrderResult:
        body = {"CANO": self.cano, "ACNT_PRDT_CD": self.acnt, "PDNO": code,
                "ORD_DVSN": "01" if market else "00", "ORD_QTY": str(int(qty)),
                "ORD_UNPR": "0" if market else str(int(price))}
        res = self._call("POST", "/uapi/domestic-stock/v1/trading/order-cash", self.tr[kind], body=body, retries=1)
        if not self._ok(res) and self.tr_legacy.get(kind):
            res = self._call("POST", "/uapi/domestic-stock/v1/trading/order-cash", self.tr_legacy[kind],
                             body=body, retries=1)
        if not self._ok(res):
            return OrderResult(False, message=str(res.get("msg1")))
        o = res.get("output", {})
        return OrderResult(True, order_no=f"{o.get('KRX_FWDG_ORD_ORGNO', '')}|{o.get('ODNO', '')}",
                           message=str(res.get("msg1", "")))

    def buy_limit(self, code: str, qty: int, price: int) -> OrderResult:
        return self._order("buy", code, qty, price, market=False)

    def sell(self, code: str, qty: int, price: Optional[int] = None) -> OrderResult:
        return self._order("sell", code, qty, price or 0, market=price is None)

    def cancel(self, order_no: str, code: str = "") -> bool:
        orgno, odno = (order_no.split("|") + [""])[:2]
        body = {"CANO": self.cano, "ACNT_PRDT_CD": self.acnt, "KRX_FWDG_ORD_ORGNO": orgno, "ORGN_ODNO": odno,
                "ORD_DVSN": "00", "RVSE_CNCL_DVSN_CD": "02", "ORD_QTY": "0", "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": "Y"}
        res = self._call("POST", "/uapi/domestic-stock/v1/trading/order-rvsecncl", self.tr["revise_cancel"],
                         body=body, retries=1)
        if not self._ok(res) and self.tr_legacy.get("revise_cancel"):
            res = self._call("POST", "/uapi/domestic-stock/v1/trading/order-rvsecncl",
                             self.tr_legacy["revise_cancel"], body=body, retries=1)
        return self._ok(res)

    def order_status(self, order_no: str) -> Tuple[int, float, int]:
        """(체결수량, 평균체결가, 미체결수량)."""
        odno = order_no.split("|")[-1]
        today = now_kst().strftime("%Y%m%d")
        params = {"CANO": self.cano, "ACNT_PRDT_CD": self.acnt, "INQR_STRT_DT": today, "INQR_END_DT": today,
                  "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "", "CCLD_DVSN": "00", "ORD_GNO_BRNO": "",
                  "ODNO": odno, "INQR_DVSN_3": "00", "INQR_DVSN_1": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        res = self._call("GET", path, self.tr["daily_ccld"], params)
        if not self._ok(res) and self.tr_legacy.get("daily_ccld"):
            res = self._call("GET", path, self.tr_legacy["daily_ccld"], params)
        for r in res.get("output1", []) or []:
            if str(r.get("odno", "")).lstrip("0") == odno.lstrip("0"):
                return int(_f(r.get("tot_ccld_qty"))), _f(r.get("avg_prvs")), int(_f(r.get("rmn_qty")))
        return 0, 0.0, 0


def _check() -> None:
    s = Settings.load()
    c = KISClient(s)
    print(f"[환경] {c.env}  계좌 {c.cano}-{c.acnt}")
    c.token()
    print("[토큰] OK")
    q = c.quote("005930")
    print(f"[현재가] {q.name} {q.price:,.0f}원 ({q.change_pct:+.2f}%)  VI={q.vi_active}")
    print(f"[지수] 코스피 {c.index_change('KOSPI')}")
    cash, pos, total = c.balance()
    print(f"[잔고] 예수금 {cash:,.0f}원 / 총평가 {total:,.0f}원 / 보유 {len(pos)}종목")
    for p in pos:
        print(f"   - {p.name}({p.code}) {p.qty}주 @ {p.avg_price:,.0f}")
    bars = c.minute_bars_today("005930")
    print(f"[분봉] 오늘 {len(bars)}개")
    past = c.minute_bars_past("005930", (now_kst() - dt.timedelta(days=7)).strftime("%Y%m%d"))
    print(f"[과거분봉] 7일 전 {len(past)}개 (0이면 휴장일이거나 API 미지원 → 타임머신은 쌓인 데이터 사용)")
    print("모두 정상입니다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="토큰·시세·잔고 조회 확인")
    args = ap.parse_args()
    if args.check:
        _check()
    else:
        ap.print_help()
