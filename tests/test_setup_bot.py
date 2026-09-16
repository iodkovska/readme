"""The Telegram profile configuration: correct methods, payloads, and limits.

Telegram is unreachable from CI, so the HTTP layer is stubbed. These tests check
the things that would otherwise only fail against the live API: method names,
payload shapes, and the documented field limits.
"""

import pathlib

import httpx
import pytest

from vcbot import setup_bot
from vcbot.setup_bot import COMMANDS, DESCRIPTION, SHORT_DESCRIPTION, TelegramError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is _NOT_JSON:
            raise ValueError("not json")
        return self._payload


_NOT_JSON = object()

ME = {"id": 8552946814, "username": "vc_analyst_bot", "first_name": "VC Analyst"}


@pytest.fixture
def calls(monkeypatch):
    """Record every Bot API call and answer each one with a bare success."""
    recorded = []

    def fake_post(url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        recorded.append((method, json))
        if method == "getMe":
            return FakeResponse({"ok": True, "result": ME})
        return FakeResponse({"ok": True, "result": True})

    monkeypatch.setattr(setup_bot.httpx, "post", fake_post)
    return recorded


def methods(calls):
    return [method for method, _ in calls]


def payload_for(calls, method):
    return next(payload for name, payload in calls if name == method)


# ----------------------------------------------------------------- applying


def test_apply_calls_every_configuration_endpoint(calls):
    setup_bot.apply("token")
    assert methods(calls) == [
        "getMe",
        "setMyCommands",
        "setChatMenuButton",
        "setMyDescription",
        "setMyShortDescription",
    ]


def test_apply_returns_the_bot_identity(calls):
    assert setup_bot.apply("token")["username"] == "vc_analyst_bot"


def test_commands_payload_shape(calls):
    setup_bot.apply("token")
    commands = payload_for(calls, "setMyCommands")["commands"]
    assert len(commands) == len(COMMANDS)
    assert commands[0] == {"command": "start", "description": COMMANDS[0][1]}
    # Telegram requires lowercase names without the leading slash.
    assert all(c["command"].islower() and "/" not in c["command"] for c in commands)


def test_start_is_listed_first(calls):
    """The first command is what Telegram surfaces most prominently."""
    setup_bot.apply("token")
    assert payload_for(calls, "setMyCommands")["commands"][0]["command"] == "start"


def test_menu_button_is_the_command_list(calls):
    setup_bot.apply("token")
    assert payload_for(calls, "setChatMenuButton") == {"menu_button": {"type": "commands"}}


def test_descriptions_are_sent(calls):
    setup_bot.apply("token")
    assert payload_for(calls, "setMyDescription")["description"] == DESCRIPTION
    assert payload_for(calls, "setMyShortDescription")["short_description"] == SHORT_DESCRIPTION


# ------------------------------------------------------------------ limits


def test_description_within_telegram_limit():
    assert 0 < len(DESCRIPTION) <= 512


def test_short_description_within_telegram_limit():
    assert 0 < len(SHORT_DESCRIPTION) <= 120


def test_command_fields_within_telegram_limits():
    for name, description in COMMANDS:
        assert 1 <= len(name) <= 32
        assert 1 <= len(description) <= 256
        assert name.replace("_", "").isalnum()


def test_every_advertised_command_is_actually_handled():
    """A command in the menu that the bot does not handle is a dead button."""
    from vcbot import bot as botmod

    source = pathlib.Path(botmod.__file__).read_text()
    for name, _ in COMMANDS:
        assert f'CommandHandler("{name}"' in source, f"/{name} is advertised but not handled"


# ------------------------------------------------------------------ errors


def test_bad_token_gets_a_plain_explanation(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return FakeResponse({"ok": False, "description": "Unauthorized"}, status_code=401)

    monkeypatch.setattr(setup_bot.httpx, "post", fake_post)
    with pytest.raises(TelegramError, match="rejected the bot token"):
        setup_bot.apply("wrong")


def test_api_error_is_surfaced_with_its_method(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        if url.endswith("getMe"):
            return FakeResponse({"ok": True, "result": ME})
        return FakeResponse({"ok": False, "description": "BUTTON_TYPE_INVALID"}, 400)

    monkeypatch.setattr(setup_bot.httpx, "post", fake_post)
    with pytest.raises(TelegramError, match="setMyCommands: BUTTON_TYPE_INVALID"):
        setup_bot.apply("token")


def test_non_json_response_raises_telegram_error(monkeypatch):
    monkeypatch.setattr(
        setup_bot.httpx, "post", lambda url, json=None, timeout=None: FakeResponse(_NOT_JSON, 502)
    )
    with pytest.raises(TelegramError, match="HTTP 502"):
        setup_bot.apply("token")


def test_main_reports_a_missing_token(monkeypatch, capsys):
    monkeypatch.setattr(setup_bot, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    assert setup_bot.main([]) == 1
    assert "TELEGRAM_BOT_TOKEN is not set" in capsys.readouterr().err


def test_main_reports_an_unreachable_telegram(monkeypatch, capsys):
    monkeypatch.setattr(setup_bot, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")

    def boom(*a, **k):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(setup_bot.httpx, "post", boom)
    assert setup_bot.main([]) == 1
    assert "Could not reach Telegram" in capsys.readouterr().err


def test_main_applies_and_reports(monkeypatch, capsys, calls):
    monkeypatch.setattr(setup_bot, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert setup_bot.main([]) == 0
    out = capsys.readouterr().out
    assert "vc_analyst_bot" in out
    assert f"{len(COMMANDS)} commands registered" in out


def test_token_is_never_printed(monkeypatch, capsys, calls):
    """A token in stdout ends up in logs and screenshots."""
    monkeypatch.setattr(setup_bot, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRETVALUE")
    setup_bot.main([])
    captured = capsys.readouterr()
    assert "SECRETVALUE" not in captured.out
    assert "SECRETVALUE" not in captured.err
