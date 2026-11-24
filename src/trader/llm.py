"""에이전트용 LLM 호출: Gemini(무료) 우선, 실패하면 Claude. JSON 응답을 파싱한다.

키 설정은 기존 브리핑과 같은 .env 의 GEMINI_API_KEY / ANTHROPIC_API_KEY 를 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

from . import settings as _settings  # noqa: F401  (프로젝트 폴더 .env 를 먼저 읽게 함)

_GEMINI_MIN_GAP = 13.0  # 무료 등급 분당 5회 제한
_QUOTA_COOLDOWN = 600.0  # 할당량 초과(429) 뒤 이 시간 동안 그 모델은 건너뜀
# 기본 모델이 할당량을 다 쓰면 무료 한도가 더 넉넉한 가벼운 모델로 넘어간다
_GEMINI_BACKUPS = ["gemini-2.5-flash-lite", "gemini-2.0-flash"]


def _key(name: str) -> str:
    return os.getenv(name, "").strip().strip('"').strip("'")


def _short_error(e: Exception) -> str:
    t = str(e)
    if "429" in t or "RESOURCE_EXHAUSTED" in t or "quota" in t.lower() or "rate_limit" in t.lower():
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


class LLM:
    def __init__(self):
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
        self._clients: Dict[str, Any] = {}
        self._last_gemini = 0.0
        self._cooldown: Dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_error = ""
        self.ok_calls = 0
        self.fail_calls = 0

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def status(self) -> str:
        """대시보드·로그에 보여줄 짧은 상태 (왜 LLM 의견이 없는지)."""
        if not self.providers:
            return "LLM 키 없음(.env 의 GEMINI_API_KEY 비어 있음)"
        if self.last_error and not self.ok_calls:
            return f"LLM 호출 실패: {self.last_error}"
        return "LLM 정상" if not self.last_error else f"LLM 일부 실패: {self.last_error}"

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

    def json(self, system: str, prompt: str, max_tokens: int = 800) -> Optional[Dict[str, Any]]:
        """JSON 객체를 돌려준다. 모든 모델이 실패하면 None (이유는 last_error)."""
        system = system + "\n반드시 JSON 객체 하나만 출력한다. 설명이나 코드블록 표시는 쓰지 않는다."
        with self._lock:
            for p, model in self._targets():
                if time.time() < self._cooldown.get(model, 0):
                    continue
                try:
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
                    if "할당량" in self.last_error:
                        self._cooldown[model] = time.time() + _QUOTA_COOLDOWN
                    print(f"[llm] {model} 호출 실패 → {self.last_error} | {str(e)[:160]}")
            self.fail_calls += 1
        return None

    def selftest(self) -> str:
        """시작할 때 한 번: 정말 답이 오는지 확인하고 사람이 읽을 한 줄을 돌려준다."""
        if not self.providers:
            return "[LLM] 키 없음 → AI 의견 없이 규칙으로만 동작합니다 (.env 에 GEMINI_API_KEY 를 넣으세요)"
        out = self.json("점검", '{"ok": true} 를 그대로 출력하라.', 50)
        if out is not None:
            return "[LLM] 정상 연결 (" + ", ".join(self.providers) + ")"
        return f"[LLM] 연결 실패: {self.last_error} → AI 의견 없이 규칙으로만 동작합니다"


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
