"""Produce a scoring memo from the command line, without Telegram.

Useful for a deal that arrives as files on disk, for running several in a batch,
and for exercising the full pipeline when debugging.

    python -m vcbot.cli --deck deck.pdf --model model.xlsx --url https://acme.com \\
        --note "Intro came from an angel" --out memo.docx
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .analyst import Analyst
from .config import Config, load_config
from .docx_memo import build_docx, filename_for
from .errors import friendly_error
from .memo import render_chat
from .state import Attachment, Deal

log = logging.getLogger(__name__)


def build_deal(args: argparse.Namespace) -> Deal:
    deal = Deal(chat_id=0, company=args.company or "")
    for path in args.deck or []:
        deal.decks.append(_attachment("pitch_deck", path))
    for path in args.model or []:
        deal.models.append(_attachment("fin_model", path))
    deal.websites.extend(args.url or [])
    deal.notes.extend(args.note or [])
    for path in args.note_file or []:
        deal.notes.append(Path(path).read_text("utf-8", errors="replace"))
    return deal


def _attachment(kind: str, path: str) -> Attachment:
    file = Path(path).expanduser().resolve()
    if not file.exists():
        raise SystemExit(f"No such file: {file}")
    return Attachment(
        kind=kind,
        file_name=file.name,
        path=str(file),
        mime="",
        size=file.stat().st_size,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m vcbot.cli",
        description="Write a scoring memo from a startup's materials.",
    )
    parser.add_argument("--deck", action="append", metavar="FILE", help="Pitch deck (repeatable)")
    parser.add_argument("--model", action="append", metavar="FILE", help="Financial model (repeatable)")
    parser.add_argument("--url", action="append", metavar="URL", help="Website (repeatable)")
    parser.add_argument("--note", action="append", metavar="TEXT", help="Additional info (repeatable)")
    parser.add_argument("--note-file", action="append", metavar="FILE", help="Additional info from a file")
    parser.add_argument("--company", help="Company name, if the materials are ambiguous")
    parser.add_argument("--out", metavar="FILE", help="Where to write the .docx (default: derived from the company name)")
    parser.add_argument("--no-research", action="store_true", help="Skip the web research pass")
    parser.add_argument("--quiet", action="store_true", help="Only print the output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)-7s %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    deal = build_deal(args)
    if not deal.has_material():
        raise SystemExit(
            "Nothing to score. Pass at least one of --deck, --model, --url, --note."
        )

    cfg = _config_for(args)

    try:
        result = Analyst(cfg).score(deal)
    except Exception as exc:  # noqa: BLE001 - the CLI reports, it does not traceback
        print(f"Could not write the memo: {friendly_error(exc)}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    out = Path(args.out).expanduser() if args.out else Path(filename_for(result.memo))
    out.write_bytes(
        build_docx(result.memo, research=result.research, sources=result.sources).getvalue()
    )

    if not args.quiet:
        print()
        print(render_chat(result.memo))
        print()
    print(out)
    return 0


def _config_for(args: argparse.Namespace) -> Config:
    """Load config from the environment, with the CLI's overrides applied.

    `load_config` requires a Telegram token because the bot cannot run without
    one; the CLI never touches Telegram, so a placeholder stands in when the
    environment has no token set.
    """
    import os

    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "cli-unused")
    cfg = load_config()
    if args.no_research:
        cfg = replace_research(cfg, False)
    return cfg


def replace_research(cfg: Config, enabled: bool) -> Config:
    """Config is frozen, so an override means a copy."""
    import dataclasses

    return dataclasses.replace(cfg, enable_web_research=enabled)


if __name__ == "__main__":
    raise SystemExit(main())
