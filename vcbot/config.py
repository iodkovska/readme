"""Runtime configuration, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _int_set(raw: str) -> set[int]:
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str | None
    model: str = "claude-opus-5"
    effort: str = "high"
    data_dir: Path = Path("./data")
    allowed_user_ids: set[int] = field(default_factory=set)
    max_source_chars: int = 60_000

    # Telegram's Bot API refuses to hand out files larger than 20 MB.
    max_file_bytes: int = 20 * 1024 * 1024

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def deals_dir(self) -> Path:
        return self.data_dir / "deals"

    def is_allowed(self, user_id: int) -> bool:
        return not self.allowed_user_ids or user_id in self.allowed_user_ids


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    cfg = Config(
        telegram_token=token,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5").strip(),
        effort=os.environ.get("ANTHROPIC_EFFORT", "high").strip(),
        data_dir=Path(os.environ.get("DATA_DIR", "./data")).expanduser(),
        allowed_user_ids=_int_set(os.environ.get("ALLOWED_USER_IDS", "")),
        max_source_chars=int(os.environ.get("MAX_SOURCE_CHARS", "60000")),
    )
    cfg.files_dir.mkdir(parents=True, exist_ok=True)
    cfg.deals_dir.mkdir(parents=True, exist_ok=True)
    return cfg
