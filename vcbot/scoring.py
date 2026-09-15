"""The scoring rubric: dimensions, weights, and the memo schema.

The model scores each dimension 1-10 and justifies it. The weighting and the
overall number are computed here in Python, so the arithmetic is deterministic
and the rubric can be re-tuned without touching the prompt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Recommendation = Literal["pass", "track", "take_meeting", "deep_diligence", "invest"]
Conviction = Literal["low", "medium", "high"]
Severity = Literal["low", "medium", "high"]

# dimension key -> (display name, weight, what the score is meant to capture)
RUBRIC: dict[str, tuple[str, float, str]] = {
    "team": (
        "Team",
        0.25,
        "Founder-market fit, track record, completeness of the founding team, "
        "ability to hire and to sell.",
    ),
    "market": (
        "Market",
        0.20,
        "Size and growth of the reachable market, timing, why now, and whether "
        "the TAM claimed is bottom-up and credible.",
    ),
    "product": (
        "Product & Technology",
        0.15,
        "What is actually built, technical depth, differentiation, and how far "
        "it is from what customers need.",
    ),
    "traction": (
        "Traction",
        0.15,
        "Revenue, growth rate, pipeline, retention, engagement, and the quality "
        "of the evidence behind them.",
    ),
    "business_model": (
        "Business Model & Unit Economics",
        0.10,
        "Pricing, gross margin, CAC/LTV, payback, burn multiple, and whether the "
        "financial model's assumptions hold up.",
    ),
    "moat": (
        "Competition & Moat",
        0.10,
        "Competitive landscape and what compounds over time: data, network "
        "effects, switching costs, distribution, regulatory position.",
    ),
    "deal": (
        "Deal & Ask",
        0.05,
        "Round size, valuation, use of funds, runway bought, and whether the ask "
        "matches the milestones promised.",
    ),
}

RECOMMENDATION_LABELS: dict[str, str] = {
    "pass": "PASS",
    "track": "TRACK — revisit at next milestone",
    "take_meeting": "TAKE MEETING",
    "deep_diligence": "PROCEED TO DEEP DILIGENCE",
    "invest": "INVEST — move to term sheet",
}


class DimensionScore(BaseModel):
    score: int = Field(ge=1, le=10, description="1 = disqualifying, 10 = exceptional")
    rationale: str = Field(description="Two to four sentences justifying the score.")
    evidence: list[str] = Field(
        description="Specific facts from the materials that support the score, "
        "each naming its source (deck page, model sheet, website, founder note)."
    )
    gaps: list[str] = Field(
        description="What is missing or unverified for this dimension. Empty if nothing."
    )


class Risk(BaseModel):
    risk: str
    severity: Severity
    mitigation: str = Field(description="What would reduce or disprove this risk.")


class ScoringMemo(BaseModel):
    """The structured memo the model returns; rendered to Markdown in memo.py."""

    company_name: str
    one_liner: str = Field(description="What the company does, in one sentence.")
    stage: str = Field(description="Best estimate, e.g. 'pre-seed', 'Series A'. 'unclear' if not stated.")
    sector: str
    summary: str = Field(description="Three to five sentences an investor could read cold.")

    team: DimensionScore
    market: DimensionScore
    product: DimensionScore
    traction: DimensionScore
    business_model: DimensionScore
    moat: DimensionScore
    deal: DimensionScore

    key_strengths: list[str]
    key_risks: list[Risk]
    diligence_questions: list[str] = Field(
        description="The questions to put to the founders next, sharpest first."
    )
    missing_information: list[str] = Field(
        description="Material that was not provided and would change the assessment."
    )

    recommendation: Recommendation
    conviction: Conviction
    recommendation_rationale: str

    def dimensions(self) -> list[tuple[str, str, float, DimensionScore]]:
        """(key, display name, weight, score) for each rubric dimension, in rubric order."""
        return [
            (key, label, weight, getattr(self, key))
            for key, (label, weight, _) in RUBRIC.items()
        ]

    def weighted_score(self) -> float:
        """Overall score out of 10, rounded to one decimal."""
        total = sum(weight * dim.score for _, _, weight, dim in self.dimensions())
        return round(total, 1)
