"""상태·에이전트 결과를 쉬운 문장으로 바꾼다 (대시보드 '지금 하는 일' 배너, 에이전트 말풍선).

순수 함수만 둔다 (테스트 대상).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

PHASES = [
    ("premarket", "장전 분석", "08:00"),
    ("scan", "종목 선정", "09:05"),
    ("intraday", "장중 감시", "09:05~15:15"),
    ("flatten", "마감 청산", "15:15"),
    ("review", "복기", "15:40"),
]

STATUS_LABEL = {
    "watch": "감시 중", "cooldown": "잠시 후 재검사", "pending": "승인 대기", "done": "거래 완료", "blocked": "오늘 제외",
}


def _hhmm(ts: Optional[str]) -> str:
    return ts[11:16] if ts and len(ts) >= 16 else ""


def heartbeat_age(heartbeat_ts: Optional[str], now: dt.datetime) -> Optional[float]:
    if not heartbeat_ts:
        return None
    try:
        t = dt.datetime.fromisoformat(heartbeat_ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=now.tzinfo)
    return (now - t).total_seconds()


def is_alive(phase_key: str, age: Optional[float]) -> bool:
    if age is None:
        return False
    limit = 600 if phase_key in ("premarket", "scan") else 120   # 장전 분석은 LLM 호출로 몇 분 걸림
    return age <= limit


def market_text(status: Dict[str, Any]) -> str:
    idx = status.get("index") or {}
    if not idx:
        return ""
    return f"코스피 {idx.get('KOSPI', 0):+.2f}% · 코스닥 {idx.get('KOSDAQ', 0):+.2f}%"


def now_text(phase_key: str, alive: bool, status: Dict[str, Any], inplay: List[Dict[str, Any]],
             now: dt.datetime) -> Dict[str, str]:
    """{"now": 지금 하는 일, "next": 다음에 할 일, "tone": ok|warn|stop|idle}"""
    hm = now.strftime("%H:%M")
    if not alive:
        if phase_key == "done":
            return {"now": "오늘 일정을 모두 마쳤어요. 아래에서 오늘 결과를 볼 수 있어요.",
                    "next": "내일 아침 08:00 전에 다시 켜 주세요 (자동실행 등록 시 07:55 자동 시작).", "tone": "idle"}
        return {"now": "트레이더가 꺼져 있거나 응답이 없어요.",
                "next": "scripts 폴더의 '모의투자_시작.bat' 을 더블클릭해 켜 주세요.", "tone": "stop"}
    positions = status.get("positions") or []
    pending = [i for i in inplay if i.get("status") == "pending"]
    watching = [i for i in inplay if i.get("status") in ("watch", "cooldown")]
    regime = status.get("regime") or {}
    if phase_key == "waiting":
        return {"now": f"장전 분석 시작(08:00)을 기다리는 중이에요. (지금 {hm})",
                "next": "08:00 에 에이전트 1~8번이 시장·뉴스·공시를 분석해요.", "tone": "idle"}
    if phase_key == "premarket":
        return {"now": "장전 분석팀(에이전트 1~8번)이 시장·뉴스·공시를 분석하고 관심종목을 고르는 중이에요.",
                "next": "09:05 에 장 초반 거래량으로 오늘 지켜볼 종목(Stocks in Play)을 정해요.", "tone": "ok"}
    if phase_key == "ready":
        return {"now": "장전 분석을 마쳤어요. 09:00 장 시작을 기다리는 중이에요.",
                "next": "09:00~09:05 시가범위를 만든 뒤, 거래량이 몰린 종목을 골라 감시를 시작해요.", "tone": "ok"}
    if phase_key == "scan":
        return {"now": "09:00~09:05 시가범위를 만드는 중이에요. 이 5분의 고가·저가가 오늘의 기준선이 돼요.",
                "next": "09:05 이후 거래량이 몰린 종목을 골라 감시를 시작해요.", "tone": "ok"}
    if phase_key == "intraday":
        if status.get("stopped"):
            return {"now": f"오늘 신규 매수를 멈췄어요 ({status.get('stop_reason', '')}).",
                    "next": "보유 종목은 손절·15:15 청산 규칙대로 관리해요." if positions else "15:15 이후 하루를 정리해요.",
                    "tone": "stop"}
        if pending:
            names = ", ".join(p["name"] for p in pending)
            return {"now": f"{names} 매수 승인을 기다리는 중이에요. 텔레그램에서 [매수]/[거절]을 눌러 주세요.",
                    "next": "3분 안에 응답이 없으면 자동 취소돼요.", "tone": "warn"}
        parts = []
        if positions:
            parts.append("보유 중: " + ", ".join(f"{p['name']} {p['qty']}주" for p in positions))
        if regime.get("decision") == "reject":
            parts.append(f"시장이 약해서({market_text(status)}) 신규 매수를 쉬는 중")
            nxt = "지수가 회복되면 돌파 종목을 다시 검사해요. 15:15 에 남은 보유분을 정리해요."
            tone = "warn"
        else:
            parts.append(f"{len(watching)}종목의 시가범위 돌파를 5초마다 지켜보는 중")
            nxt = "돌파가 나오면 에이전트들이 차례로 검사하고, 모두 통과하면 텔레그램으로 승인을 요청해요."
            tone = "ok"
        if not inplay:
            parts = ["오늘은 조건(거래량 급증 등)을 만족하는 종목이 없어서 관망 중"]
            nxt = "15:15 이후 하루를 정리해요."
        return {"now": " · ".join(parts) + ".", "next": nxt, "tone": tone}
    if phase_key == "flatten":
        return {"now": "15:15 장 마감 정리 중이에요. 보유 종목을 모두 팔아요.",
                "next": "15:40 에 오늘 하루를 복기하고 텔레그램으로 리포트를 보내요.", "tone": "ok"}
    if phase_key == "review":
        return {"now": "오늘 매매를 복기하는 중이에요 (15:40 이후).",
                "next": "리포트를 텔레그램으로 보내고 종료해요.", "tone": "ok"}
    return {"now": "오늘 일정을 마쳤어요.", "next": "내일 아침에 다시 시작해요.", "tone": "idle"}


def current_phase(phase_snap: Dict[str, Any], now: dt.datetime) -> str:
    key = (phase_snap or {}).get("key")
    if key:
        return key
    return "waiting" if now.strftime("%H%M") < "0800" else "done"


SUFFIX = {"pass": "👍", "reject": "✋", "wait": "⏳", "info": ""}


def agent_line(no: int, decision: str, reason: str) -> str:
    """에이전트 말풍선 문장."""
    reason = (reason or "").strip()
    if decision == "wait" and "앞 단계" in reason:
        return "앞에서 막혀서 저는 검사하지 않았어요."
    if no == 13 and decision == "reject":
        return f"{reason}. 지금은 사지 말자 {SUFFIX['reject']}"
    if no == 12 and decision == "reject":
        return f"악재가 보여요: {reason} {SUFFIX['reject']}"
    if no == 15 and decision == "pass":
        return f"한도 안이에요. {reason} {SUFFIX['pass']}"
    return f"{reason} {SUFFIX.get(decision, '')}".strip()


def event_text(kind: str, text: str) -> str:
    icon = {"체결": "✅", "매수": "🛒", "매도": "💰", "거부": "🚫", "신호": "📈", "중단": "⏸", "오류": "⚠️"}.get(kind, "ℹ️")
    return f"{icon} {text}"
