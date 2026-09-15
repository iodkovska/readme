"""The Claude call that turns collected material into a scored memo."""

from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from .config import Config
from .ingest import (
    IngestError,
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    clamp,
    extract_file,
    image_block,
    pdf_document_block,
)
from .scoring import RUBRIC, ScoringMemo
from .state import Deal

log = logging.getLogger(__name__)


def _rubric_text() -> str:
    lines = []
    for key, (label, weight, guidance) in RUBRIC.items():
        lines.append(f"- {label} (`{key}`, weight {weight:.0%}): {guidance}")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are a partner-track analyst at an early-stage venture fund. \
You write the internal scoring memo that the partnership reads before deciding \
whether to spend another hour on a company.

Score each of these dimensions from 1 to 10:

{_rubric_text()}

Anchor the 1-10 scale honestly: 5 is an average company in the fund's deal flow, \
7 is genuinely strong, 9+ is the one deal a year you fight for. Most companies are \
not 8s. Do not inflate to be encouraging.

Rules that matter more than polish:

1. Separate what the materials SHOW from what they CLAIM. A slide asserting \
"$2M ARR" is a claim; a cohort chart with monthly detail is evidence. Say which \
you are relying on.
2. Every score needs specific evidence, cited to its source — deck page number, \
spreadsheet sheet and row, the website, or the founder's notes. No generic \
observations that would fit any startup.
3. Interrogate the financial model rather than summarizing it. Name the driver \
assumptions (growth rate, conversion, churn, CAC, headcount) and flag any that \
are hardcoded, circular, or implausible against the traction shown. If revenue \
growth is a typed-in curve rather than a function of inputs, say so.
4. Missing material is a finding, not an excuse. If there is no financial model, \
score unit economics on what can be inferred and put the gap in \
`missing_information` — but do not refuse to score.
5. Be concrete about risk. "Execution risk" is not a risk; "two founders, neither \
has sold into hospital procurement, and the model assumes a 45-day sales cycle" is.
6. `diligence_questions` are the questions that would actually change your mind, \
ordered by how much they would move the score.

Write for a reader who is short on time and allergic to hype. Plain sentences, \
no marketing register, no hedging into meaninglessness."""


def build_user_content(deal: Deal, cfg: Config) -> tuple[list[dict], list[str]]:
    """Assemble the content blocks for the request.

    Returns the blocks and a list of human-readable warnings about anything that
    could not be read, which the bot relays to the chat.
    """
    blocks: list[dict] = []
    warnings: list[str] = []
    inventory: list[str] = []

    for att in deal.decks:
        path = Path(att.path)
        if not path.exists():
            warnings.append(f"{att.file_name} is no longer on disk and was skipped.")
            continue
        suffix = att.suffix
        if suffix in PDF_SUFFIXES:
            blocks.append(pdf_document_block(path, f"Pitch deck: {att.file_name}"))
            inventory.append(f"pitch deck PDF ({att.file_name})")
        elif suffix in IMAGE_SUFFIXES:
            blocks.append({"type": "text", "text": f"Pitch deck image: {att.file_name}"})
            blocks.append(image_block(path))
            inventory.append(f"pitch deck image ({att.file_name})")
        else:
            try:
                text = clamp(extract_file(path), cfg.max_source_chars)
            except IngestError as exc:
                warnings.append(str(exc))
                continue
            blocks.append(
                {
                    "type": "text",
                    "text": f"<pitch_deck name=\"{att.file_name}\">\n{text}\n</pitch_deck>",
                }
            )
            inventory.append(f"pitch deck ({att.file_name})")

    for att in deal.models:
        path = Path(att.path)
        if not path.exists():
            warnings.append(f"{att.file_name} is no longer on disk and was skipped.")
            continue
        if att.suffix in PDF_SUFFIXES:
            blocks.append(pdf_document_block(path, f"Financial model: {att.file_name}"))
            inventory.append(f"financial model PDF ({att.file_name})")
            continue
        try:
            text = clamp(extract_file(path), cfg.max_source_chars)
        except IngestError as exc:
            warnings.append(str(exc))
            continue
        blocks.append(
            {
                "type": "text",
                "text": (
                    f"<financial_model name=\"{att.file_name}\">\n"
                    "Each sheet appears twice: once with computed values and once with "
                    "the underlying formulas.\n\n"
                    f"{text}\n</financial_model>"
                ),
            }
        )
        inventory.append(f"financial model ({att.file_name})")

    for url, text in _website_texts(deal, cfg, warnings):
        blocks.append(
            {"type": "text", "text": f"<website url=\"{url}\">\n{text}\n</website>"}
        )
        inventory.append(f"website ({url})")

    if deal.notes:
        joined = "\n\n---\n\n".join(deal.notes)
        blocks.append(
            {
                "type": "text",
                "text": (
                    "<additional_info>\n"
                    "Notes supplied by the person running this analysis — founder "
                    "emails, call notes, references, anything else.\n\n"
                    f"{clamp(joined, cfg.max_source_chars)}\n</additional_info>"
                ),
            }
        )
        inventory.append(f"{len(deal.notes)} note(s)")

    instruction = (
        "Write the scoring memo for this company.\n\n"
        f"Material provided: {', '.join(inventory) if inventory else 'none'}."
    )
    if deal.company:
        instruction += f"\nThe company is referred to as: {deal.company}."
    blocks.append({"type": "text", "text": instruction})

    return blocks, warnings


def _website_texts(deal: Deal, cfg: Config, warnings: list[str]):
    """Fetch each saved website, collecting failures as warnings."""
    from .ingest import fetch_website

    for url in deal.websites:
        try:
            yield url, clamp(fetch_website(url), cfg.max_source_chars)
        except IngestError as exc:
            warnings.append(str(exc))


class Analyst:
    """Wraps the Anthropic client. Synchronous — call it from a worker thread."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        # 10 minutes: a deck-plus-model memo is a long single request.
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, timeout=600.0)

    def score(self, deal: Deal) -> tuple[ScoringMemo, list[str]]:
        blocks, warnings = build_user_content(deal, self.cfg)

        response = self.client.messages.parse(
            model=self.cfg.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": self.cfg.effort},
            messages=[{"role": "user", "content": blocks}],
            output_format=ScoringMemo,
        )

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", "") or ""
            raise RuntimeError(f"The model declined to analyse this material. {detail}".strip())
        if response.parsed_output is None:
            raise RuntimeError("The model returned no structured memo. Try again.")

        log.info(
            "memo for chat %s: in=%s out=%s tokens",
            deal.chat_id,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return response.parsed_output, warnings
