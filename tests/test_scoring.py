import pytest

from vcbot.scoring import (
    CATEGORIES,
    FACT_LABELS_LEFT,
    FACT_LABELS_RIGHT,
    MAX_PER_CATEGORY,
    MAX_TOTAL,
    ForwardingSummary,
    Point,
    Scores,
    ScoringMemo,
    Sections,
)


FACT_VALUES = {
    "Round size": "$4M",
    "Round terms": "SAFE, $18M post",
    "Already Closed": "$1.2M",
    "Soft commitments": "$800K",
    "Left Open": "$2M",
    "Use of funds": "55% engineering, 30% sales",
    "Co-investors": "",
    "Cap Table": "Founders 75%, pool 10%",
    "Previous funding": "$1M pre-seed",
    "Source": "Angel intro",
    "URL": "https://vektor.example",
    "Industry": "Warehouse robotics",
    "Stage": "Seed",
    "TA Type": "B2B",
    "Configuration": "RaaS",
    "Revenue Geo": "US",
    "R&D Geo": "US",
    "Deal Breakers": "No",
    "Intellectual Property": "No",
    "Revenue 1 month": "$116K",
}


def make_facts(**overrides) -> str:
    values = dict(FACT_VALUES)
    values.update(overrides)
    return "\n".join(f"{label}: {value}" for label, value in values.items())


def make_memo(**scores) -> ScoringMemo:
    values = {key: 2 for key in CATEGORIES}
    values.update(scores)
    return ScoringMemo(
        company_name="Vektor Robotics",
        tagline="Autonomous piece-picking for third-party logistics",
        facts=make_facts(),
        scores=Scores(**values),
        rationales="\n".join(
            f"{label}: {label} rationale citing page 5" for _, (label, _) in CATEGORIES.items()
        ),
        sections=Sections(
            product="Problem: 3PL throughput\nSolution: Retrofit arms\nProven Value: 9 live deployments",
            business_model="Model: RaaS\nHow recurrent & repeatable: 36-month contracts\nPricing: $4,200/arm/mo",
            traction="Key metrics: $1.4M ARR\nGrowth rate: 4.5x YoY",
            team="Dana Whitfield: CEO, 8 years logistics software\nWhy This Team: Domain fit on the buyer side",
            go_to_market="How they sell: Direct to 3PL ops leads\nChannels used: Founder-led outbound",
            market="Size: $64B claimed, top-down\nWhy Now: Labour churn",
            competitors="Leaders: Locus, Fetch\nClosest competition: Retrofit vendors\nHow they differ: No racking change",
            technology="Features: Vision stack, 4.1M pick events",
            deal="Terms: $4M on $18M post\nBenchmarking to industry multiples: ~13x ARR\nValuation: Above median",
        ),
        pros=[Point(category="Traction", point="ARR grew 4.5x in twelve months")],
        cons_risks=[Point(category="Traction", point="71% of ARR is one customer")],
        forwarding_summary=ForwardingSummary(
            round_terms="$4M on $18M post", source_and_terms="Angel intro", deadline="5 weeks"
        ),
        recommendation="track",
        recommendation_rationale="Worth watching until concentration resolves.",
        missing_information=["No cohort data"],
    )


def test_ten_categories_out_of_thirty():
    assert len(CATEGORIES) == 10
    assert MAX_TOTAL == 30
    assert MAX_PER_CATEGORY == 3


def test_total_sums_the_categories():
    assert make_memo().total() == 20
    assert make_memo(market=3, product=3).total() == 22


def test_scoring_line_matches_the_template_format():
    assert make_memo().scoring_line() == "20/30"
    assert make_memo(**{k: 3 for k in CATEGORIES}).scoring_line() == "30/30"


def test_scores_follow_template_column_order():
    labels = [label for _, label, _, _ in make_memo().scored()]
    assert labels == [
        "Market",
        "Product",
        "Business Model",
        "Traction",
        "Sales & Marketing",
        "Competition",
        "Team",
        "Tech",
        "Deal",
        "Financials",
    ]


def test_score_bounds_are_enforced():
    with pytest.raises(Exception):
        make_memo(market=4)
    with pytest.raises(Exception):
        make_memo(market=-1)


def test_zero_is_a_valid_score():
    assert make_memo(tech=0).scores.tech == 0
    assert make_memo(tech=0).total() == 18


def test_fact_labels_cover_both_template_columns():
    assert len(FACT_LABELS_LEFT) == 10
    assert len(FACT_LABELS_RIGHT) == 10
    assert set(FACT_LABELS_LEFT) | set(FACT_LABELS_RIGHT) == set(FACT_VALUES)


def test_rationales_are_parsed_back_per_category():
    scored = make_memo().scored()
    assert all(rationale for _, _, _, rationale in scored)
    assert scored[0][3] == "Market rationale citing page 5"


def test_missing_rationale_line_leaves_it_empty_not_crashing():
    memo = make_memo()
    memo.rationales = "Market: only this one"
    scored = memo.scored()
    assert scored[0][3] == "Market rationale"[:0] + "only this one"
    assert scored[1][3] == ""
