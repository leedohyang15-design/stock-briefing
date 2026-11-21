"""평일 오케스트레이터: 장전 분석 → 장중 매매 → 장후 복기.

    python -m src.trader.run_day --dry-run     # 실제 시세, 가상 주문 (처음엔 반드시 이것부터)
    python -m src.trader.run_day               # 실계좌 (텔레그램 승인 필수)

윈도우 작업 스케줄러로 평일 07:55 에 실행하도록 등록하면 된다 (README_TRADER.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import datalog
from . import strategy as st
from .agents import intraday, timemachine
from .agents.premarket import PremarketReport, default_inputs, run_premarket
from .agents.review import daily_review
from .broker import LiveBroker, PaperBroker
from .executor import Executor
from .journal import Journal
from .llm import get_llm
from .models import AgentResult, Candidate, Position, Quote, Signal, now_kst
from .risk import DayState, check_loss_limit, evaluate, max_entries
from .settings import Settings
from .telegram_bot import NullTelegram, Telegram
from .ticks import add_ticks, cost_pct

_ETF_WORDS = ("KODEX", "TIGER", "KBSTAR", "ACE ", "SOL ", "HANARO", "ARIRANG", "KOSEF", "RISE ", "PLUS ", "ETN",
              "인버스", "레버리지", "선물", "TIMEFOLIO", "KoAct", "WON ")
TRANSIENT = {11, 13, 14, 15}      # 시간이 지나면 바뀔 수 있는 거부 → 잠시 후 재검사
RECHECK_SEC = 60
MAX_SIGNALS_PER_CODE = 3


def _hhmm(t: str) -> str:
    return t.replace(":", "")


@dataclass
class CodeState:
    status: str = "watch"            # watch | pending | done | blocked | cooldown
    retry_at: float = 0.0
    signals: int = 0
    sid: Optional[int] = None
    pending: Dict = field(default_factory=dict)
    note: str = ""


class DayTrader:
    def __init__(self, settings: Settings, kis, broker, journal: Journal, llm, tg,
                 now_fn: Callable[[], dt.datetime] = now_kst, sleep_fn: Callable[[float], None] = time.sleep,
                 premarket_inputs=None):
        self.s, self.kis, self.broker, self.j, self.llm, self.tg = settings, kis, broker, journal, llm, tg
        self.now, self.sleep = now_fn, sleep_fn
        self.inputs = premarket_inputs
        journal.now_fn = now_fn
        self.ex = Executor(broker, journal, settings.costs, notify=tg.send)
        self.state: Optional[DayState] = None
        self.report: Optional[PremarketReport] = None
        self.inplay: Dict[str, intraday.InPlay] = {}
        self.codes: Dict[str, CodeState] = {}
        self.quotes: Dict[str, Quote] = {}
        self.index = {"KOSPI": 0.0, "KOSDAQ": 0.0}
        self.first30: Optional[float] = None
        self.regime: Optional[AgentResult] = None
        self._last_index = 0.0
        self._last_bars = 0.0
        self.cost_pct = cost_pct(settings.costs.get("fee_pct", 0.015), settings.costs.get("sell_tax_pct", 0.2))
        self._register_commands()

    # ── 공통 ──
    def hhmm(self) -> str:
        return self.now().strftime("%H%M")

    def today(self) -> str:
        return self.now().strftime("%Y%m%d")

    def wait_until(self, hhmm: str) -> None:
        while self.hhmm() < hhmm:
            self.sleep(min(30.0, 5.0))

    def _register_commands(self):
        self.tg.on("status", lambda a: self.status_text())
        self.tg.on("stop", lambda a: self._cmd_stop())
        self.tg.on("flat", lambda a: self._cmd_flat())
        self.tg.on("weekly", lambda a: "주간 복기는 토요일에 run_weekly 로 실행됩니다 (python -m src.trader.run_weekly).")
        self.tg.on("help", lambda a: "/status 현재 상태 · /stop 신규 매수 중단 · /flat 전량 청산+중단")

    def _cmd_stop(self) -> str:
        if self.state:
            self.state.stopped, self.state.stop_reason = True, "사용자 /stop"
        self.j.event("중단", "사용자 /stop → 신규 매수 중단")
        return "신규 매수를 중단했습니다. 보유 종목은 손절·청산 규칙대로 관리합니다."

    def _cmd_flat(self) -> str:
        self._cmd_stop()
        self._flat_requested = True
        return "전량 청산을 요청했습니다."

    def status_text(self) -> str:
        if not self.state:
            return "아직 시작 전입니다."
        s = self.state
        pos = ", ".join(f"{p.name} {p.qty}주 @{p.avg_price:,.0f} (손절 {p.stop:,.0f})" for p in self.ex.positions.values()) or "없음"
        return (f"[{self.broker.mode}] 일 수익률 {s.ret_pct:+.2f}% ({s.pnl:+,.0f}원)\n매수 {s.entries}/"
                f"{max_entries(self.s.risk, s.aggression)}회 · 보유: {pos}\n"
                f"상태: {'중단 - ' + s.stop_reason if s.stopped else '운영 중'}")

    # ── 장전 ──
    def premarket(self) -> PremarketReport:
        self.j.event("정보", "장전 분석팀 실행 시작 (에이전트 1~8)")
        rep = run_premarket(self.llm, self.inputs or default_inputs(), self.s.news.get("reject_keywords", []))
        for r in rep.results:
            self.j.agent_result(r)
        self.report = rep
        if self.state:
            self.state.aggression = rep.aggression
        self.j.snapshot("premarket", rep.to_dict())
        wl = ", ".join(c.name for c in rep.watchlist)
        self.j.event("정보", f"수석 트레이더: 관심종목 {len(rep.watchlist)}개 ({wl}) · 공격성 {rep.aggression}")
        self.tg.send(f"[장전 분석] 공격성 {rep.aggression}\n관심종목: {wl}\n제외: {len(rep.excluded)}종목\n" +
                     "\n".join(f"· {r.agent}: {r.reason}" for r in rep.results[:5]))
        # 일봉·과거 분봉 미리 받기 (타임머신·Stocks in Play 계산용)
        budget = 0
        for c in rep.watchlist + [Candidate(p["code"], p["name"]) for p in rep.pool[:20]]:
            datalog.ensure_daily(self.kis, self.j, c.code, 40)
        if self.s.timemachine.get("enabled", True):
            for c in rep.watchlist:
                if budget > 2000:
                    break
                datalog.ensure_history(self.kis, self.j, c.code, self.s.timemachine.get("lookback_days", 59), 240)
                budget += 240
        return rep

    # ── 09:0x Stocks in Play ──
    def candidates(self) -> List[Candidate]:
        out: Dict[str, Candidate] = {}
        excluded = self.report.excluded if self.report else {}
        for c in (self.report.watchlist if self.report else []):
            out[c.code] = c
        for kind in ("increase", "value"):
            try:
                for r in self.kis.volume_rank(kind):
                    if r["code"] not in out and not any(w in r["name"] for w in _ETF_WORDS):
                        out[r["code"]] = Candidate(r["code"], r["name"], source="scanner")
            except Exception as e:  # noqa: BLE001
                self.j.event("오류", f"거래량 순위 실패: {e}")
        return [c for c in out.values() if c.code not in excluded][:40]

    def scan(self) -> None:
        cfg = self.s.strategy
        or_end = st.hhmm_add("0900", cfg["orb_minutes"])
        cands = self.candidates()
        or_bars, daily = {}, {}
        for c in cands:
            daily[c.code] = datalog.ensure_daily(self.kis, self.j, c.code, 40)
            try:
                or_bars[c.code] = self.kis.minute_bars_today(c.code, or_end + "00")
            except Exception as e:  # noqa: BLE001
                self.j.event("오류", f"분봉 실패 {c.name}: {e}", c.code)
        top, r9 = intraday.scan_stocks_in_play(cands, or_bars, daily, cfg)
        n = cfg["relvol_top_n"] if not self.state or self.state.aggression != "low" else max(1, cfg["relvol_top_n"] // 2)
        top = top[:n]
        r9.reason = f"상위 {len(top)}종목: " + ", ".join(f"{t.name}({t.relvol:.1f}배)" for t in top)
        self.j.agent_result(r9)
        self.inplay = {t.code: t for t in top}
        for i, t in enumerate(top):
            self.codes.setdefault(t.code, CodeState())
            if cfg.get("require_bullish_or", True) and not t.rng.bullish:
                self.codes[t.code].status = "blocked"
                self.codes[t.code].note = "시가범위 음봉"
        self.j.event("정보", "Stocks in Play 확정: " + (", ".join(t.name for t in top) or "없음"))
        self.tg.send("[Stocks in Play] " + (r9.reason if top else "조건 만족 종목 없음 → 오늘은 관망"))

    # ── 장중 루프 ──
    def refresh_quotes(self) -> None:
        codes = set(self.inplay) | set(self.ex.positions)
        for c in codes:
            try:
                self.quotes[c] = self.kis.quote(c)
            except Exception as e:  # noqa: BLE001
                print(f"[quote] {c} 실패: {e}")
        t = self.now().timestamp()
        if t - self._last_index > 30:
            self._last_index = t
            for m in ("KOSPI", "KOSDAQ"):
                try:
                    self.index[m] = self.kis.index_change(m)[1]
                except Exception as e:  # noqa: BLE001
                    print(f"[index] {m} 실패: {e}")
            avg = (self.index["KOSPI"] + self.index["KOSDAQ"]) / 2
            if self.first30 is None and self.hhmm() >= "0930":
                self.first30 = avg
                self.j.event("정보", f"지수 첫 30분 수익률 {avg:+.2f}% (코스피·코스닥 평균)")
            cfg = self.s.strategy
            self.regime = intraday.regime_check(self.hhmm(), avg, self.first30, cfg["regime_early_min_pct"],
                                                cfg["regime_first30_min_pct"], "코스피·코스닥")
        if t - self._last_bars > 60:
            self._last_bars = t
            for c in codes:
                datalog.refresh_today(self.kis, self.j, c, full=False)

    def prices(self) -> Dict[str, float]:
        return {c: q.price for c, q in self.quotes.items()}

    def update_pnl(self) -> None:
        s = self.state
        s.unrealized_pnl = self.ex.unrealized(self.prices())
        s.positions = len(self.ex.positions)
        if check_loss_limit(s, self.s.risk) and s.stop_reason and not getattr(self, "_loss_notified", False):
            self._loss_notified = True
            self.j.event("중단", s.stop_reason)
            self.tg.send(f"⛔ {s.stop_reason} → 오늘 신규 매수 중단")

    def _history(self, code: str) -> Dict:
        hist = datalog.history_from_db(self.j, code, self.today(), self.s.timemachine.get("lookback_days", 59))
        if len(hist) < self.s.timemachine.get("min_days", 10):
            hist = datalog.ensure_history(self.kis, self.j, code, 20, 80)
        return hist

    def evaluate_signal(self, ip: intraday.InPlay, q: Quote, rank: int) -> None:
        cs = self.codes[ip.code]
        cfg, risk = self.s.strategy, self.s.risk
        r10 = intraday.orb_check(q.price, ip, cfg.get("require_bullish_or", True))
        if r10.decision != "pass":
            return
        limit = add_ticks(q.price, 1)
        stop = st.stop_price(limit, ip.atr, cfg["stop_atr_mult"])
        sig = Signal(ip.code, ip.name, q.price, ip.rng.high, ip.rng.low, ip.atr, stop)
        sid = self.j.new_signal(sig, {"relvol": ip.relvol, "time": self.hhmm(), "rank": rank})
        cs.signals += 1
        cs.sid = sid
        self.j.event("신호", f"{ip.name} ORB 돌파 신호 ({q.price:,.0f} > {ip.rng.high:,.0f}) → 에이전트 검사", ip.code)
        results = [intraday.sip_result(ip, rank), r10]
        steps = [
            lambda: self.regime or AgentResult(13, "시장 분위기", "pass", "지수 데이터 대기"),
            lambda: intraday.vi_check(q, ip.rng.open, cfg["static_vi_pct"], cfg["vi_guard_pct"]),
            lambda: intraday.imbalance_check(self.kis.recent_trades(ip.code), cfg["imbalance_trades"], cfg["imbalance_min"]),
            lambda: evaluate(ip.code, q.price, stop, self.hhmm(), self.state, risk),
            lambda: timemachine.check(self._history(ip.code), self.hhmm(), _hhmm(risk.get("flatten_time", "15:15")),
                                      limit, stop, ip.atr, self.s.timemachine, cfg, self.cost_pct),
            lambda: self._news(ip),
        ]
        order = [13, 14, 11, 15, 18, 12]
        blocked: Optional[AgentResult] = None
        for no, fn in zip(order, steps):
            if blocked:
                results.append(AgentResult(no, "", "wait", "앞 단계 거부로 검사하지 않음"))
                continue
            try:
                r = fn()
            except Exception as e:  # noqa: BLE001
                r = AgentResult(no, "", "reject", f"오류로 거부: {e}")
            results.append(r)
            if r.blocks:
                blocked = r
        from .agents import NAMES
        for r in results:
            r.agent = r.agent or NAMES.get(r.no, "")
            self.j.agent_result(r, ip.code, sid)
        if blocked:
            permanent = blocked.no not in TRANSIENT or cs.signals >= MAX_SIGNALS_PER_CODE
            if blocked.no == 15 and any(k in blocked.reason for k in ("마감", "중단", "이미 거래")):
                permanent = True
            cs.status = "blocked" if permanent else "cooldown"
            cs.retry_at = self.now().timestamp() + RECHECK_SEC
            cs.note = f"{blocked.agent}: {blocked.reason}"
            self.j.update_signal(sid, "rejected", cs.note)
            self.j.event("거부", f"{ip.name} 신호 → {blocked.no}번 {blocked.agent} 거부 ({blocked.reason})"
                         + ("" if permanent else " · 1분 후 재검사"), ip.code)
            return
        rk = next(r for r in results if r.no == 15)
        qty, lim = rk.data["qty"], rk.data["limit_price"]
        tm = next((r for r in results if r.no == 18), None)
        self.j.update_signal(sid, "pending", "승인 대기", qty)
        cs.status, cs.pending = "pending", {"qty": qty, "limit": lim, "stop": stop}
        bull = (self.report.bull.get(ip.code, "") if self.report else "")
        bear = (self.report.bear.get(ip.code, "") if self.report else "")
        msg = (f"[매수 승인 요청] {ip.name} ({ip.code})\n{qty}주 × {lim:,}원 = {qty * lim:,}원\n"
               f"손절 {stop:,.0f}원 · 15:15 자동 청산\n상대거래량 {ip.relvol:.1f}배 · 시가범위 {ip.rng.low:,.0f}~{ip.rng.high:,.0f}\n"
               f"타임머신: {tm.reason if tm else '-'}\n강세: {bull or '-'}\n약세: {bear or '-'}\n"
               f"{self.s.approval.get('timeout_sec', 180) // 60}분 안에 응답이 없으면 취소됩니다.")
        self.tg.request_approval(sid, msg)
        self.j.event("매수", f"{ip.name} 필터 통과 → 텔레그램 승인 요청 ({qty}주 @{lim:,})", ip.code)

    def _news(self, ip) -> AgentResult:
        from . import naver
        return intraday.news_check(self.llm, ip.name, naver.stock_news(ip.code), naver.stock_notices(ip.code),
                                   self.s.news.get("reject_keywords", []), self.s.news.get("llm_required", True))

    def handle_pending(self, code: str) -> None:
        cs = self.codes[code]
        status = self.tg.approval_status(cs.sid, self.s.approval.get("timeout_sec", 180))
        if status == "pending":
            return
        ip, q = self.inplay[code], self.quotes.get(code)
        if status != "approved":
            cs.status = "blocked"
            self.j.update_signal(cs.sid, "rejected" if status == "rejected" else "expired",
                                 "사용자 거절" if status == "rejected" else "승인 시간 초과")
            self.j.event("거부", f"{ip.name} {'사용자 거절' if status == 'rejected' else '승인 시간 초과'}", code)
            return
        p = cs.pending
        if q and q.price > p["limit"] * 1.01:
            cs.status = "blocked"
            self.j.update_signal(cs.sid, "expired", "승인 사이 가격 1% 이상 상승 → 추격 매수 안 함")
            self.j.event("거부", f"{ip.name} 승인 후 가격 이탈 ({q.price:,.0f}) → 주문 안 함", code)
            self.tg.send(f"{ip.name}: 승인하는 사이 가격이 1% 넘게 올라 주문하지 않았습니다.")
            return
        r = evaluate(code, q.price if q else p["limit"], p["stop"], self.hhmm(), self.state, self.s.risk)
        if r.blocks:
            cs.status = "blocked"
            self.j.update_signal(cs.sid, "rejected", f"승인 후 리스크 재검사 거부: {r.reason}")
            self.j.event("거부", f"{ip.name} 승인 후 리스크 재검사 거부: {r.reason}", code)
            return
        filled = self.ex.enter(code, ip.name, min(p["qty"], r.data["qty"]), p["limit"], p["stop"], cs.sid)
        cs.status = "done"
        self.j.agent_result(AgentResult(16, "주문 실행·청산", "pass" if filled else "wait",
                                        f"지정가 {p['limit']:,}원 {filled}주 체결 · 손절 {p['stop']:,.0f} · 15:15 청산"
                                        if filled else "미체결 → 주문 취소"), code, cs.sid)
        self.j.update_signal(cs.sid, "filled" if filled else "unfilled", f"{filled}주 체결" if filled else "미체결")
        if filled:
            self.state.entries += 1
            self.state.traded_codes.add(code)
            self.state.cash -= filled * p["limit"]

    def tick(self) -> None:
        self.refresh_quotes()
        prices = self.prices()
        realized = self.ex.check_stops(prices)
        self.state.realized_pnl += realized
        if getattr(self, "_flat_requested", False):
            self.state.realized_pnl += self.ex.flatten(prices, "사용자 청산")
            self._flat_requested = False
        self.update_pnl()
        for rank, (code, ip) in enumerate(self.inplay.items(), start=1):
            cs, q = self.codes[code], self.quotes.get(code)
            if not q:
                continue
            if cs.status == "pending":
                self.handle_pending(code)
            elif cs.status == "watch" or (cs.status == "cooldown" and self.now().timestamp() >= cs.retry_at):
                if code in self.ex.positions or self.state.stopped:
                    continue
                self.evaluate_signal(ip, q, rank)
        self.snapshot()

    def snapshot(self) -> None:
        s = self.state
        limit_amt = s.start_equity * self.s.risk.get("daily_loss_limit_pct", 3.0) / 100
        closed = self.j.query("SELECT net_pnl FROM trades WHERE date=? AND exit_ts IS NOT NULL", (self.today(),))
        self.j.snapshot("status", {
            "mode": self.broker.mode, "ts": self.now().isoformat(timespec="seconds"), "start_equity": s.start_equity,
            "pnl": s.pnl, "ret_pct": s.ret_pct, "realized": s.realized_pnl, "unrealized": s.unrealized_pnl,
            "loss_room": limit_amt + s.pnl, "loss_limit_amt": limit_amt, "entries": s.entries,
            "max_entries": max_entries(self.s.risk, s.aggression), "positions": [p.__dict__ for p in self.ex.positions.values()],
            "max_positions": self.s.risk.get("max_positions", 2), "stopped": s.stopped, "stop_reason": s.stop_reason,
            "aggression": s.aggression, "wins": sum(1 for t in closed if (t["net_pnl"] or 0) > 0),
            "losses": sum(1 for t in closed if (t["net_pnl"] or 0) <= 0),
            "regime": self.regime.__dict__ if self.regime else None, "index": self.index, "first30": self.first30,
        })
        self.j.snapshot("inplay", [{
            "code": c, "name": ip.name, "relvol": ip.relvol, "or_high": ip.rng.high, "or_low": ip.rng.low,
            "or_end": ip.rng.end, "atr": ip.atr, "vi_upper": st.static_vi_upper(ip.rng.open, self.s.strategy["static_vi_pct"]),
            "price": self.quotes[c].price if c in self.quotes else None,
            "change_pct": self.quotes[c].change_pct if c in self.quotes else None,
            "status": self.codes[c].status, "note": self.codes[c].note, "pm_note": ip.note,
        } for c, ip in self.inplay.items()])

    # ── 전체 일정 ──
    def start(self, paper_cash: float) -> None:
        cash, _, total = self.broker.balance()
        self.state = DayState(start_equity=total or cash or paper_cash, cash=cash)
        if self.broker.mode == "live":
            self.ex.restore(self._restore_stop)
            self.state.positions = len(self.ex.positions)
            self.state.traded_codes |= set(self.ex.positions)
        self.j.event("정보", f"[{self.broker.mode}] 시작 · 평가금 {self.state.start_equity:,.0f}원 · 예수금 {cash:,.0f}원")

    def _restore_stop(self, p: Position) -> float:
        a = st.atr(datalog.ensure_daily(self.kis, self.j, p.code, 30)) or p.avg_price * 0.05
        return st.stop_price(p.avg_price, a, self.s.strategy["stop_atr_mult"])

    def run(self, paper_cash: float = 1_000_000.0) -> None:
        sch, risk, cfg = self.s.schedule, self.s.risk, self.s.strategy
        self.tg.start()
        self.start(paper_cash)
        self.tg.send(f"[{'드라이런' if self.broker.mode == 'paper' else '실계좌'}] 트레이더 시작 · 평가금 {self.state.start_equity:,.0f}원")
        self.wait_until(_hhmm(sch.get("premarket_start", "08:00")))
        if self.hhmm() < _hhmm(risk.get("entry_end", "15:10")):
            self.premarket()
        scan_at = st.hhmm_add("0900", cfg["orb_minutes"])
        self.wait_until(scan_at)
        self.sleep(10)
        flatten = _hhmm(risk.get("flatten_time", "15:15"))
        if self.hhmm() < flatten:
            self.scan()
        interval = float(sch.get("loop_interval_sec", 5))
        while self.hhmm() < flatten:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.j.event("오류", f"루프 오류: {e}")
            self.sleep(interval)
        self.refresh_quotes()
        self.state.realized_pnl += self.ex.flatten(self.prices(), "장마감 청산")
        self.update_pnl()
        self.snapshot()
        self.wait_until(_hhmm(sch.get("review_time", "15:40")))
        datalog.record_eod(self.kis, self.j, list(self.inplay) + [c.code for c in (self.report.watchlist if self.report else [])])
        _, text = daily_review(self.j, self.llm, self.today(), self.state.start_equity, self.broker.mode)
        self.j.event("정보", "일일 복기 완료")
        self.tg.send(text)
        self.tg.stop()


def build(dry_run: bool, settings: Optional[Settings] = None, paper_cash: float = 1_000_000.0):
    from .kis_client import KISClient
    s = settings or Settings.load()
    kis = KISClient(s)
    j = Journal()
    sec = s.secrets
    if dry_run:
        broker = PaperBroker(lambda c: kis.quote(c).price, cash=paper_cash)
        tg = Telegram(sec.telegram_token, sec.telegram_chat_id) if sec.has_telegram else NullTelegram()
    else:
        if not sec.has_telegram or s.approval.get("mode") != "telegram":
            raise SystemExit("실계좌는 텔레그램 승인이 필수입니다 (.env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, approval.mode: telegram)")
        broker = LiveBroker(kis)
        tg = Telegram(sec.telegram_token, sec.telegram_chat_id)
    return DayTrader(s, kis, broker, j, get_llm(), tg)


def main() -> None:
    ap = argparse.ArgumentParser(description="AI 멀티에이전트 단타 트레이더")
    ap.add_argument("--dry-run", action="store_true", help="실제 시세 + 가상 주문")
    ap.add_argument("--force", action="store_true", help="휴장일에도 실행")
    ap.add_argument("--paper-cash", type=float, default=1_000_000.0, help="드라이런 가상 예수금")
    args = ap.parse_args()
    from ..holidays_kr import is_market_holiday
    if is_market_holiday(now_kst().date()) and not args.force:
        print("오늘은 휴장일입니다.")
        return
    build(args.dry_run, paper_cash=args.paper_cash).run(args.paper_cash)


if __name__ == "__main__":
    main()
