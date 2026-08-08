# TradePilot AI — tests for the evaluation engine (Milestone 8).
#
# Everything here is pure computation -- no network, no mocking needed,
# no AI calls exist to mock in the first place.

import inspect
from datetime import datetime, timezone

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams
from evals.trade_evaluator import EvaluationStatus, UNCERTAINTY_CAPS, evaluate


def _analysis(**overrides) -> AgentAnalysisResult:
    """A 'perfect' analysis by default: every subjective field is
    substantive (>= 15 chars) and contains no negative/absence phrases,
    so each scores 20 before any uncertainty cap is applied."""
    defaults = dict(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="Price has been grinding higher against a rising trendline with clean structure.",
        trend_assessment="Uptrend with a clear series of higher highs and higher lows.",
        structure_assessment="Stair-step structure, minimal overlap between recent candles.",
        setup_assessment="Pullback to the trendline, holding as support, a readable entry point.",
        uncertainty="LOW",
        timestamp=datetime.now(timezone.utc),
        error_message=None,
    )
    defaults.update(overrides)
    return AgentAnalysisResult(**defaults)


def _long_params(**overrides) -> TradeParams:
    # entry=100, stop=95 (risk=5), target=110 (reward=10) -> RR = 2.0
    defaults = dict(direction="long", entry=100.0, stop=95.0, target=110.0)
    defaults.update(overrides)
    return TradeParams(**defaults)


def _short_params(**overrides) -> TradeParams:
    # entry=100, stop=105 (risk=5), target=90 (reward=10) -> RR = 2.0
    defaults = dict(direction="short", entry=100.0, stop=105.0, target=90.0)
    defaults.update(overrides)
    return TradeParams(**defaults)


# ---------------------------------------------------------------------------
# Determinism and the total-score boundary
# ---------------------------------------------------------------------------


def test_same_input_scored_twice_is_identical():
    analysis = _analysis()
    params = _long_params()

    first = evaluate(analysis, params)
    second = evaluate(analysis, params)

    assert first == second


def test_total_always_equals_sum_of_five_components():
    for uncertainty in ("LOW", "MEDIUM", "HIGH"):
        result = evaluate(_analysis(uncertainty=uncertainty), _long_params())

        assert result.status == EvaluationStatus.SUCCESS
        assert result.total_score == (
            result.trend_score
            + result.structure_score
            + result.entry_score
            + result.risk_reward_score
            + result.timing_context_score
        )


def test_evaluate_has_no_total_score_parameter():
    """This is what actually enforces 'the engine never accepts a total
    from anywhere': there is no parameter to pass one in through."""
    params = inspect.signature(evaluate).parameters

    assert "total_score" not in params
    assert "total" not in params


# ---------------------------------------------------------------------------
# Risk/Reward arithmetic
# ---------------------------------------------------------------------------


def test_risk_reward_computed_correctly_for_long():
    # risk = 100 - 95 = 5, reward = 110 - 100 = 10, RR = 2.0
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=95.0, target=110.0))

    assert result.status == EvaluationStatus.SUCCESS
    assert result.risk_reward_ratio == 2.0
    assert result.risk_reward_score == 20


def test_risk_reward_computed_correctly_for_short():
    # risk = 105 - 100 = 5, reward = 100 - 90 = 10, RR = 2.0
    result = evaluate(_analysis(), _short_params(entry=100.0, stop=105.0, target=90.0))

    assert result.status == EvaluationStatus.SUCCESS
    assert result.risk_reward_ratio == 2.0
    assert result.risk_reward_score == 20


def test_risk_reward_marginal_band():
    # risk = 5, reward = 5 -> RR = 1.0 -> 10 points
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=95.0, target=105.0))

    assert result.risk_reward_ratio == 1.0
    assert result.risk_reward_score == 10


def test_risk_reward_poor_band():
    # risk = 10, reward = 5 -> RR = 0.5 -> 0 points
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=90.0, target=105.0))

    assert result.risk_reward_ratio == 0.5
    assert result.risk_reward_score == 0


# ---------------------------------------------------------------------------
# Risk/Reward failure modes -- never a guessed score
# ---------------------------------------------------------------------------


def test_stop_on_wrong_side_of_entry_returns_failed_not_a_score():
    # LONG, but stop is ABOVE entry -- backwards.
    bad_params = _long_params(entry=100.0, stop=105.0, target=110.0)

    result = evaluate(_analysis(), bad_params)

    assert result.status == EvaluationStatus.FAILED
    assert result.total_score is None
    assert result.risk_reward_score is None
    assert result.risk_reward_ratio is None
    assert "wrong side" in result.error_message


def test_target_on_wrong_side_of_entry_returns_failed():
    # LONG, but target is BELOW entry -- backwards.
    bad_params = _long_params(entry=100.0, stop=95.0, target=90.0)

    result = evaluate(_analysis(), bad_params)

    assert result.status == EvaluationStatus.FAILED
    assert result.total_score is None


def test_zero_risk_distance_returns_failed_not_a_division_error():
    zero_risk_params = _long_params(entry=100.0, stop=100.0, target=110.0)

    result = evaluate(_analysis(), zero_risk_params)

    assert result.status == EvaluationStatus.FAILED
    assert "zero" in result.error_message.lower()


def test_missing_entry_returns_failed_not_a_guessed_rr():
    result = evaluate(_analysis(), _long_params(entry=None))

    assert result.status == EvaluationStatus.FAILED
    assert result.risk_reward_ratio is None
    assert "entry" in result.error_message


def test_missing_stop_returns_failed():
    result = evaluate(_analysis(), _long_params(stop=None))

    assert result.status == EvaluationStatus.FAILED
    assert "stop" in result.error_message


def test_missing_target_returns_failed():
    result = evaluate(_analysis(), _long_params(target=None))

    assert result.status == EvaluationStatus.FAILED
    assert "target" in result.error_message


def test_missing_direction_returns_failed():
    result = evaluate(_analysis(), _long_params(direction=None))

    assert result.status == EvaluationStatus.FAILED
    assert "direction" in result.error_message


def test_no_trade_params_at_all_returns_failed():
    result = evaluate(_analysis(), None)

    assert result.status == EvaluationStatus.FAILED


# ---------------------------------------------------------------------------
# Failed agent analysis -- never scored
# ---------------------------------------------------------------------------


def test_failed_agent_analysis_returns_failed_evaluation_without_scoring():
    failed_analysis = AgentAnalysisResult(
        status=AgentAnalysisStatus.FAILED,
        analysis_text=None,
        trend_assessment=None,
        structure_assessment=None,
        setup_assessment=None,
        uncertainty=None,
        timestamp=None,
        error_message="No chart to analyze -- capture status is FAILED.",
    )

    result = evaluate(failed_analysis, _long_params())

    assert result.status == EvaluationStatus.FAILED
    assert result.total_score is None
    assert result.trend_score is None
    assert result.risk_reward_score is None
    assert "No agent analysis to evaluate" in result.error_message


# ---------------------------------------------------------------------------
# Subjective scoring bands (via evaluate(), using LOW uncertainty so the
# cap never interferes with reading the raw band score)
# ---------------------------------------------------------------------------


def test_substantive_text_scores_twenty():
    result = evaluate(
        _analysis(uncertainty="LOW", trend_assessment="Clear uptrend, higher highs and higher lows."),
        _long_params(),
    )

    assert result.trend_score == 20


def test_thin_text_scores_ten():
    result = evaluate(
        _analysis(uncertainty="LOW", trend_assessment="Choppy."),
        _long_params(),
    )

    assert result.trend_score == 10


def test_negative_phrase_scores_zero_even_if_long():
    long_but_negative = "There is no clear trend here -- price is just moving sideways without direction."
    result = evaluate(
        _analysis(uncertainty="LOW", trend_assessment=long_but_negative),
        _long_params(),
    )

    assert result.trend_score == 0


def test_empty_text_scores_zero():
    result = evaluate(
        _analysis(uncertainty="LOW", setup_assessment=""),
        _long_params(),
    )

    assert result.entry_score == 0


# ---------------------------------------------------------------------------
# Uncertainty caps -- the hard-coded 20/14/8 behavior
# ---------------------------------------------------------------------------


def test_higher_uncertainty_produces_lower_score_on_identical_input():
    params = _long_params()
    low = evaluate(_analysis(uncertainty="LOW"), params)
    medium = evaluate(_analysis(uncertainty="MEDIUM"), params)
    high = evaluate(_analysis(uncertainty="HIGH"), params)

    assert low.total_score > medium.total_score > high.total_score


def test_low_uncertainty_perfect_input_reaches_the_documented_ceiling_of_100():
    result = evaluate(_analysis(uncertainty="LOW"), _long_params())

    assert result.trend_score == 20
    assert result.structure_score == 20
    assert result.entry_score == 20
    assert result.timing_context_score == 20
    assert result.risk_reward_score == 20
    assert result.total_score == 100


def test_medium_uncertainty_perfect_input_reaches_the_documented_ceiling_of_76():
    result = evaluate(_analysis(uncertainty="MEDIUM"), _long_params())

    assert result.trend_score == 14
    assert result.structure_score == 14
    assert result.entry_score == 14
    assert result.timing_context_score == 14
    assert result.risk_reward_score == 20
    assert result.total_score == 76


def test_high_uncertainty_perfect_input_cannot_exceed_the_documented_ceiling_of_52():
    """
    The four subjective components are capped at 8 each (32 total) under
    HIGH uncertainty, even with otherwise-perfect input. Risk/Reward is
    NOT capped at 8 -- it can still contribute its full 20, which is what
    takes the ceiling from 32 up to 52.
    """
    result = evaluate(_analysis(uncertainty="HIGH"), _long_params())

    assert result.trend_score == 8
    assert result.structure_score == 8
    assert result.entry_score == 8
    assert result.timing_context_score == 8
    assert result.risk_reward_score == 20  # exceeds the 8-point cap -- it's exempt
    assert result.total_score == 52
    assert result.total_score <= 52


def test_risk_reward_is_unchanged_across_all_three_uncertainty_levels():
    params = _long_params()  # RR = 2.0 -> score 20

    low = evaluate(_analysis(uncertainty="LOW"), params)
    medium = evaluate(_analysis(uncertainty="MEDIUM"), params)
    high = evaluate(_analysis(uncertainty="HIGH"), params)

    assert low.risk_reward_ratio == medium.risk_reward_ratio == high.risk_reward_ratio == 2.0
    assert low.risk_reward_score == medium.risk_reward_score == high.risk_reward_score == 20


def test_uncertainty_caps_constant_matches_the_documented_values():
    assert UNCERTAINTY_CAPS == {"LOW": 20, "MEDIUM": 14, "HIGH": 8}
