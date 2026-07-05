"""환경변수 로드 및 전역 설정.

로컬 실행 시에는 프로젝트 루트의 `.env` 파일을,
GitHub Actions 등 CI 환경에서는 주입된 환경변수를 그대로 사용한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

# 윈도우 한글 사용자명 → yfinance SSL 인증서 경로 문제 보정 (import 시 1회 실행).
# 반드시 yfinance 요청 전에 실행되어야 하므로 가장 먼저 import 한다.
from . import _ssl_bootstrap  # noqa: F401

from dotenv import load_dotenv

# 로컬 .env 로드 (CI 에서는 파일이 없어도 무시됨)
load_dotenv()


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip())
    except (ValueError, AttributeError):
        return default


@dataclass
class Config:
    # LLM — Gemini(무료) 또는 Claude. 둘 다 있으면 Gemini 우선.
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip())
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5").strip())

    # SMTP
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com").strip())
    smtp_port: int = field(default_factory=lambda: _get_int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", "").strip())
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", "").strip())
    mail_from_name: str = field(default_factory=lambda: os.getenv("MAIL_FROM_NAME", "데일리 주식 브리핑").strip())

    # 카카오톡 '나에게 보내기' (메모 API) — 무료. 세팅은 scripts/kakao_auth.py 참고.
    kakao_rest_key: str = field(default_factory=lambda: os.getenv("KAKAO_REST_KEY", "").strip())
    kakao_refresh_token: str = field(default_factory=lambda: os.getenv("KAKAO_REFRESH_TOKEN", "").strip())
    # Client Secret 을 '사용함'으로 켠 경우에만 필요 (기본 빈 값이면 미전송).
    kakao_client_secret: str = field(default_factory=lambda: os.getenv("KAKAO_CLIENT_SECRET", "").strip())
    kakao_redirect_uri: str = field(
        default_factory=lambda: os.getenv("KAKAO_REDIRECT_URI", "https://localhost").strip()
    )

    @property
    def mail_to(self) -> List[str]:
        raw = os.getenv("MAIL_TO", "").strip()
        return [addr.strip() for addr in raw.split(",") if addr.strip()]

    @property
    def llm_provider(self) -> Optional[str]:
        """사용할 LLM 제공자. Gemini(무료) 우선, 없으면 Claude, 둘 다 없으면 None."""
        if self.gemini_api_key:
            return "gemini"
        if self.anthropic_api_key:
            return "claude"
        return None

    @property
    def has_llm(self) -> bool:
        return self.llm_provider is not None

    @property
    def kakao_enabled(self) -> bool:
        """카카오 '나에게 보내기'에 필요한 키가 모두 있으면 True."""
        return bool(self.kakao_rest_key and self.kakao_refresh_token)

    @property
    def has_email(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.mail_to)

    def validate_for_send(self) -> None:
        """이메일 발송에 필요한 최소 설정이 갖춰졌는지 검증."""
        missing = []
        if not self.smtp_user:
            missing.append("SMTP_USER")
        if not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        if not self.mail_to:
            missing.append("MAIL_TO")
        if missing:
            raise RuntimeError(
                f"이메일 발송에 필요한 환경변수가 없습니다: {', '.join(missing)} "
                f"(.env 또는 GitHub Secrets 확인)"
            )


# 싱글턴처럼 임포트해서 사용
config = Config()
