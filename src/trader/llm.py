"""에이전트용 LLM 호출: Gemini(무료) 우선, 실패하면 Claude. JSON 응답을 파싱한다.

키 설정은 기존 브리핑과 같은 .env 의 GEMINI_API_KEY / ANTHROPIC_API_KEY 를 쓴다.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional

from ..config import config

_GEMINI_MIN_GAP = 13.0  # 무료 등급 분당 5회 제한


class LLM:
    def __init__(self):
        self.providers: List[str] = []
        if config.gemini_api_key:
            self.providers.append("gemini")
        if config.anthropic_api_key:
            self.providers.append("claude")
        self._clients: Dict[str, Any] = {}
        self._last_gemini = 0.0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def _client(self, p: str):
        if p not in self._clients:
            if p == "gemini":
                from google import genai
                self._clients[p] = genai.Client(api_key=config.gemini_api_key)
            else:
                import anthropic
                self._clients[p] = anthropic.Anthropic(api_key=config.anthropic_api_key)
        return self._clients[p]

    def _call(self, p: str, system: str, prompt: str, max_tokens: int) -> Optional[str]:
        if p == "gemini":
            from google.genai import types
            gap = _GEMINI_MIN_GAP - (time.time() - self._last_gemini)
            if gap > 0:
                time.sleep(gap)
            cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                              response_mime_type="application/json")
            if "2.5" in config.gemini_model:
                cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
            try:
                resp = self._client(p).models.generate_content(model=config.gemini_model, contents=prompt, config=cfg)
            finally:
                self._last_gemini = time.time()
            return (resp.text or "").strip() or None
        resp = self._client(p).messages.create(model=config.anthropic_model, max_tokens=max_tokens, system=system,
                                               messages=[{"role": "user", "content": prompt}])
        return "\n".join(b.text for b in resp.content if b.type == "text").strip() or None

    def json(self, system: str, prompt: str, max_tokens: int = 800) -> Optional[Dict[str, Any]]:
        """JSON 객체를 돌려준다. 모든 제공자가 실패하면 None."""
        system = system + "\n반드시 JSON 객체 하나만 출력한다. 설명이나 코드블록 표시는 쓰지 않는다."
        with self._lock:
            for p in self.providers:
                try:
                    text = self._call(p, system, prompt, max_tokens)
                    parsed = parse_json(text)
                    if parsed is not None:
                        return parsed
                    print(f"[llm] {p} JSON 파싱 실패: {str(text)[:120]}")
                except Exception as e:  # noqa: BLE001
                    print(f"[llm] {p} 호출 실패: {e}")
        return None


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
