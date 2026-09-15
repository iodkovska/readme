import pytest

from vcbot.scoring import RUBRIC, DimensionScore, Risk, ScoringMemo


def dim(score: int) -> DimensionScore:
    return DimensionScore(score=score, rationale="because", evidence=["p3"], gaps=[])


def make_memo(**scores) -> ScoringMemo:
    defaults = {key: 5 for key in RUBRIC}
    defaults.update(scores)
    return ScoringMemo(
        company_name="Acme Robotics",
        one_liner="Warehouse pick-and-place arms sold as a service.",
        stage="seed",
        sector="robotics",
        summary="A summary.",
        key_strengths=["strong ops hire"],
        key_risks=[Risk(risk="single customer", severity="high", mitigation="sign a second")],
        diligence_questions=["What is net revenue retention?"],
        missing_information=["no cohort data"],
        recommendation="track",
        conviction="medium",
        recommendation_rationale="Worth watching.",
        **{key: dim(value) for key, value in defaults.items()},
    )


def test_weights_sum_to_one():
    assert round(sum(weight for _, weight, _ in RUBRIC.values()), 6) == 1.0


def test_uniform_scores_give_that_score():
    assert make_memo().weighted_score() == 5.0


def test_weighting_favours_team_over_deal():
    team_heavy = make_memo(team=10)
    deal_heavy = make_memo(deal=10)
    assert team_heavy.weighted_score() > deal_heavy.weighted_score()


def test_score_bounds_are_enforced():
    with pytest.raises(Exception):
        DimensionScore(score=11, rationale="x", evidence=[], gaps=[])
    with pytest.raises(Exception):
        DimensionScore(score=0, rationale="x", evidence=[], gaps=[])


def test_dimensions_follow_rubric_order():
    assert [key for key, _, _, _ in make_memo().dimensions()] == list(RUBRIC)
