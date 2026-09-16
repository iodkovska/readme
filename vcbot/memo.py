"""The at-a-glance version of a memo, posted into the chat.

The full memo is the filled Word template (`docx_memo.py`); this is the summary
that goes in the message body so the scores are readable without downloading.
"""

from __future__ import annotations

from .scoring import MAX_PER_CATEGORY, MAX_TOTAL, RECOMMENDATION_LABELS, ScoringMemo

TELEGRAM_LIMIT = 4096


def score_bar(score: int, width: int = MAX_PER_CATEGORY) -> str:
    return "█" * score + "░" * (width - score)


def render_chat(memo: ScoringMemo) -> str:
    """The summary posted into the chat alongside the .docx."""
    lines = [
        f"📋 {memo.company_name} — {memo.tagline}",
    ]
    facts = memo.fact_map()
    context = " · ".join(
        p for p in (facts.get("industry"), facts.get("stage"), facts.get("ta type")) if p
    )
    if context:
        lines.append(context)

    lines += [
        "",
        f"🎯 SCORING: {memo.scoring_line()}",
        f"   {RECOMMENDATION_LABELS.get(memo.recommendation, memo.recommendation)}",
        "",
    ]

    for _, label, score, _rationale in memo.scored():
        lines.append(f"{score_bar(score)} {score}/{MAX_PER_CATEGORY}  {label}")

    lines += ["", "WHY", memo.recommendation_rationale]

    if memo.pros:
        lines += ["", "PROS"]
        for point in memo.pros[:4]:
            lines.append(f"• {point.category}: {point.point}")

    if memo.cons_risks:
        lines += ["", "CONS / RISKS"]
        for point in memo.cons_risks[:4]:
            lines.append(f"• {point.category}: {point.point}")

    if memo.missing_information:
        lines += ["", "MISSING"]
        for item in memo.missing_information[:3]:
            lines.append(f"• {item}")

    lines += ["", "Full memo attached as a Word document. 📎"]
    return "\n".join(lines)


def chunk(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into Telegram-sized pieces, preferring paragraph then line breaks."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = window.rfind("\n\n")
        if split_at < limit // 2:
            split_at = window.rfind("\n")
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


__all__ = ["TELEGRAM_LIMIT", "chunk", "render_chat", "score_bar", "MAX_TOTAL"]
