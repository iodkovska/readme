"""Per-chat deal state: what the analyst has been given so far.

One JSON file per chat under ``<data_dir>/deals``. Small enough that a file per
chat beats pulling in a database, and it survives a bot restart mid-deal.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# What the bot is waiting for after a button press. ``None`` means nothing in
# particular, and incoming files are routed by their type instead.
AWAIT_PITCH_DECK = "pitch_deck"
AWAIT_FIN_MODEL = "fin_model"
AWAIT_WEBSITE = "website"
AWAIT_NOTES = "notes"


@dataclass
class Attachment:
    """A file the user uploaded, kept on disk next to its metadata."""

    kind: str  # AWAIT_PITCH_DECK or AWAIT_FIN_MODEL
    file_name: str
    path: str
    mime: str
    size: int
    added_at: float = field(default_factory=time.time)

    @property
    def suffix(self) -> str:
        return Path(self.file_name).suffix.lower()


@dataclass
class Deal:
    chat_id: int
    company: str = ""
    decks: list[Attachment] = field(default_factory=list)
    models: list[Attachment] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    awaiting: str | None = None
    updated_at: float = field(default_factory=time.time)

    def has_material(self) -> bool:
        return bool(self.decks or self.models or self.websites or self.notes)

    def summary_lines(self) -> list[str]:
        """Human-readable inventory, used by /status and the main menu."""
        def mark(items: list) -> str:
            return "✅" if items else "⬜"

        lines = [
            f"{mark(self.decks)} Pitch deck — {len(self.decks)} file(s)",
            f"{mark(self.models)} Financial model — {len(self.models)} file(s)",
            f"{mark(self.websites)} Website — {len(self.websites)} link(s)",
            f"{mark(self.notes)} Additional info — {len(self.notes)} note(s)",
        ]
        for att in self.decks + self.models:
            lines.append(f"    • {att.file_name}")
        for url in self.websites:
            lines.append(f"    • {url}")
        return lines


class DealStore:
    """Loads and saves :class:`Deal` records as JSON."""

    def __init__(self, deals_dir: Path) -> None:
        self.deals_dir = deals_dir
        self.deals_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chat_id: int) -> Path:
        return self.deals_dir / f"{chat_id}.json"

    def load(self, chat_id: int) -> Deal:
        path = self._path(chat_id)
        if not path.exists():
            return Deal(chat_id=chat_id)
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt state file should not brick the chat.
            return Deal(chat_id=chat_id)
        return Deal(
            chat_id=raw.get("chat_id", chat_id),
            company=raw.get("company", ""),
            decks=[Attachment(**a) for a in raw.get("decks", [])],
            models=[Attachment(**a) for a in raw.get("models", [])],
            websites=list(raw.get("websites", [])),
            notes=list(raw.get("notes", [])),
            awaiting=raw.get("awaiting"),
            updated_at=raw.get("updated_at", time.time()),
        )

    def save(self, deal: Deal) -> None:
        deal.updated_at = time.time()
        path = self._path(deal.chat_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(deal), indent=2), "utf-8")
        tmp.replace(path)

    def reset(self, chat_id: int) -> Deal:
        self._path(chat_id).unlink(missing_ok=True)
        return Deal(chat_id=chat_id)
