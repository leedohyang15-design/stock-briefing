"""트레이더 설정: config/trader.yaml + 환경변수(.env)."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "trader.yaml"
DATA_DIR = Path(os.getenv("TRADER_DATA_DIR", str(ROOT / "data")))

# 주간 업데이트가 바꿀 수 있는 파라미터가 어느 섹션에 있는지
_PARAM_SECTIONS = ("strategy", "risk", "timemachine")


def _env(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return v.strip() if v and v.strip() else default


@dataclass
class Secrets:
    kis_app_key: str = field(default_factory=lambda: _env("KIS_APP_KEY"))
    kis_app_secret: str = field(default_factory=lambda: _env("KIS_APP_SECRET"))
    kis_account: str = field(default_factory=lambda: _env("KIS_ACCOUNT"))  # 12345678-01
    kis_env: str = field(default_factory=lambda: _env("KIS_ENV", "real"))  # real | mock
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))

    @property
    def has_kis(self) -> bool:
        return bool(self.kis_app_key and self.kis_app_secret and self.kis_account)

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    @property
    def account_parts(self):
        acct = self.kis_account.replace("-", "")
        return acct[:8], (acct[8:10] or "01")


class Settings:
    """yaml 설정을 감싼 객체. s.strategy['orb_minutes'] 처럼 섹션 딕셔너리로 접근."""

    def __init__(self, data: Dict[str, Any], path: Optional[Path] = None):
        self.data = data
        self.path = path
        self.secrets = Secrets()

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {}, path)

    def __getattr__(self, name: str) -> Dict[str, Any]:
        if name in ("data", "path", "secrets"):
            raise AttributeError(name)
        return self.data.get(name, {})

    @property
    def version(self) -> int:
        return int(self.data.get("version", 1))

    # ── 주간 업데이트용 파라미터 접근 ──
    def get_param(self, name: str) -> Any:
        for sec in _PARAM_SECTIONS:
            if name in self.data.get(sec, {}):
                return self.data[sec][name]
        raise KeyError(name)

    def with_params(self, changes: Dict[str, Any]) -> "Settings":
        new = copy.deepcopy(self.data)
        for name, val in changes.items():
            for sec in _PARAM_SECTIONS:
                if name in new.get(sec, {}):
                    new[sec][name] = val
                    break
            else:
                raise KeyError(name)
        s = Settings(new, self.path)
        s.secrets = self.secrets
        return s

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False)

    def save(self, path: Optional[Path] = None) -> None:
        p = path or self.path or CONFIG_PATH
        header = "# AI 단타 트레이딩 설정 (README_TRADER.md 참고). 주간 업데이트로 자동 갱신됨.\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(header + self.to_yaml())
