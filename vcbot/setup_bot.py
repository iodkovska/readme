"""Register the bot's profile with Telegram: commands, menu button, description.

The in-chat keyboard (📊 Add pitch deck, and so on) is sent with each message by
`bot.py` and needs no registration. This script configures the parts that live on
Telegram's servers and persist whether or not the bot is running:

- the command list behind the blue Menu button and the `/` autocomplete
- what the Menu button does
- the "What can this bot do?" text new users see before pressing Start
- the short description shown on the bot's profile card

Safe to re-run; every call overwrites the previous value.

    python -m vcbot.setup_bot          # apply
    python -m vcbot.setup_bot --show   # print what Telegram currently has
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

API = "https://api.telegram.org"

# Shown in the Menu button and in `/` autocomplete, in this order.
COMMANDS = [
    ("start", "Start a new deal and show the buttons"),
    ("memo", "Research, score, and return the memo"),
    ("status", "What I've collected for this deal"),
    ("company", "Name the company: /company Acme Robotics"),
    ("reset", "Clear everything and start a new deal"),
    ("help", "How to use this bot"),
]

# Telegram caps these: 512 chars for the description, 120 for the short one.
DESCRIPTION = (
    "I'm a VC analyst. Send me a startup's pitch deck, financial model, website "
    "and any notes you have. I read the deck as rendered pages, interrogate the "
    "financial model's formulas, and search public sources for market sizing, "
    "product positioning, team qualifications and competitors.\n\n"
    "You get back the fund's scoring memo as a Word document: ten categories "
    "scored out of 30, the deal facts, pros and risks, and the nine detail "
    "sections — with the evidence behind every score.\n\n"
    "Press Start to begin."
)

SHORT_DESCRIPTION = (
    "Send a pitch deck, financial model and website — get back a scored VC "
    "investment memo as a Word document."
)


class TelegramError(RuntimeError):
    pass


def call(token: str, method: str, payload: dict | None = None) -> dict:
    """Call one Bot API method, raising on Telegram's own error envelope."""
    response = httpx.post(f"{API}/bot{token}/{method}", json=payload or {}, timeout=30.0)
    try:
        body = response.json()
    except ValueError as exc:  # pragma: no cover - only on a non-JSON gateway error
        raise TelegramError(f"{method}: HTTP {response.status_code}") from exc

    if not body.get("ok"):
        description = body.get("description", "unknown error")
        # 401 means the token itself is wrong; say so plainly rather than echoing it.
        if response.status_code == 401:
            raise TelegramError(
                "Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN in .env — "
                "a regenerated token invalidates the old one."
            )
        raise TelegramError(f"{method}: {description}")
    return body["result"]


def apply(token: str) -> dict:
    """Push commands, menu button and descriptions. Returns getMe for confirmation."""
    me = call(token, "getMe")

    call(
        token,
        "setMyCommands",
        {"commands": [{"command": c, "description": d} for c, d in COMMANDS]},
    )
    call(token, "setChatMenuButton", {"menu_button": {"type": "commands"}})
    call(token, "setMyDescription", {"description": DESCRIPTION})
    call(token, "setMyShortDescription", {"short_description": SHORT_DESCRIPTION})
    return me


def show(token: str) -> None:
    me = call(token, "getMe")
    print(f"bot: @{me.get('username')} ({me.get('first_name')}) id={me.get('id')}")
    print(f"  can join groups:      {me.get('can_join_groups')}")
    print(f"  reads all messages:   {me.get('can_read_all_group_messages')}")
    print(f"  inline mode:          {me.get('supports_inline_queries')}")

    print("\ncommands registered:")
    for command in call(token, "getMyCommands") or []:
        print(f"  /{command['command']:<9} {command['description']}")

    button = call(token, "getChatMenuButton")
    print(f"\nmenu button: {button.get('type')}")

    description = call(token, "getMyDescription").get("description", "")
    short = call(token, "getMyShortDescription").get("short_description", "")
    print(f"\ndescription ({len(description)} chars):\n  " + description.replace("\n", "\n  "))
    print(f"\nshort description ({len(short)} chars):\n  {short}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vcbot.setup_bot")
    parser.add_argument(
        "--show", action="store_true", help="Print the current configuration instead of applying"
    )
    args = parser.parse_args(argv)

    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set. Fill it in in .env.", file=sys.stderr)
        return 1

    try:
        if args.show:
            show(token)
        else:
            me = apply(token)
            print(f"Configured @{me.get('username')}:")
            print(f"  {len(COMMANDS)} commands registered")
            print("  menu button set to the command list")
            print("  description and short description set")
            print("\nThe in-chat buttons appear when a user sends /start.")
    except TelegramError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"Could not reach Telegram: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
