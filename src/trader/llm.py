"""에이전트용 LLM 호출: Gemini(무료) 우선, 실패하면 Claude. JSON 응답을 파싱한다.

키 설정은 기존 브리핑과 같은 .env 의 GEMINI_API_KEY / ANTHROPIC_API_KEY 를 쓴다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import settings as _settings  # .env 를 먼저 읽게 함

_GEMINI_MIN_GAP = 13.0  # 무료 등급 분당 5회 제한
_MINUTE_COOLDOWN = 65.0  # 분당 한도 초과 → 잠깐만 쉼
# 기본 모델이 할당량을 다 쓰면 무료 한도가 따로인 가벼운 모델로 넘어간다
_GEMINI_BACKUPS = ["gemini-2.5-flash-lite", "gemini-2.0-flash"]
_DEFAULT_BUDGET = 18     # 하루 호출 예산 (무료 등급 기준, LLM_DAILY_BUDGET 으로 변경)
_RESERVE_HIGH = 5        # 장전 회의(우선순위 high) 몫으로 남겨 두는 횟수
_PT = ZoneInfo("America/Los_Angeles")  # 구글 할당량은 미국 태평양 시간 자정에 초기화


def _key(name: str) -> str:
    return os.getenv(name, "").strip().strip('"').strip("'")


def _is_quota(t: str) -> bool:
    return "429" in t or "RESOURCE_EXHAUSTED" in t or "quota" in t.lower() or "rate_limit" in t.lower()


def _short_error(e: Exception) -> str:
    t = str(e)
    if _is_quota(t):
        return "무료 사용량(할당량) 초과"
    if "API_KEY_INVALID" in t or "API key not valid" in t or "401" in t or "authentication" in t.lower():
        return "API 키가 틀림"
    if "403" in t or "PERMISSION_DENIED" in t:
        return "권한 없음(키 제한·지역 확인)"
    if "404" in t or "NOT_FOUND" in t:
        return "모델 이름을 찾을 수 없음"
    if "credit" in t.lower() or "billing" in t.lower():
        return "결제·크레딧 부족"
    return t.splitlines()[0][:80] if t else type(e).__name__


def quota_day(now: Optional[dt.datetime] = None) -> str:
    return (now or dt.datetime.now(_PT)).astimezone(_PT).strftime("%Y-%m-%d")


class LLM:
    def __init__(self, usage_path: Optional[Path] = None, budget: Optional[int] = None,
                 now_fn: Optional[Callable[[], dt.datetime]] = None):
        self.gemini_key = _key("GEMINI_API_KEY")
        self.claude_key = _key("ANTHROPIC_API_KEY")
        main = os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"
        self.gemini_models = [main] + [m for m in _GEMINI_BACKUPS if m != main]
        self.claude_model = os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-haiku-4-5"
        self.providers: List[str] = []
        if self.gemini_key:
            self.providers.append("gemini")
        if self.claude_key:
            self.providers.append("claude")
        try:
            env_budget = int(os.getenv("LLM_DAILY_BUDGET", "").strip() or _DEFAULT_BUDGET)
        except ValueError:
            env_budget = _DEFAULT_BUDGET
        self.budget = budget if budget is not None else env_budget
        self.usage_path = usage_path or (_settings.DATA_DIR / "llm_usage.json")
        self.now_fn = now_fn or (lambda: dt.datetime.now(_PT))
        self._clients: Dict[str, Any] = {}
        self._last_gemini = 0.0
        self._cooldown: Dict[str, float] = {}      # 모델 → 이 시각(time.time)까지 건너뜀
        self._dead_day: Dict[str, str] = {}        # 모델 → 하루 할당량을 다 쓴 날
        self._lock = threading.Lock()
        self.last_error = ""
        self.ok_calls = 0
        self.fail_calls = 0

    # ── 하루 사용량 (재시작해도 유지) ──
    def _day(self) -> str:
        return quota_day(self.now_fn())

    def used_today(self) -> int:
        try:
            return int(json.loads(self.usage_path.read_text(encoding="utf-8")).get(self._day(), 0))
        except Exception:  # noqa: BLE001
            return 0

    def _count(self) -> None:
        try:
            data = json.loads(self.usage_path.read_text(encoding="utf-8")) if self.usage_path.exists() else {}
        except Exception:  # noqa: BLE001
            data = {}
        d = self._day()
        data = {k: v for k, v in data.items() if k >= quota_day(self.now_fn() - dt.timedelta(days=14))}
        data[d] = int(data.get(d, 0)) + 1
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            self.usage_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def remaining(self) -> int:
        return max(0, self.budget - self.used_today())

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def status(self) -> str:
        """대시보드·로그에 보여줄 짧은 상태 (왜 LLM 의견이 없는지)."""
        if not self.providers:
            return "LLM 키 없음(.env 의 GEMINI_API_KEY 비어 있음)"
        use = f"오늘 {self.used_today()}/{self.budget}회 사용"
        if self.last_error and not self.ok_calls:
            return f"LLM 호출 실패: {self.last_error} · {use}"
        return f"LLM 정상 · {use}" if not self.last_error else f"LLM 일부 실패: {self.last_error} · {use}"

    def why_none(self) -> str:
        return "LLM 키 없음" if not self.providers else f"LLM 실패({self.last_error or '응답 없음'})"

    def _client(self, p: str):
        if p not in self._clients:
            if p == "gemini":
                from google import genai
                self._clients[p] = genai.Client(api_key=self.gemini_key)
            else:
                import anthropic
                self._clients[p] = anthropic.Anthropic(api_key=self.claude_key)
        return self._clients[p]

    def _targets(self) -> List[tuple]:
        out = [("gemini", m) for m in self.gemini_models] if "gemini" in self.providers else []
        if "claude" in self.providers:
            out.append(("claude", self.claude_model))
        return out

    def _call(self, p: str, model: str, system: str, prompt: str, max_tokens: int) -> Optional[str]:
        if p == "gemini":
            from google.genai import types
            gap = _GEMINI_MIN_GAP - (time.time() - self._last_gemini)
            if gap > 0:
                time.sleep(gap)
            cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                              response_mime_type="application/json")
            if "2.5" in model:
                cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
            try:
                resp = self._client(p).models.generate_content(model=model, contents=prompt, config=cfg)
            finally:
                self._last_gemini = time.time()
            return (resp.text or "").strip() or None
        resp = self._client(p).messages.create(model=model, max_tokens=max_tokens, system=system,
                                               messages=[{"role": "user", "content": prompt}])
        return "\n".join(b.text for b in resp.content if b.type == "text").strip() or None

    def json(self, system: str, prompt: str, max_tokens: int = 800, priority: str = "normal") -> Optional[Dict[str, Any]]:
        """JSON 객체를 돌려준다. 모든 모델이 실패하거나 오늘 예산이 없으면 None (이유는 last_error).
        priority='high'(장전 회의)는 예산 끝까지, 'normal' 은 장전 회의 몫을 남기고 쓴다."""
        system = system + "\n반드시 JSON 객체 하나만 출력한다. 설명이나 코드블록 표시는 쓰지 않는다."
        with self._lock:
            left = self.remaining()
            if left <= 0 or (priority != "high" and left <= _RESERVE_HIGH):
                self.last_error = f"오늘 AI 호출 예산 소진({self.budget}회)"
                self.fail_calls += 1
                return None
            day = self._day()
            for p, model in self._targets():
                if self._dead_day.get(model) == day or time.time() < self._cooldown.get(model, 0):
                    continue
                try:
                    self._count()
                    text = self._call(p, model, system, prompt, max_tokens)
                    parsed = parse_json(text)
                    if parsed is not None:
                        self.ok_calls += 1
                        self.last_error = ""
                        return parsed
                    self.last_error = "답이 JSON 형식이 아님(잘림)"
                    print(f"[llm] {model} JSON 파싱 실패: {str(text)[:120]}")
                except Exception as e:  # noqa: BLE001
                    self.last_error = _short_error(e)
                    raw = str(e)
                    if _is_quota(raw):
                        if "PerMinute" in raw or "per minute" in raw.lower():
                            self._cooldown[model] = time.time() + _MINUTE_COOLDOWN
                        else:
                            self._dead_day[model] = day      # 하루 할당량 → 오늘은 이 모델 그만
                    print(f"[llm] {model} 호출 실패 → {self.last_error} | {raw[:160]}")
            self.fail_calls += 1
        return None

    def selftest(self) -> str:
        """시작할 때 한 번: 실제 호출 없이(할당량 아끼기) 키·오늘 사용량만 알려준다."""
        if not self.providers:
            return "[LLM] 키 없음 → AI 의견 없이 규칙으로만 동작합니다 (.env 에 GEMINI_API_KEY 를 넣으세요)"
        return (f"[LLM] 키 있음 ({', '.join(self.providers)}) · 오늘 {self.used_today()}/{self.budget}회 사용 "
                f"(장전 회의 몫 {_RESERVE_HIGH}회 확보, 한도를 넘으면 데이터 기반으로 동작)")


def parse_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {"items": v}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


_shared: Optional[LLM] = None


def get_llm() -> LLM:
    global _shared
    if _shared is None:
        _shared = LLM()
    return _shared
