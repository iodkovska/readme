"""Turning API failures into something a person in a Telegram chat can act on.

Every message here was written against a failure actually seen from the API, or
from its documented error list. The raw exceptions are JSON blobs aimed at
developers; a partner waiting on a memo needs to know whose problem it is and
what to do next.
"""

from __future__ import annotations

import anthropic

# Substrings of the API's own message -> what to tell the user. Checked in order,
# because a 400 carries many different meanings.
_BAD_REQUEST_HINTS: list[tuple[str, str]] = [
    (
        "credit balance is too low",
        "The Anthropic account is out of credit. Top it up at "
        "console.anthropic.com/settings/billing and try again — nothing you sent "
        "was lost.",
    ),
    (
        "grammar is too large",
        "Internal error: the memo schema got too complex for the API to compile. "
        "This is a bug in the bot, not in your material. Report it — the fix is to "
        "flatten a field in vcbot/scoring.py.",
    ),
    (
        "prompt is too long",
        "There is too much material for one memo. Drop the largest file (usually a "
        "long PDF) with ♻️ New deal and send a shorter export, or lower "
        "MAX_SOURCE_CHARS.",
    ),
    (
        "max_tokens",
        "The memo came out longer than the configured limit. Try again; if it keeps "
        "happening, raise max_tokens in vcbot/analyst.py.",
    ),
]

_OVERSIZE_MARKERS = ("request_too_large", "too many total text bytes", "exceeds the maximum")


def friendly_error(exc: BaseException) -> str:
    """A one- or two-sentence explanation suitable for a chat message."""
    if isinstance(exc, anthropic.AuthenticationError):
        return (
            "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env — "
            "a rotated or deleted key is the usual cause."
        )

    if isinstance(exc, anthropic.PermissionDeniedError):
        return (
            "The Anthropic API key lacks permission for this model. Check the key's "
            "scopes, or set ANTHROPIC_MODEL to a model the account can use."
        )

    if isinstance(exc, anthropic.NotFoundError):
        return (
            f"The model '{_model_hint(exc)}' was not found. Check ANTHROPIC_MODEL "
            "in .env."
        )

    if isinstance(exc, anthropic.RateLimitError):
        retry = _retry_after(exc)
        wait = f" Try again in about {retry} seconds." if retry else " Try again shortly."
        return f"Hit the Anthropic rate limit.{wait}"

    if isinstance(exc, anthropic.BadRequestError):
        message = str(exc).lower()
        for marker, hint in _BAD_REQUEST_HINTS:
            if marker in message:
                return hint
        if any(marker in message for marker in _OVERSIZE_MARKERS):
            return (
                "The material is too large for a single request. Remove a file and "
                "try again."
            )
        return f"The API rejected the request: {_short(exc)}"

    if isinstance(exc, anthropic.APITimeoutError):
        return (
            "The request timed out. A big deck plus a financial model can take a "
            "while — try again, or turn off web research to halve the work."
        )

    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API. Check the network and try again."

    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return (
                f"The Anthropic API returned a server error ({exc.status_code}). "
                "That is their side — try again in a minute."
            )
        return f"The API returned an error ({exc.status_code}): {_short(exc)}"

    return str(exc) or exc.__class__.__name__


def _short(exc: BaseException, limit: int = 200) -> str:
    text = str(exc).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _retry_after(exc: anthropic.RateLimitError) -> int | None:
    try:
        return int(exc.response.headers.get("retry-after", ""))
    except (AttributeError, TypeError, ValueError):
        return None


def _model_hint(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        message = str(body.get("error", {}).get("message", ""))
        if message:
            return _short(message, 60)
    return "configured"
