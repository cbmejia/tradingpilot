# TradePilot AI — tests for the evaluation engine (Milestone 8, revised
# to the v2 category-based rubric).
#
# Everything here is pure computation -- no network, no mocking needed,
# no AI calls exist to mock in the first place.

import inspect
from datetime import datetime, timezone

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams
from evals.trade_evaluator import EvaluationStatus, UNCERTAINTY_CAPS, evaluate


def _analysis(**overrides) -> AgentAnalysisResult:
    """
    A 'perfect' analysis by default: every categorical field is the best
    option in its set (STRONG uptrend, CLEAN structure, TEXTBOOK setup,
    LOW context risk), so each subjective component scores 20 before any
    uncertainty cap is applied. Prose fields are present but irrelevant
    to scoring in v2 -- deliberately kept short here to prove that.
    """
    defaults = dict(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="Uptrend.",
        trend_assessment="Up.",
        structure_assessment="Clean.",
        setup_assessment="Good.",
        uncertainty="LOW",
        trend_direction="UP",
        trend_quality="STRONG",
        structure_quality="CLEAN",
        setup_quality="TEXTBOOK",
        context_risk="LOW",
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
# v2 fix: verbosity must no longer affect the score
# ---------------------------------------------------------------------------


def test_prose_length_does_not_affect_score_when_categories_match():
    """
    The whole point of the v2 revision: two analyses with identical
    categories but wildly different prose length must score identically.
    """
    short = _analysis(
        analysis_text="Up.",
        trend_assessment="Up.",
        structure_assessment="Clean.",
        setup_assessment="Good.",
    )
    long = _analysis(
        analysis_text=(
            "Price has been in a persistent, well-defined uptrend for the entire "
            "visible window, printing a clean sequence of higher highs and higher "
            "lows with very little overlap between candles, and the most recent "
            "pullback is holding cleanly above the rising trendline, offering a "
            "textbook continuation entry with well-defined invalidation below the "
            "most recent swing low and a clear measured-move target overhead."
        ),
        trend_assessment=(
            "A strong, sustained uptrend is visible across the full window, with "
            "consistently higher highs and higher lows and no meaningful violation "
            "of the trendline at any point."
        ),
        structure_assessment=(
            "The structure is exceptionally clean: minimal candle overlap, well-"
            "spaced swing points, and no choppy consolidation anywhere in view."
        ),
        setup_assessment=(
            "This is about as textbook a pullback entry as this pattern produces, "
            "with price respecting the trendline precisely and volume tapering off "
            "into the retracement before resuming."
        ),
    )

    short_result = evaluate(short, _long_params())
    long_result = evaluate(long, _long_params())

    assert short_result.total_score == long_result.total_score
    assert short_result.trend_score == long_result.trend_score
    assert short_result.structure_score == long_result.structure_score
    assert short_result.entry_score == long_result.entry_score
    assert short_result.timing_context_score == long_result.timing_context_score


# ---------------------------------------------------------------------------
# Category -> score band mapping
# ---------------------------------------------------------------------------


def test_trend_strong_scores_twenty():
    result = evaluate(_analysis(trend_direction="UP", trend_quality="STRONG"), _long_params())
    assert result.trend_score == 20


def test_trend_moderate_scores_ten():
    result = evaluate(_analysis(trend_direction="UP", trend_quality="MODERATE"), _long_params())
    assert result.trend_score == 10


def test_trend_weak_scores_zero():
    result = evaluate(_analysis(trend_direction="DOWN", trend_quality="WEAK"), _long_params())
    assert result.trend_score == 0


def test_trend_sideways_scores_zero_even_with_strong_quality():
    """direction is a gate -- SIDEWAYS means there's no trend to credit,
    regardless of what quality claims."""
    result = evaluate(
        _analysis(trend_direction="SIDEWAYS", trend_quality="STRONG"), _long_params()
    )
    assert result.trend_score == 0


def test_structure_quality_bands():
    assert evaluate(_analysis(structure_quality="CLEAN"), _long_params()).structure_score == 20
    assert evaluate(_analysis(structure_quality="MIXED"), _long_params()).structure_score == 10
    assert evaluate(_analysis(structure_quality="CHOPPY"), _long_params()).structure_score == 0


def test_setup_quality_bands():
    assert evaluate(_analysis(setup_quality="TEXTBOOK"), _long_params()).entry_score == 20
    assert evaluate(_analysis(setup_quality="ACCEPTABLE"), _long_params()).entry_score == 15
    assert evaluate(_analysis(setup_quality="MARGINAL"), _long_params()).entry_score == 5
    assert evaluate(_analysis(setup_quality="NONE"), _long_params()).entry_score == 0


def test_context_risk_bands_are_inverted():
    """LOW risk is favorable (high score); ELEVATED risk is unfavorable
    (low score) -- the opposite direction from the other category
    fields, where the 'best-sounding' word scores highest."""
    assert evaluate(_analysis(context_risk="LOW"), _long_params()).timing_context_score == 20
    assert evaluate(_analysis(context_risk="MODERATE"), _long_params()).timing_context_score == 10
    assert evaluate(_analysis(context_risk="ELEVATED"), _long_params()).timing_context_score == 0


def test_unclear_scores_at_or_near_zero_for_every_component():
    result = evaluate(
        _analysis(
            trend_direction="UNCLEAR",
            trend_quality="UNCLEAR",
            structure_quality="UNCLEAR",
            setup_quality="UNCLEAR",
            context_risk="UNCLEAR",
        ),
        _long_params(),
    )

    assert result.trend_score == 0
    assert result.structure_score == 0
    assert result.entry_score == 0
    assert result.timing_context_score == 0
    # Risk/Reward is arithmetic and unaffected by any of this.
    assert result.risk_reward_score == 20


def test_out_of_set_category_value_returns_failed_not_a_crash():
    """
    Defense in depth: the agent already rejects out-of-set values before
    a SUCCESS result can exist, but if a bad value ever reached the
    evaluator directly (e.g. hand-constructed in a test or future code),
    it must fail cleanly, never crash or silently mis-score.
    """
    bad_analysis = _analysis(setup_quality="AMAZING")  # not a real category

    result = evaluate(bad_analysis, _long_params())

    assert result.status == EvaluationStatus.FAILED
    assert result.total_score is None
    assert "setup_quality" in result.error_message


# ---------------------------------------------------------------------------
# Risk/Reward arithmetic (unchanged from v1)
# ---------------------------------------------------------------------------


def test_risk_reward_computed_correctly_for_long():
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=95.0, target=110.0))
    assert result.status == EvaluationStatus.SUCCESS
    assert result.risk_reward_ratio == 2.0
    assert result.risk_reward_score == 20


def test_risk_reward_computed_correctly_for_short():
    result = evaluate(_analysis(), _short_params(entry=100.0, stop=105.0, target=90.0))
    assert result.status == EvaluationStatus.SUCCESS
    assert result.risk_reward_ratio == 2.0
    assert result.risk_reward_score == 20


def test_risk_reward_marginal_band():
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=95.0, target=105.0))
    assert result.risk_reward_ratio == 1.0
    assert result.risk_reward_score == 10


def test_risk_reward_poor_band():
    result = evaluate(_analysis(), _long_params(entry=100.0, stop=90.0, target=105.0))
    assert result.risk_reward_ratio == 0.5
    assert result.risk_reward_score == 0


def test_stop_on_wrong_side_of_entry_returns_failed_not_a_score():
    bad_params = _long_params(entry=100.0, stop=105.0, target=110.0)
    result = evaluate(_analysis(), bad_params)
    assert result.status == EvaluationStatus.FAILED
    assert result.total_score is None
    assert result.risk_reward_score is None
    assert result.risk_reward_ratio is None
    assert "wrong side" in result.error_message


def test_target_on_wrong_side_of_entry_returns_failed():
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
        trend_direction=None,
        trend_quality=None,
        structure_quality=None,
        setup_quality=None,
        context_risk=None,
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
# Uncertainty caps -- the hard-coded 20/14/8 behavior (unchanged from v1)
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
