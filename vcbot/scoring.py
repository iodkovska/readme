"""The scoring rubric and memo schema, matching the fund's Word template.

Ten categories scored 0-3 for a total out of 30, a deal-facts header, pros and
cons by category, a forwarding summary, and nine detail sections. The shape here
mirrors `templates/scoring_template.docx` field for field — change one and the
other has to follow.

The schema is deliberately shallow. Structured outputs compile to a grammar, and
a grammar has a size limit: an earlier version modelled each of the nine detail
sections as its own nested object and the API rejected it with "the compiled
grammar is too large". Sections are therefore strings whose internal labels the
prompt dictates, and the per-category scores and rationales are two flat maps
rather than ten nested objects.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Score category key -> (label as it appears in the template, what it covers).
# Order matters: it is the column order of the scoring table.
CATEGORIES: dict[str, tuple[str, str]] = {
    "market": ("Market", "Size, growth, timing, and the risk attached to the geography served."),
    "product": ("Product", "The problem, the solution, and whether value is proven with real users."),
    "business_model": ("Business Model", "How revenue is earned, how recurrent and repeatable it is, and pricing."),
    "traction": ("Traction", "Key metrics and growth rate, and how well evidenced they are."),
    "sales_marketing": ("Sales & Marketing", "How they sell, which channels work, and whether the motion is repeatable."),
    "competition": ("Competition", "The leaders, the closest competitors, and what genuinely differentiates."),
    "team": ("Team", "Expertise, entrepreneurial track record, and why this team wins."),
    "tech": ("Tech", "The technology itself: features, depth, and defensibility."),
    "deal": ("Deal", "Terms, valuation against industry multiples, and the ask."),
    "financials": ("Financials", "The model's integrity, burn, runway, and unit economics."),
}

# The header table's labels, in the order the renderer writes them. The prompt
# asks for exactly these, so `facts` can be parsed back into the right cells.
FACT_LABELS_LEFT = [
    "Round size",
    "Round terms",
    "Already Closed",
    "Soft commitments",
    "Left Open",
    "Use of funds",
    "Co-investors",
    "Cap Table",
    "Previous funding",
    "Source",
]
FACT_LABELS_RIGHT = [
    "URL",
    "Industry",
    "Stage",
    "TA Type",
    "Configuration",
    "Revenue Geo",
    "R&D Geo",
    "Deal Breakers",
    "Intellectual Property",
    "Revenue 1 month",
]

MAX_PER_CATEGORY = 3
MAX_TOTAL = MAX_PER_CATEGORY * len(CATEGORIES)  # 30

SCORE_GUIDE = """0 = a serious problem or nothing to support it; 1 = below the \
bar, real doubts; 2 = solid, no red flags; 3 = a genuine strength worth citing \
in the partner meeting."""

# Detail section key -> (template heading, the sub-headings the prompt must cover).
SECTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "product": ("1. Product", ("Problem", "Solution", "Proven Value")),
    "business_model": ("2. Business model", ("Model", "How recurrent & repeatable", "Pricing")),
    "traction": ("3. Traction", ("Key metrics", "Growth rate")),
    "team": ("4. Team", ("Founders", "Expertise", "Entrepreneurial experience", "Why This Team")),
    "go_to_market": ("5. Go to market", ("How they sell", "Channels used")),
    "market": ("6. Market", ("Size", "Why Now")),
    "competitors": ("7. Competitors", ("Leaders", "Closest competition", "How they differ")),
    "technology": ("8. Technology", ("Features",)),
    "deal": ("9. Deal/Ask", ("Terms", "Benchmarking to industry multiples", "Valuation")),
}

_LINE_FORMAT = (
    "Write one 'Label: text' line per sub-heading, in the order given, separated "
    "by newlines. Use the exact labels."
)


def _labelled_lines(text: str) -> dict[str, str]:
    """Parse `Label: value` lines into a lowercased label -> value map."""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        label, sep, value = raw.strip().lstrip("-•").strip().partition(":")
        if sep:
            out[label.strip().lower()] = value.strip()
    return out


class Scores(BaseModel):
    """The ten category scores, 0-3 each."""

    market: int = Field(ge=0, le=MAX_PER_CATEGORY)
    product: int = Field(ge=0, le=MAX_PER_CATEGORY)
    business_model: int = Field(ge=0, le=MAX_PER_CATEGORY)
    traction: int = Field(ge=0, le=MAX_PER_CATEGORY)
    sales_marketing: int = Field(ge=0, le=MAX_PER_CATEGORY)
    competition: int = Field(ge=0, le=MAX_PER_CATEGORY)
    team: int = Field(ge=0, le=MAX_PER_CATEGORY)
    tech: int = Field(ge=0, le=MAX_PER_CATEGORY)
    deal: int = Field(ge=0, le=MAX_PER_CATEGORY)
    financials: int = Field(ge=0, le=MAX_PER_CATEGORY)


class Sections(BaseModel):
    """The nine detail sections of the memo body."""

    product: str = Field(description=f"Problem / Solution / Proven Value. {_LINE_FORMAT}")
    business_model: str = Field(
        description=f"Model / How recurrent & repeatable / Pricing. {_LINE_FORMAT}"
    )
    traction: str = Field(description=f"Key metrics / Growth rate. {_LINE_FORMAT}")
    team: str = Field(
        description=(
            "One line per founder: 'Name: role, expertise, entrepreneurial experience, "
            "bio URL if found', then a final 'Why This Team: ...' line."
        )
    )
    go_to_market: str = Field(description=f"How they sell / Channels used. {_LINE_FORMAT}")
    market: str = Field(
        description=(
            "Size / Why Now. Under Size, say whether the figure is top-down or "
            f"bottom-up and where it comes from. {_LINE_FORMAT}"
        )
    )
    competitors: str = Field(
        description=f"Leaders / Closest competition / How they differ. {_LINE_FORMAT}"
    )
    technology: str = Field(description=f"Features. {_LINE_FORMAT}")
    deal: str = Field(
        description=(
            "Terms / Benchmarking to industry multiples / Valuation. "
            f"{_LINE_FORMAT}"
        )
    )


class Point(BaseModel):
    """A pro or a con, labelled with the scoring category it belongs to."""

    category: str = Field(description="One of the ten scoring categories, e.g. 'Traction'.")
    point: str = Field(description="The specific observation. No generic filler.")


class ForwardingSummary(BaseModel):
    round_terms: str
    source_and_terms: str
    deadline: str


class ScoringMemo(BaseModel):
    """One filled scoring memo, rendered into the Word template."""

    company_name: str
    tagline: str = Field(description="The short descriptor after the company name in the title.")

    facts: str = Field(
        description=(
            "The deal-facts header, as 'Label: value' lines using exactly these "
            "labels, one per line, in this order: Round size, Round terms, Already "
            "Closed, Soft commitments, Left Open, Use of funds, Co-investors, Cap "
            "Table, Previous funding, Source, URL, Industry, Stage, TA Type, "
            "Configuration, Revenue Geo, R&D Geo, Deal Breakers, Intellectual "
            "Property, Revenue 1 month. Leave the value empty when the materials do "
            "not answer it — never guess. Deal Breakers and Intellectual Property "
            "are 'No' unless you found one."
        )
    )
    scores: Scores
    rationales: str = Field(
        description=(
            "One 'Category: rationale' line per scoring category, using exactly the "
            "ten category labels, in the order they are listed above. One or two "
            "sentences each, citing the evidence behind that score."
        )
    )
    sections: Sections

    pros: list[Point]
    cons_risks: list[Point]
    forwarding_summary: ForwardingSummary

    recommendation: Literal["pass", "track", "take_meeting", "deep_diligence", "invest"]
    recommendation_rationale: str
    missing_information: list[str] = Field(
        description="Material not provided that would change the assessment."
    )

    def fact_map(self) -> dict[str, str]:
        """Parse the deal-facts block into a lowercased label -> value map.

        The prompt dictates the labels, but a model may still drop one or reword
        it slightly, so a missing label simply resolves to an empty value.
        """
        return _labelled_lines(self.facts)

    def rationale_map(self) -> dict[str, str]:
        """Parse the `Category: rationale` lines back into a label -> text map."""
        return _labelled_lines(self.rationales)

    def scored(self) -> list[tuple[str, str, int, str]]:
        """(key, template label, score, rationale) in template column order."""
        rationales = self.rationale_map()
        return [
            (
                key,
                label,
                getattr(self.scores, key),
                rationales.get(label.lower(), rationales.get(key.replace("_", " "), "")),
            )
            for key, (label, _) in CATEGORIES.items()
        ]

    def total(self) -> int:
        return sum(getattr(self.scores, key) for key in CATEGORIES)

    def scoring_line(self) -> str:
        return f"{self.total()}/{MAX_TOTAL}"


RECOMMENDATION_LABELS: dict[str, str] = {
    "pass": "PASS",
    "track": "TRACK — revisit at next milestone",
    "take_meeting": "TAKE MEETING",
    "deep_diligence": "PROCEED TO DEEP DILIGENCE",
    "invest": "INVEST — move to term sheet",
}
