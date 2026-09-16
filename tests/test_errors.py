"""Chat-facing error messages.

Two of these correspond to failures actually seen from the live API during
development: an exhausted credit balance and a schema too large to compile.
"""

import httpx
import pytest

import anthropic

from vcbot.errors import friendly_error


def api_error(cls, message: str, status: int = 400, headers=None):
    """Build a real SDK exception carrying Telegram-visible message text."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, headers=headers or {})
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return cls(message=message, response=response, body=body)


def test_exhausted_credit_points_at_billing():
    exc = api_error(
        anthropic.BadRequestError,
        "Your credit balance is too low to access the Anthropic API.",
    )
    out = friendly_error(exc)
    assert "out of credit" in out
    assert "billing" in out
    assert "nothing you sent was lost" in out.lower()


def test_grammar_too_large_is_named_as_a_bot_bug():
    """The user's material is not the problem; say so."""
    exc = api_error(
        anthropic.BadRequestError,
        "The compiled grammar is too large, which would cause performance issues.",
    )
    out = friendly_error(exc)
    assert "bug in the bot" in out
    assert "scoring.py" in out


def test_prompt_too_long_suggests_dropping_a_file():
    exc = api_error(anthropic.BadRequestError, "prompt is too long: 1200000 tokens")
    out = friendly_error(exc)
    assert "too much material" in out
    assert "New deal" in out or "MAX_SOURCE_CHARS" in out


def test_oversize_request_is_explained():
    exc = api_error(anthropic.BadRequestError, "request_too_large: too many total text bytes")
    assert "too large for a single request" in friendly_error(exc)


def test_unknown_bad_request_still_says_something_useful():
    exc = api_error(anthropic.BadRequestError, "some novel validation failure")
    out = friendly_error(exc)
    assert "rejected the request" in out
    assert "some novel validation failure" in out


def test_authentication_error_points_at_the_key():
    exc = api_error(anthropic.AuthenticationError, "invalid x-api-key", status=401)
    out = friendly_error(exc)
    assert "ANTHROPIC_API_KEY" in out


def test_rate_limit_uses_retry_after_when_present():
    exc = api_error(
        anthropic.RateLimitError, "rate limit", status=429, headers={"retry-after": "42"}
    )
    assert "42 seconds" in friendly_error(exc)


def test_rate_limit_without_a_header_still_advises():
    exc = api_error(anthropic.RateLimitError, "rate limit", status=429)
    out = friendly_error(exc)
    assert "rate limit" in out.lower()
    assert "try again" in out.lower()


def test_server_error_is_attributed_to_the_api():
    exc = api_error(anthropic.InternalServerError, "overloaded", status=529)
    out = friendly_error(exc)
    assert "their side" in out
    assert "529" in out


def test_timeout_suggests_turning_off_research():
    exc = anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    out = friendly_error(exc)
    assert "timed out" in out
    assert "web research" in out


def test_connection_error_mentions_the_network():
    exc = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    assert "network" in friendly_error(exc).lower()


def test_a_plain_exception_passes_through():
    assert friendly_error(RuntimeError("something broke")) == "something broke"


def test_an_empty_exception_still_names_its_type():
    assert friendly_error(ValueError()) == "ValueError"


@pytest.mark.parametrize(
    "exc",
    [
        api_error(anthropic.BadRequestError, "Your credit balance is too low"),
        api_error(anthropic.AuthenticationError, "bad key", 401),
        api_error(anthropic.RateLimitError, "slow down", 429),
        anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        RuntimeError("plain"),
    ],
)
def test_every_message_is_short_enough_for_a_chat_message(exc):
    out = friendly_error(exc)
    assert out and len(out) < 400
    assert "Traceback" not in out
