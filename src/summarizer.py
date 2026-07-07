"""LLM 기반 요약 로직 (프롬프트 체인) — Gemini(무료) 또는 Claude 지원.

각 섹션의 원본 데이터를 '개인 투자자가 읽기 쉬운 형태'로 요약한다.
- 제공자 우선순위: GEMINI_API_KEY(무료) > ANTHROPIC_API_KEY
- 아무 키도 없거나 호출이 실패하면 LLM 없이 원본 데이터를 그대로 쓰는
  폴백으로 우회한다 (요구사항: 키 없이도 브리핑이 발송되어야 함).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .config import config

_SYSTEM = (
    "너는 개인(개미) 투자자를 위한 데일리 주식 브리핑 에디터다. "
    "전문 용어를 남발하지 말고, 초보 투자자도 출근길에 1분 안에 이해할 수 있도록 "
    "군더더기 없이 핵심만 짧게 한국어로 정리한다. 과장·추천·매수/매도 권유는 하지 않는다."
)


class _LLM:
    """제공자(Gemini/Claude)를 감싸는 얇은 래퍼."""

    def __init__(self, provider: str):
        self.provider = provider
        self._client = None
        try:
            if provider == "gemini":
                from google import genai

                self._client = genai.Client(api_key=config.gemini_api_key)
            elif provider == "claude":
                import anthropic

                self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        except Exception as e:  # noqa: BLE001
            print(f"[summarizer] {provider} 클라이언트 생성 실패: {e}")
            self._client = None

    def complete(self, user_prompt: str, max_tokens: int = 400) -> Optional[str]:
        if self._client is None:
            return None
        try:
            if self.provider == "gemini":
                from google.genai import types

                cfg = types.GenerateContentConfig(
                    system_instruction=_SYSTEM, max_output_tokens=max_tokens
                )
                # 2.5 계열은 기본 '생각(thinking)' 토큰이 출력 한도를 잠식해
                # 문장이 잘릴 수 있어 thinking 을 끈다.
                if "2.5" in config.gemini_model:
                    cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
                resp = self._client.models.generate_content(
                    model=config.gemini_model, contents=user_prompt, config=cfg,
                )
                return (resp.text or "").strip() or None

            resp = self._client.messages.create(
                model=config.anthropic_model,
                max_tokens=max_tokens,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
            parts = [b.text for b in resp.content if b.type == "text"]
            return "\n".join(parts).strip() or None
        except Exception as e:  # noqa: BLE001
            print(f"[summarizer] LLM 호출 실패, 폴백 사용: {e}")
            return None


def _client() -> Optional["_LLM"]:
    provider = config.llm_provider
    if provider is None:
        return None
    llm = _LLM(provider)
    return llm if llm._client is not None else None


# Gemini 무료 등급은 분당 5회(5 RPM) 제한이 있어, 연속 호출이 몰리면 429 로 실패한다.
# 호출 사이에 최소 간격을 둬 한도를 넘지 않게 한다. (하루 1회 실행이라 지연은 무의미)
import time as _time

_last_llm_call = [0.0]
_MIN_GAP_SEC = 13.0  # 60초 / 5회 = 12초 → 여유 두어 13초


def _complete(client: "_LLM", prompt: str, max_tokens: int = 400) -> Optional[str]:
    if client.provider == "gemini":
        gap = _MIN_GAP_SEC - (_time.time() - _last_llm_call[0])
        if gap > 0:
            _time.sleep(gap)
    out = client.complete(prompt, max_tokens)
    _last_llm_call[0] = _time.time()
    return out


def _parse_numbered(out: str) -> Dict[int, str]:
    """'1. 내용' 형태의 여러 줄을 {번호: 내용} 으로 파싱."""
    result: Dict[int, str] = {}
    for raw in out.splitlines():
        line = raw.strip()
        if not line or "." not in line[:4]:
            continue
        num, _, body = line.partition(".")
        if num.strip().isdigit() and body.strip():
            result[int(num.strip())] = body.strip()
    return result


# ── 섹션 1: 지수 & 환율 관전 포인트 (💡 한 줄) ────────────
def summarize_indices_comment(plain_lines: List[str]) -> str:
    """지수·환율 데이터를 바탕으로 '관전 포인트' 코멘트만 반환 (수치 나열·인사말 금지)."""
    if not plain_lines:
        return "주요 지수·환율 데이터를 불러오지 못했습니다."
    body = "\n".join(plain_lines)
    client = _client()
    if client:
        prompt = (
            "다음은 국내·해외 주요 지수와 원/달러 환율의 전일 대비 등락이다.\n"
            f"{body}\n\n"
            "이 흐름을 바탕으로 '오늘 국내 증시 관전 포인트'를 2문장으로 정리하라. "
            "인사말·머리말·수치 나열은 하지 말고, 완결된 문장으로 관전 포인트만 써라."
        )
        out = _complete(client, prompt, max_tokens=400)
        if out:
            return out
    return "간밤 지수 흐름을 참고해 오늘 시장 대응에 유의하세요."


# ── 섹션 2: 테마 그룹별 원인 분석 (🔍 원인 분석) ──────────
def annotate_theme_summaries(groups) -> None:
    """각 ThemeGroup 의 .summary 를 '원인 분석'으로 채운다. 실패 시 None 유지."""
    client = _client()
    if not client or not groups:
        return
    listing = "\n".join(
        f"{i + 1}. {g.name} (평균 {g.label}) — "
        + ", ".join(f"{s.name} {s.change_pct:+.2f}%" for s in g.stocks)
        for i, g in enumerate(groups)
    )
    prompt = (
        "다음은 오늘 국내 증시에서 등락률 상위에 오른 '테마(섹터)'와 그 대표 종목의 등락률이다.\n"
        f"{listing}\n\n"
        "각 테마가 오늘 '왜' 그렇게 오르거나 내렸는지 원인을 분석하라. "
        "정책·뉴스·실적·수급·업황·매크로(금리·환율·유가) 등 핵심 동인을 짚어 "
        "개인 투자자가 이해하기 쉽게 2문장으로 설명하라. "
        f"반드시 테마 수({len(groups)}개)만큼 '번호. 분석내용' 형태로 줄바꿈해 출력하고, "
        "각 문장은 절대 도중에 끊지 말고 완결된 문장으로 마무리하라. "
        "확실치 않으면 '단기 테마성 수급'처럼 신중히 쓰고, 매수/매도 권유는 금지.\n"
        "예)\n1. 국제 유가 급등으로 정제마진 개선 기대가 커지며 정유주가 일제히 상승했다.\n"
        "2. 신규 상장주에 단기 수급이 몰리며 관련 종목이 강세를 보였으나 변동성은 크다."
    )
    out = _complete(client, prompt, max_tokens=2000)
    if not out:
        return
    causes = _parse_numbered(out)
    for i, g in enumerate(groups):
        if (i + 1) in causes:
            g.summary = causes[i + 1]


# ── 섹션 2: 종목별 등락 원인 (항목 옆 한 줄) ──────────────
def annotate_stock_reasons(groups) -> None:
    """각 종목(Stock)의 .reason 을 채운다. 전 종목을 1회 호출로 배치 처리."""
    client = _client()
    if not client or not groups:
        return
    pairs = [(g, s) for g in groups for s in g.stocks if s.ok]
    if not pairs:
        return
    listing = "\n".join(
        f"{i + 1}. {s.name} [{g.name}] {s.change_pct:+.2f}%"
        for i, (g, s) in enumerate(pairs)
    )
    prompt = (
        "다음은 테마별 개별 종목의 전일 등락률이다.\n"
        f"{listing}\n\n"
        f"각 종목이 그렇게 움직인 이유를 개인 투자자 눈높이에서 아주 짧게(15자 내외) "
        f"한 줄로 추정하라. 반드시 종목 수({len(pairs)}개)만큼 '번호. 이유' 형태로만 "
        "줄바꿈해 출력하라. 확실치 않으면 '테마 동반 등락'·'보합권 등락' 정도로 신중히 쓰고, "
        "매수/매도 권유는 하지 말 것.\n예)\n1. 실적 기대에 강세\n2. 차익실현 매물 출회"
    )
    out = _complete(client, prompt, max_tokens=1500)
    if not out:
        return
    reasons = _parse_numbered(out)
    for i, (_, s) in enumerate(pairs):
        if (i + 1) in reasons:
            s.reason = reasons[i + 1]


# ── 섹션 2 보조: 기타 급등 테마 원인 ─────────────────────
def annotate_hot_theme_causes(themes) -> None:
    """각 HotTheme 의 .cause 를 채운다 (급등 원인 1줄). 실패 시 None 유지."""
    client = _client()
    if not client or not themes:
        return
    listing = "\n".join(
        f"{i + 1}. {t.name} (+{t.change_pct:.2f}%)"
        + (f", 주도주: {', '.join(t.leaders)}" if t.leaders else "")
        for i, t in enumerate(themes)
    )
    prompt = (
        "다음은 오늘 시장에서 갑자기 급등한 테마 목록이다.\n"
        f"{listing}\n\n"
        f"각 테마가 왜 급등했는지 개인 투자자 눈높이에서 '한 줄'로 분석하라. "
        f"반드시 테마 수({len(themes)}개)만큼 '번호. 원인' 형태로만 줄바꿈해 출력하라. "
        "확실치 않으면 '단기 테마성 수급 유입' 정도로 신중히 쓰고, 매수 권유는 하지 말 것.\n"
        "예)\n1. 신소재 상용화 기대감에 단기 수급 집중\n2. 정부 정책 발표 기대에 관련주 동반 강세"
    )
    out = _complete(client, prompt, max_tokens=400)
    if not out:
        return
    causes = _parse_numbered(out)
    for i, t in enumerate(themes):
        if (i + 1) in causes:
            t.cause = causes[i + 1]


# ── 섹션 4: 일정 & 리스크 ─────────────────────────────────
def summarize_calendar(plain_lines: List[str]) -> str:
    if not plain_lines:
        return "오늘 특별히 주의할 주요 일정은 없습니다. (그래도 뇌동매매는 금물!)"
    body = "\n".join(plain_lines)
    client = _client()
    if client:
        prompt = (
            "다음은 오늘부터 향후 7일 내 예정된 주요 경제 일정 및 리스크다. "
            "각 줄 앞의 [오늘]/[D-3] 은 며칠 뒤인지를 뜻한다.\n"
            f"{body}\n\n"
            "개인 투자자가 물리거나 뇌동매매하지 않도록, 각 항목을 왜 조심해야 하는지 "
            "한 줄씩 짧게 풀어 설명하라. 맨 앞의 [오늘]/[D-n] 표기는 그대로 유지하고, "
            "항목별로 줄바꿈하라."
        )
        out = _complete(client, prompt, max_tokens=600)
        if out:
            return out
    return body


if __name__ == "__main__":
    print("LLM 사용 가능:", config.has_llm, "| 제공자:", config.llm_provider)
    print(summarize_indices_comment(["[국내] 코스피: 2,600.00 (▲ +0.50%)"]))
