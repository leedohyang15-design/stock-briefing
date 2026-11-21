"""A. 장전 분석팀 (08:00~08:50) — 에이전트 1~8.

TradingAgents(Xiao 외, arXiv 2412.20138)의 '분석가 → 강세·약세 토론 → 트레이더' 구조를 따른다.
LLM 은 종목 선정과 근거 정리에만 쓰고, 실제 진입·청산은 장중 규칙 에이전트가 결정한다.
LLM 이 없거나 실패하면 규칙 기반 대체 결과를 낸다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from ..models import AgentResult, Candidate

_SYS = ("너는 한국 주식 단타(당일 매매) 트레이딩팀의 {role}다. 과장 없이 사실과 데이터에 근거해 "
        "짧은 한국어로 답한다. 모르는 것은 모른다고 한다.")


def _sys(role: str) -> str:
    return _SYS.format(role=role)


@dataclass
class PremarketInputs:
    """수집 함수들을 주입할 수 있게 묶음 (테스트에서 가짜로 교체)."""
    indices: Callable[[], List[str]]
    headlines: Callable[[], List[str]]
    themes: Callable[[], List[str]]
    pool: Callable[[], List[Dict[str, Any]]]
    notices: Callable[[str], List[Dict[str, str]]]


def default_inputs() -> PremarketInputs:
    from ...collectors import hot_sectors, indices, issues
    from .. import naver

    def _idx():
        return [f"{q.name} {q.value:,.2f} ({q.change_pct:+.2f}%)" for q in indices.fetch_indices()]

    def _news():
        return [i.title for i in issues.fetch_top_issues(limit=10)]

    def _themes():
        groups, _ = hot_sectors.fetch_trending(themes_n=5, per_sector=3)
        return [f"{g.name} {g.headline_pct:+.2f}% (대표: {', '.join(s.name for s in g.stocks)})" for g in groups]

    return PremarketInputs(indices=_idx, headlines=_news, themes=_themes,
                           pool=lambda: naver.top_trading_value(30), notices=naver.stock_notices)


@dataclass
class PremarketReport:
    results: List[AgentResult] = field(default_factory=list)
    watchlist: List[Candidate] = field(default_factory=list)
    excluded: Dict[str, str] = field(default_factory=dict)   # code → 사유
    aggression: str = "normal"                                 # low | normal | high
    bull: Dict[str, str] = field(default_factory=dict)         # code → 강세 근거
    bear: Dict[str, str] = field(default_factory=dict)
    pool: List[Dict[str, Any]] = field(default_factory=list)
    market_lines: List[str] = field(default_factory=list)
    themes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.__dict__ for r in self.results],
            "watchlist": [c.__dict__ for c in self.watchlist], "excluded": self.excluded,
            "aggression": self.aggression, "bull": self.bull, "bear": self.bear, "pool": self.pool,
            "market_lines": self.market_lines, "themes": self.themes,
        }


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[premarket] 수집 실패: {e}")
        return default


def agent_macro(llm, lines: List[str]) -> AgentResult:
    out = llm.json(_sys("매크로 분석가"), "간밤 해외 지수·환율·원자재:\n" + "\n".join(lines) +
                   '\n\n오늘 국내 증시 분위기를 -2(매우 약세)~+2(매우 강세) 정수 점수로 평가하라. '
                   '형식: {"score": 정수, "summary": "한 문장"}', 300) if llm.available and lines else None
    if out and "score" in out:
        score = max(-2, min(2, int(out.get("score", 0))))
        return AgentResult(1, "매크로", "info", f"분위기 {score:+d} · {out.get('summary', '')}", {"score": score})
    # 대체: 나스닥 등락률 부호
    score = 0
    for ln in lines:
        if "나스닥" in ln:
            score = 1 if "+" in ln.split("(")[-1] else -1
    return AgentResult(1, "매크로", "info", f"분위기 {score:+d} (규칙 기반: 나스닥 방향)", {"score": score})


def agent_news(llm, headlines: List[str]) -> AgentResult:
    out = llm.json(_sys("시사·뉴스 분석가"), "오늘 아침 주요 증시 뉴스 제목:\n" + "\n".join(f"- {h}" for h in headlines) +
                   '\n\n수혜·피해가 예상되는 업종을 뽑아라. 형식: {"positive": ["업종"], "negative": ["업종"], '
                   '"summary": "한 문장"}', 400) if llm.available and headlines else None
    if out:
        return AgentResult(2, "시사·뉴스", "info", out.get("summary", ""),
                           {"positive": out.get("positive", []), "negative": out.get("negative", []), "headlines": headlines})
    return AgentResult(2, "시사·뉴스", "info", f"주요 뉴스 {len(headlines)}건 수집 (LLM 요약 없음)", {"headlines": headlines})


def agent_disclosure(pool: List[Dict[str, Any]], notices_fn, keywords: List[str]) -> AgentResult:
    """후보 종목 최근 공시 제목에서 악재 키워드를 찾아 제외 목록을 만든다 (규칙)."""
    flagged: Dict[str, str] = {}
    for s in pool:
        for n in _safe(lambda: notices_fn(s["code"]), [])[:5]:
            hit = next((k for k in keywords if k in n.get("title", "")), None)
            if hit:
                flagged[s["code"]] = f"{s['name']}: {n['title']} ({n.get('date', '')})"
                break
    reason = f"악재 공시 {len(flagged)}종목 제외" if flagged else "후보 종목에 악재 공시 없음"
    return AgentResult(3, "공시", "info", reason, {"flagged": flagged})


def agent_theme(themes: List[str]) -> AgentResult:
    return AgentResult(4, "테마·섹터", "info", " / ".join(themes[:3]) if themes else "테마 데이터 없음", {"themes": themes})


def agent_flow(pool: List[Dict[str, Any]]) -> AgentResult:
    top = pool[:5]
    txt = ", ".join(f"{s['name']}({s['value_krw'] / 1e8:,.0f}억, {s['change_pct']:+.1f}%)" for s in top)
    return AgentResult(5, "수급·거래대금", "info", f"전일 거래대금 상위: {txt}" if top else "데이터 없음", {"top": top})


def _brief(results: List[AgentResult], pool: List[Dict[str, Any]]) -> str:
    lines = [f"[{r.agent}] {r.reason}" for r in results]
    plist = "\n".join(f"- {s['code']} {s['name']} 전일 {s['change_pct']:+.1f}% 거래대금 {s['value_krw'] / 1e8:,.0f}억" for s in pool)
    return "분석가 보고:\n" + "\n".join(lines) + "\n\n후보 종목(전일 거래대금 상위):\n" + plist


def agent_debate(llm, brief: str, side: str) -> AgentResult:
    no, name = (6, "강세론자") if side == "bull" else (7, "약세론자")
    ask = "오늘 단타로 '살 만한 이유'" if side == "bull" else "오늘 단타로 '사면 안 되는 이유와 위험'"
    out = llm.json(_sys(name), brief + f"\n\n후보 종목 중 최대 10개에 대해 {ask}를 종목별 한 문장으로 써라. "
                   '형식: {"items": [{"code": "6자리", "text": "한 문장"}]}', 1200) if llm.available else None
    items = {}
    for it in (out or {}).get("items", []) or []:
        if isinstance(it, dict) and it.get("code"):
            items[str(it["code"]).zfill(6)] = str(it.get("text", ""))
    reason = f"{len(items)}종목 의견" if items else "LLM 없음 → 의견 없음"
    return AgentResult(no, name, "info", reason, {"items": items})


def agent_pm(llm, brief: str, bull: Dict[str, str], bear: Dict[str, str], pool: List[Dict[str, Any]],
             excluded: Dict[str, str], max_n: int = 10) -> AgentResult:
    prompt = (brief + "\n\n강세론:\n" + json.dumps(bull, ensure_ascii=False) + "\n약세론:\n" +
              json.dumps(bear, ensure_ascii=False) + "\n악재 공시로 제외된 종목:\n" + json.dumps(excluded, ensure_ascii=False) +
              f"\n\n토론을 종합해 오늘 장중에 지켜볼 관심종목을 최대 {max_n}개 고르고, 추가로 피해야 할 종목과 "
              "오늘의 공격성(low/normal/high)을 정하라. 관심종목도 장중 규칙(시가범위 돌파 등)을 통과해야만 매수된다. "
              '형식: {"watchlist": [{"code": "6자리", "note": "한 문장"}], "exclude": [{"code": "6자리", "reason": "..."}], '
              '"aggression": "normal", "summary": "한 문장"}')
    out = llm.json(_sys("수석 트레이더(PM)"), prompt, 1200) if llm.available else None
    names = {s["code"]: s["name"] for s in pool}
    wl: List[Dict[str, str]] = []
    excl: Dict[str, str] = {}
    aggression = "normal"
    summary = ""
    if out:
        for it in out.get("watchlist", []) or []:
            code = str(it.get("code", "")).zfill(6) if isinstance(it, dict) else ""
            if code in names and code not in excluded:
                wl.append({"code": code, "name": names[code], "note": it.get("note", "")})
        for it in out.get("exclude", []) or []:
            if isinstance(it, dict) and it.get("code"):
                excl[str(it["code"]).zfill(6)] = str(it.get("reason", "PM 제외"))
        aggression = out.get("aggression", "normal") if out.get("aggression") in ("low", "normal", "high") else "normal"
        summary = out.get("summary", "")
    if not wl:
        wl = [{"code": s["code"], "name": s["name"], "note": "거래대금 상위 (규칙 기반)"}
              for s in pool if s["code"] not in excluded][:max_n]
        summary = summary or "LLM 판단 없음 → 전일 거래대금 상위로 관심종목 구성"
    return AgentResult(8, "수석 트레이더(PM)", "info", f"관심종목 {len(wl)}개 · 공격성 {aggression} · {summary}",
                       {"watchlist": wl, "exclude": excl, "aggression": aggression})


def run_premarket(llm, inputs: PremarketInputs, reject_keywords: List[str]) -> PremarketReport:
    rep = PremarketReport()
    rep.market_lines = _safe(inputs.indices, [])
    headlines = _safe(inputs.headlines, [])
    rep.themes = _safe(inputs.themes, [])
    rep.pool = _safe(inputs.pool, [])

    r1 = agent_macro(llm, rep.market_lines)
    r2 = agent_news(llm, headlines)
    r3 = agent_disclosure(rep.pool, inputs.notices, reject_keywords)
    r4 = agent_theme(rep.themes)
    r5 = agent_flow(rep.pool)
    rep.excluded.update(r3.data.get("flagged", {}))
    base = [r1, r2, r3, r4, r5]
    brief = _brief(base, [s for s in rep.pool if s["code"] not in rep.excluded])
    r6 = agent_debate(llm, brief, "bull")
    r7 = agent_debate(llm, brief, "bear")
    rep.bull, rep.bear = r6.data["items"], r7.data["items"]
    r8 = agent_pm(llm, brief, rep.bull, rep.bear, rep.pool, rep.excluded)
    rep.excluded.update(r8.data.get("exclude", {}))
    rep.aggression = r8.data.get("aggression", "normal")
    rep.watchlist = [Candidate(code=w["code"], name=w["name"], source="pm", pm_note=w.get("note", ""))
                     for w in r8.data["watchlist"] if w["code"] not in rep.excluded]
    rep.results = base + [r6, r7, r8]
    return rep
