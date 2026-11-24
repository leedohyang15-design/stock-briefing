"""17. 복기 에이전트 — 평일 15:40 일일 리포트 / 토요일 주간 전략 업데이트. + 투자 대가 패널(참고용).

주간 업데이트 흐름 (릴스 1: '돈 잃은 거래만 골라 원인 찾기 → 규칙 수정 → 재시험' 반복)
 1) 그 주 성과 집계 (일 수익률이 1순위 지표)
 2) 에이전트 성적표: 거부한 신호가 실제로 어떻게 됐는지 쌓인 분봉으로 채점
 3) 손실 거래 원인 분석 → 허용된 파라미터(levers) 안에서 수정안 → 백테스트 재시험 (최대 3회)
 4) 과최적화 방지: 과거 구간·최근 구간 모두 일 수익률이 좋아지고 표본 ≥ min_samples 일 때만 제안,
    한 번에 최대 max_param_changes 개
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, List, Optional, Tuple

from .. import backtest
from ..journal import Journal
from ..models import AgentResult, now_kst
from ..settings import Settings
from ..ticks import cost_pct


# ── 일일 ────────────────────────────────────────────
def daily_review(journal: Journal, llm, date: str, start_equity: float, mode: str) -> Tuple[AgentResult, str]:
    trades = journal.query("SELECT * FROM trades WHERE date=? AND exit_ts IS NOT NULL", (date,))
    net = sum(t["net_pnl"] or 0 for t in trades)
    wins = sum(1 for t in trades if (t["net_pnl"] or 0) > 0)
    losses = len(trades) - wins
    journal.save_daily(date, start_equity, net, len(trades), wins, losses, mode)
    ret = net / start_equity * 100 if start_equity else 0.0
    sigs = journal.query("SELECT status, COUNT(*) n FROM signals WHERE date=? GROUP BY status", (date,))
    rej = journal.query("SELECT agent, COUNT(*) n FROM agent_results WHERE date=? AND decision='reject' "
                        "AND signal_id IS NOT NULL GROUP BY agent ORDER BY n DESC", (date,))
    lines = [f"[일일 리포트 {date}] ({'드라이런' if mode == 'paper' else '실계좌'})",
             f"일 수익률 {ret:+.2f}% ({net:+,.0f}원) · {len(trades)}건 {wins}승 {losses}패",
             "신호: " + ", ".join(f"{r['status']} {r['n']}" for r in sigs) if sigs else "신호 없음"]
    if rej:
        lines.append("거부 많이 한 에이전트: " + ", ".join(f"{r['agent']} {r['n']}" for r in rej[:4]))
    sh = journal.query("SELECT * FROM shadow WHERE date=? AND exit_ts IS NOT NULL", (date,))
    if sh:
        avg = sum(r["ret_pct"] for r in sh) / len(sh)
        saved = sum(1 for r in sh if r["ret_pct"] < 0)
        lines.append(f"👻 그림자 거래 {len(sh)}건 (거부된 신호를 샀다면): 평균 {avg:+.2f}% · 거부가 옳았던 건 {saved}/{len(sh)}")
    for t in trades:
        lines.append(f" - {t['name']} {t['qty']}주 {t['entry_price']:,.0f}→{t['exit_price']:,.0f} "
                     f"{t['exit_reason']} {t['net_pnl']:+,.0f}원")
    if llm.available and trades:
        out = llm.json("너는 단타팀 복기 담당이다. 사실만 짧게 정리한다.",
                       "\n".join(lines) + '\n\n오늘 매매에서 배울 점 1~2개. 형식: {"lessons": ["..."]}', 300)
        for ls in (out or {}).get("lessons", [])[:2]:
            lines.append(f"· {ls}")
    text = "\n".join(lines)
    return AgentResult(17, "복기", "info", f"일 수익률 {ret:+.2f}%", {"ret_pct": ret, "net": net}), text


# ── 주간: 성과 / 성적표 ──────────────────────────────
def week_metrics(journal: Journal, since: str) -> Dict[str, Any]:
    days = journal.query("SELECT * FROM daily WHERE date>=? ORDER BY date", (since,))
    trades = journal.query("SELECT * FROM trades WHERE date>=? AND exit_ts IS NOT NULL", (since,))
    wins = [t["net_pnl"] for t in trades if (t["net_pnl"] or 0) > 0]
    losses = [t["net_pnl"] for t in trades if (t["net_pnl"] or 0) <= 0]
    total = 1.0
    for d in days:
        total *= 1 + (d["ret_pct"] or 0) / 100
    return {
        "days": [{"date": d["date"], "ret_pct": d["ret_pct"]} for d in days],
        "cum_ret_pct": (total - 1) * 100, "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "payoff": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses and sum(losses) else None,
        "worst_day": min((d["ret_pct"] for d in days), default=0.0),
    }


def _outcome(journal: Journal, sig: Dict[str, Any], flatten: str, cpct: float) -> Optional[float]:
    """거부된 신호를 그대로 샀다면 (비용 차감 %)."""
    bars = journal.bars(sig["code"], sig["date"])
    t0 = sig["ts"][11:16].replace(":", "")
    after = [b for b in bars if t0 < b.time < flatten]
    if not after or not sig["price"]:
        return None
    for b in after:
        if sig["stop"] and b.low <= sig["stop"]:
            return (sig["stop"] / sig["price"] - 1) * 100 - cpct
    return (after[-1].close / sig["price"] - 1) * 100 - cpct


def scorecard(journal: Journal, since: str, s: Settings) -> List[Dict[str, Any]]:
    flatten = s.risk.get("flatten_time", "15:15").replace(":", "")
    cpct = cost_pct(s.costs.get("fee_pct", 0.015), s.costs.get("sell_tax_pct", 0.2))
    sigs = journal.query("SELECT * FROM signals WHERE date>=? AND status='rejected'", (since,))
    stats: Dict[str, Dict[str, Any]] = {}
    for sig in sigs:
        blk = journal.query("SELECT no, agent FROM agent_results WHERE signal_id=? AND decision='reject' ORDER BY id LIMIT 1",
                            (sig["id"],))
        if not blk:
            continue
        key = f"{blk[0]['no']} {blk[0]['agent']}"
        sh = journal.query("SELECT ret_pct FROM shadow WHERE signal_id=? AND exit_ts IS NOT NULL", (sig["id"],))
        o = sh[0]["ret_pct"] if sh else _outcome(journal, sig, flatten, cpct)   # 그림자 거래 결과 우선
        st_ = stats.setdefault(key, {"name": key, "rejects": 0, "scored": 0, "right": 0, "avoided_pct": 0.0})
        st_["rejects"] += 1
        if o is not None:
            st_["scored"] += 1
            st_["right"] += 1 if o < 0 else 0
            st_["avoided_pct"] += -o
    out = []
    for v in stats.values():
        v["right_rate"] = v["right"] / v["scored"] * 100 if v["scored"] else None
        out.append(v)
    return sorted(out, key=lambda x: x["rejects"], reverse=True)


# ── 주간: 파라미터 수정안 탐색 ─────────────────────────
def _split(dates: List[str], holdout: int) -> Tuple[List[str], List[str]]:
    if len(dates) <= holdout:
        return [], dates
    return dates[:-holdout], dates[-holdout:]


def _eval(journal, s: Settings, ins, outs):
    a, b = backtest.run(journal, s, ins), backtest.run(journal, s, outs)
    return a, b


def _valid_changes(changes: Dict[str, Any], levers: Dict[str, list], s: Settings, max_n: int) -> Dict[str, Any]:
    ok = {}
    for k, v in (changes or {}).items():
        if k in levers and v in levers[k] and s.get_param(k) != v:
            ok[k] = v
    return dict(list(ok.items())[:max_n])


def search_changes(journal: Journal, s: Settings, llm, log: List[str]) -> Dict[str, Any]:
    w = s.weekly
    levers: Dict[str, list] = w.get("levers", {})
    max_n = w.get("max_param_changes", 2)
    dates = journal.bar_dates()
    ins, outs = _split(dates, w.get("holdout_days", 5))
    base_in, base_out = _eval(journal, s, ins, outs)
    result = {"baseline": {"in": base_in.mean_daily, "out": base_out.mean_daily, "n": base_in.n + base_out.n,
                           "in_days": len(ins), "out_days": len(outs)}, "tried": [], "best": None}
    log.append(f"현재 규칙 백테스트: 과거 {len(ins)}일 일평균 {base_in.mean_daily:+.3f}% / 최근 {len(outs)}일 "
               f"{base_out.mean_daily:+.3f}% · 표본 {base_in.n + base_out.n}건")
    if not ins:
        log.append("과거 구간 데이터가 없어 변경 제안을 하지 않습니다 (데이터 누적 중).")
        return result

    def accept(ch: Dict[str, Any]):
        t = s.with_params(ch)
        a, b = _eval(journal, t, ins, outs)
        n = a.n + b.n
        good = n >= w.get("min_samples", 30) and a.mean_daily > base_in.mean_daily and b.mean_daily > base_out.mean_daily
        rec = {"changes": ch, "in": a.mean_daily, "out": b.mean_daily, "n": n, "accepted": good}
        result["tried"].append(rec)
        return rec

    losers = [t for t in base_in.trades if t.ret_pct < 0]
    tried_keys = set()
    # 1) LLM 손실 원인 분석 루프
    for it in range(w.get("max_iterations", 3)):
        if not llm.available or not losers:
            break
        feats = [dict(date=t.date, code=t.code, ret=round(t.ret_pct, 2), reason=t.reason, **t.features) for t in losers[:40]]
        prompt = ("돈을 잃은 거래 목록(백테스트):\n" + json.dumps(feats, ensure_ascii=False) +
                  "\n\n현재 파라미터: " + json.dumps({k: s.get_param(k) for k in levers}, ensure_ascii=False) +
                  "\n바꿀 수 있는 파라미터와 후보값: " + json.dumps(levers, ensure_ascii=False) +
                  "\n이미 시험한 결과: " + json.dumps(result["tried"], ensure_ascii=False, default=str) +
                  f"\n\n손실 거래의 공통 원인을 하나 찾고, 그 원인을 줄일 변경을 최대 {max_n}개 제안하라. "
                  '형식: {"cause": "한 문장", "changes": {"파라미터": 값}}')
        out = llm.json("너는 단타팀 복기 담당 퀀트다. 데이터에 근거해 원인을 찾는다.", prompt, 500)
        ch = _valid_changes((out or {}).get("changes", {}), levers, s, max_n)
        if not ch or json.dumps(ch, sort_keys=True) in tried_keys:
            continue
        tried_keys.add(json.dumps(ch, sort_keys=True))
        rec = accept(ch)
        rec["cause"] = (out or {}).get("cause", "")
        log.append(f"[반복 {it + 1}] 원인: {rec['cause']} → 수정 {ch} → 과거 {rec['in']:+.3f}% / 최근 {rec['out']:+.3f}% "
                   f"({'채택 가능' if rec['accepted'] else '기각'})")
    # 2) 규칙 기반 탐색 (LLM 이 없거나 채택안이 없을 때): 단일 변경 → 최선안에 하나 더
    if not any(r["accepted"] for r in result["tried"]):
        singles = []
        for k, vals in levers.items():
            for v in vals:
                ch = _valid_changes({k: v}, levers, s, 1)
                if ch and json.dumps(ch, sort_keys=True) not in tried_keys:
                    tried_keys.add(json.dumps(ch, sort_keys=True))
                    singles.append(accept(ch))
        good = sorted([r for r in singles if r["accepted"]], key=lambda r: r["in"], reverse=True)
        if good and max_n >= 2:
            top = good[0]
            for other in good[1:4]:
                ch = {**top["changes"], **other["changes"]}
                if len(ch) == 2:
                    accept(ch)
    acc = [r for r in result["tried"] if r["accepted"]]
    if acc:
        result["best"] = max(acc, key=lambda r: (r["in"] + r["out"]))
        log.append(f"제안: {result['best']['changes']} (과거 {result['best']['in']:+.3f}% / 최근 {result['best']['out']:+.3f}%)")
    else:
        log.append("과최적화 방지 규칙을 통과한 변경이 없어 이번 주는 설정을 유지합니다.")
    return result


def investor_panel(llm, stocks: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """버핏·멍거·그레이엄·린치·드러켄밀러 관점 의견 (virattt/ai-hedge-fund 아이디어). 단타 판단에 쓰지 않는다."""
    if not llm.available or not stocks:
        return []
    out = llm.json("너는 유명 투자자들의 공개된 투자 철학을 요약해 적용하는 교육용 패널이다. 실제 인물의 발언이 아님을 전제로 한다.",
                   "종목: " + ", ".join(f"{s['name']}({s['code']})" for s in stocks[:8]) +
                   "\n\n버핏, 멍거, 그레이엄, 린치, 드러켄밀러의 투자 철학 관점에서 각자 한 종목을 골라 사자/팔자/중립과 이유 한 문장. "
                   '형식: {"items": [{"name": "버핏 관점", "view": "종목명 사자/팔자/중립 · 이유"}]}', 600)
    return [i for i in (out or {}).get("items", []) if isinstance(i, dict)][:5]


def weekly_report(journal: Journal, s: Settings, llm, panel: bool = True) -> Dict[str, Any]:
    since = (now_kst() - dt.timedelta(days=7)).strftime("%Y%m%d")
    log: List[str] = []
    rep: Dict[str, Any] = {"generated": now_kst().isoformat(timespec="seconds"), "since": since}
    rep["metrics"] = week_metrics(journal, since)
    rep["scorecard"] = scorecard(journal, since, s)
    share = backtest.estimate_open_share(journal, s.strategy["orb_minutes"])
    rep["calibration"] = {"open_volume_share": share} if share else {}
    rep["search"] = search_changes(journal, s, llm, log)
    rep["log"] = log
    if panel:
        wl = journal.get_snapshot("premarket", {}).get("watchlist", [])
        rep["panel"] = investor_panel(llm, wl)
    m = rep["metrics"]
    summary = [f"[주간 복기] 누적 {m['cum_ret_pct']:+.2f}% · {m['trades']}건 · 승률 {m['win_rate']:.0f}% · "
               f"최대 손실일 {m['worst_day']:+.2f}%"]
    summary += log
    if llm.available:
        out = llm.json("너는 단타팀 복기 담당이다. 초보 투자자도 이해하게 쉬운 말로 쓴다.",
                       "\n".join(summary) + '\n\n이번 주를 3줄로 요약. 형식: {"lines": ["..."]}', 400)
        rep["plain"] = (out or {}).get("lines", [])
    rep["text"] = "\n".join(summary + [f"· {x}" for x in rep.get("plain", [])])
    return rep
