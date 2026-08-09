# TradePilot AI — tests for the guardrail layer (Milestone 9).
#
# Everything here is pure computation -- no network, no AI, no mocking
# needed. Freshness checks always pass an explicit `now` so results never
# depend on wall-clock time while the test suite runs.

from datetime import datetime, timedelta, timezone

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeParams
from capture.base import CaptureMode, CaptureResult, CaptureStatus
from capture.demo_provider import DemoProvider
from evals.trade_evaluator import EvaluationResult, EvaluationStatus, evaluate
from guardrails.rules import GuardrailOutcome, evaluate_guardrails
from tools.market_data import DemoMarketDataProvider, MarketDataMode, MarketDataStatus, MarketQuote

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fresh_capture(**overrides) -> CaptureResult:
    defaults = dict(
        mode=CaptureMode.LIVE,
        symbol="EURUSD",
        timeframe="1h",
        screenshot_path="screenshots/live/EURUSD_1h_20260101T115950Z.png",
        captured_at=NOW - timedelta(seconds=10),
        status=CaptureStatus.SUCCESS,
        error_message=None,
    )
    defaults.update(overrides)
    return CaptureResult(**defaults)


def _fresh_market_data(**overrides) -> MarketQuote:
    defaults = dict(
        mode=MarketDataMode.LIVE,
        symbol="EURUSD",
        price=1.0950,
        timestamp=NOW - timedelta(seconds=10),
        source="alpha_vantage",
        status=MarketDataStatus.SUCCESS,
        error_message=None,
    )
    defaults.update(overrides)
    return MarketQuote(**defaults)


def _good_analysis(**overrides) -> AgentAnalysisResult:
    """Best possible categories, so evaluate() against _long_params()
    (RR=2.0) reaches the LOW-uncertainty ceiling of 100."""
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
        proposal_has_proposal=False,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
        timestamp=NOW - timedelta(seconds=5),
        error_message=None,
    )
    defaults.update(overrides)
    return AgentAnalysisResult(**defaults)


def _failed_evaluation(**overrides) -> EvaluationResult:
    defaults = dict(
        status=EvaluationStatus.FAILED,
        trend_score=None,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        risk_reward_ratio=None,
        error_message="No agent analysis to evaluate.",
    )
    defaults.update(overrides)
    return EvaluationResult(**defaults)


def _long_params(**overrides) -> TradeParams:
    # entry=100, stop=95 (risk=5), target=110 (reward=10) -> RR = 2.0
    defaults = dict(direction="long", entry=100.0, stop=95.0, target=110.0)
    defaults.update(overrides)
    return TradeParams(**defaults)


def _checks_by_name(report):
    return {c.name: c for c in report.checks}


def _perfect_run(**param_overrides):
    """A fully passing LIVE run: every guardrail should pass, outcome
    READY_FOR_REVIEW. Used as the baseline that individual tests degrade
    one input at a time."""
    capture = _fresh_capture()
    market_data = _fresh_market_data()
    analysis = _good_analysis()
    params = _long_params(**param_overrides)
    evaluation = evaluate(analysis, params)
    return capture, market_data, analysis, evaluation, params


# ---------------------------------------------------------------------------
# Baseline: a perfect run reaches READY_FOR_REVIEW
# ---------------------------------------------------------------------------


def test_perfect_live_run_reaches_ready_for_review():
    capture, market_data, analysis, evaluation, params = _perfect_run()

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    assert report.outcome == GuardrailOutcome.READY_FOR_REVIEW
    assert all(c.passed for c in report.checks)


def test_all_eleven_rules_are_always_present():
    capture, market_data, analysis, evaluation, params = _perfect_run()

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    expected_names = {
        "CAPTURE_SUCCEEDED",
        "CAPTURE_FRESH",
        "MARKET_DATA_SUCCEEDED",
        "MARKET_DATA_FRESH",
        "ANALYSIS_SUCCEEDED",
        "EVALUATION_SUCCEEDED",
        "RISK_REWARD_MINIMUM",
        "TRADE_PARAMS_VALID",
        "UNCERTAINTY_ACCEPTABLE",
        "SCORE_THRESHOLD",
        "SYNTHETIC_DATA",
    }
    assert {c.name for c in report.checks} == expected_names
    assert len(report.checks) == 11


# ---------------------------------------------------------------------------
# No short-circuiting: every rule runs even when an earlier one fails
# ---------------------------------------------------------------------------


def test_all_rules_still_evaluated_when_the_first_one_fails():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    broken_capture = _fresh_capture(status=CaptureStatus.FAILED, screenshot_path=None, error_message="boom")

    report = evaluate_guardrails(broken_capture, market_data, analysis, evaluation, params, now=NOW)

    # 11 rules ran, not just the one that failed first.
    assert len(report.checks) == 11
    checks = _checks_by_name(report)
    assert checks["CAPTURE_SUCCEEDED"].passed is False
    # Rules independent of capture still ran and still passed.
    assert checks["MARKET_DATA_SUCCEEDED"].passed is True
    assert checks["ANALYSIS_SUCCEEDED"].passed is True
    assert checks["SCORE_THRESHOLD"].passed is True


# ---------------------------------------------------------------------------
# a. CAPTURE_SUCCEEDED
# ---------------------------------------------------------------------------


def test_capture_succeeded_passes_on_success():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["CAPTURE_SUCCEEDED"].passed is True


def test_capture_succeeded_fails_and_blocks_on_failed_capture():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    bad_capture = _fresh_capture(status=CaptureStatus.FAILED, screenshot_path=None, captured_at=None)

    report = evaluate_guardrails(bad_capture, market_data, analysis, evaluation, params, now=NOW)

    assert _checks_by_name(report)["CAPTURE_SUCCEEDED"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# b. CAPTURE_FRESH
# ---------------------------------------------------------------------------


def test_capture_fresh_passes_for_a_recent_capture():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["CAPTURE_FRESH"].passed is True


def test_stale_capture_blocks_using_a_timestamp_set_in_the_past():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    stale_capture = _fresh_capture(captured_at=NOW - timedelta(hours=2))

    report = evaluate_guardrails(stale_capture, market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["CAPTURE_FRESH"]
    assert check.passed is False
    assert "old" in check.reason.lower()
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# c. MARKET_DATA_SUCCEEDED
# ---------------------------------------------------------------------------


def test_market_data_succeeded_passes_on_success():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["MARKET_DATA_SUCCEEDED"].passed is True


def test_market_data_succeeded_fails_and_blocks_on_failed_fetch():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    bad_market_data = _fresh_market_data(
        status=MarketDataStatus.FAILED, price=None, timestamp=None, error_message="no key"
    )

    report = evaluate_guardrails(capture, bad_market_data, analysis, evaluation, params, now=NOW)

    assert _checks_by_name(report)["MARKET_DATA_SUCCEEDED"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# d. MARKET_DATA_FRESH -- based on the SOURCE timestamp, not fetch time
# ---------------------------------------------------------------------------


def test_market_data_fresh_passes_for_a_recent_quote():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["MARKET_DATA_FRESH"].passed is True


def test_stale_market_quote_blocks_based_on_source_timestamp():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    # The quote's own reported time is old, even though nothing about
    # "when we fetched it" is tracked separately -- MarketQuote has no
    # such field, by design (see tools/market_data.py).
    stale_market_data = _fresh_market_data(timestamp=NOW - timedelta(hours=2))

    report = evaluate_guardrails(capture, stale_market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["MARKET_DATA_FRESH"]
    assert check.passed is False
    assert "old" in check.reason.lower()
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# e. ANALYSIS_SUCCEEDED
# ---------------------------------------------------------------------------


def test_analysis_succeeded_passes_on_success():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["ANALYSIS_SUCCEEDED"].passed is True


def test_analysis_succeeded_fails_and_blocks_on_failed_analysis():
    capture, market_data, _analysis, _evaluation, params = _perfect_run()
    bad_analysis = AgentAnalysisResult(
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
        proposal_has_proposal=None,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
        timestamp=None,
        error_message="No chart to analyze.",
    )
    bad_evaluation = evaluate(bad_analysis, params)

    report = evaluate_guardrails(capture, market_data, bad_analysis, bad_evaluation, params, now=NOW)

    assert _checks_by_name(report)["ANALYSIS_SUCCEEDED"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# f. EVALUATION_SUCCEEDED
# ---------------------------------------------------------------------------


def test_evaluation_succeeded_passes_on_success():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["EVALUATION_SUCCEEDED"].passed is True


def test_evaluation_succeeded_fails_and_blocks_on_failed_evaluation():
    capture, market_data, analysis, _evaluation, params = _perfect_run()
    bad_evaluation = _failed_evaluation()

    report = evaluate_guardrails(capture, market_data, analysis, bad_evaluation, params, now=NOW)

    assert _checks_by_name(report)["EVALUATION_SUCCEEDED"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# g. RISK_REWARD_MINIMUM
# ---------------------------------------------------------------------------


def test_risk_reward_minimum_passes_at_exactly_the_threshold():
    capture, market_data, analysis, _e, _p = _perfect_run()
    # risk=5, reward=5 -> RR = 1.0, exactly MIN_RISK_REWARD's default.
    params = _long_params(entry=100.0, stop=95.0, target=105.0)
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    assert _checks_by_name(report)["RISK_REWARD_MINIMUM"].passed is True


def test_risk_reward_below_minimum_forces_review_not_a_block():
    capture, market_data, analysis, _e, _p = _perfect_run()
    # risk=10, reward=5 -> RR = 0.5, below the 1.0 minimum.
    params = _long_params(entry=100.0, stop=90.0, target=105.0)
    evaluation = evaluate(analysis, params)
    assert evaluation.status == EvaluationStatus.SUCCESS  # sanity check

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["RISK_REWARD_MINIMUM"]
    assert check.passed is False
    assert "below the minimum" in check.reason
    # A low RR is a review-forcing failure, not a blocking one -- the
    # pipeline worked and produced something to look at.
    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW


# ---------------------------------------------------------------------------
# h. TRADE_PARAMS_VALID
# ---------------------------------------------------------------------------


def test_trade_params_valid_passes_for_coherent_params():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["TRADE_PARAMS_VALID"].passed is True


def test_trade_params_valid_fails_and_blocks_for_stop_on_wrong_side():
    capture, market_data, analysis, _e, _p = _perfect_run()
    bad_params = _long_params(entry=100.0, stop=105.0, target=110.0)  # stop above entry on a LONG
    bad_evaluation = evaluate(analysis, bad_params)

    report = evaluate_guardrails(capture, market_data, analysis, bad_evaluation, bad_params, now=NOW)

    assert _checks_by_name(report)["TRADE_PARAMS_VALID"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED


def test_trade_params_valid_fails_for_missing_params():
    capture, market_data, analysis, _e, _p = _perfect_run()
    missing_params = TradeParams()  # nothing provided
    evaluation = evaluate(analysis, missing_params)

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, missing_params, now=NOW)

    assert _checks_by_name(report)["TRADE_PARAMS_VALID"].passed is False


# ---------------------------------------------------------------------------
# i. UNCERTAINTY_ACCEPTABLE
# ---------------------------------------------------------------------------


def test_uncertainty_acceptable_passes_for_low_and_medium():
    capture, market_data, _a, _e, params = _perfect_run()
    for level in ("LOW", "MEDIUM"):
        analysis = _good_analysis(uncertainty=level)
        evaluation = evaluate(analysis, params)
        report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
        assert _checks_by_name(report)["UNCERTAINTY_ACCEPTABLE"].passed is True, level


def test_high_uncertainty_can_never_reach_ready_for_review():
    capture, market_data, _a, _e, params = _perfect_run()
    analysis = _good_analysis(uncertainty="HIGH")  # otherwise-perfect categories
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["UNCERTAINTY_ACCEPTABLE"]
    assert check.passed is False
    assert "HIGH" in check.reason
    assert report.outcome != GuardrailOutcome.READY_FOR_REVIEW
    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW


# ---------------------------------------------------------------------------
# j. SCORE_THRESHOLD
# ---------------------------------------------------------------------------


def test_score_threshold_passes_for_a_high_score():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    assert evaluation.total_score == 100  # sanity check on the fixture
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["SCORE_THRESHOLD"].passed is True


def test_score_below_threshold_forces_review():
    capture, market_data, _a, _e, _p = _perfect_run()
    # WEAK trend, CHOPPY structure, NONE setup, ELEVATED context -> every
    # subjective component scores 0; only RR (2.0) contributes, total 20.
    weak_analysis = _good_analysis(
        trend_direction="UP",
        trend_quality="WEAK",
        structure_quality="CHOPPY",
        setup_quality="NONE",
        context_risk="ELEVATED",
    )
    params = _long_params()
    evaluation = evaluate(weak_analysis, params)
    assert evaluation.total_score == 20  # sanity check

    report = evaluate_guardrails(capture, market_data, weak_analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["SCORE_THRESHOLD"]
    assert check.passed is False
    assert "below the minimum" in check.reason
    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW


# ---------------------------------------------------------------------------
# k. SYNTHETIC_DATA
# ---------------------------------------------------------------------------


def test_synthetic_data_passes_for_live_capture_and_live_market_data():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert _checks_by_name(report)["SYNTHETIC_DATA"].passed is True


def test_demo_capture_can_never_reach_ready_for_review_even_with_a_perfect_score():
    _c, market_data, analysis, evaluation, params = _perfect_run()
    demo_capture = _fresh_capture(mode=CaptureMode.DEMO)
    assert evaluation.total_score == 100  # confirms this really is a perfect score

    report = evaluate_guardrails(demo_capture, market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["SYNTHETIC_DATA"]
    assert check.passed is False
    assert "DEMO" in check.reason
    assert report.outcome != GuardrailOutcome.READY_FOR_REVIEW
    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW


def test_demo_market_data_can_never_reach_ready_for_review_even_with_a_perfect_score():
    capture, _m, analysis, evaluation, params = _perfect_run()
    demo_market_data = _fresh_market_data(mode=MarketDataMode.DEMO)
    assert evaluation.total_score == 100

    report = evaluate_guardrails(capture, demo_market_data, analysis, evaluation, params, now=NOW)

    check = _checks_by_name(report)["SYNTHETIC_DATA"]
    assert check.passed is False
    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW


# ---------------------------------------------------------------------------
# There is no approved state, anywhere
# ---------------------------------------------------------------------------


def test_guardrail_outcome_has_exactly_three_states_and_none_of_them_is_approved():
    values = {member.value for member in GuardrailOutcome}
    assert values == {"BLOCKED", "REQUIRES_REVIEW", "READY_FOR_REVIEW"}
    assert not any("APPROV" in v for v in values)


def test_no_scenario_in_this_file_ever_produces_an_approved_looking_outcome():
    """Every report built anywhere in this file resolves to one of
    exactly three GuardrailOutcome members -- enforced by the type
    system, asserted here as a direct, explicit check."""
    capture, market_data, analysis, evaluation, params = _perfect_run()
    report = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    assert report.outcome in (
        GuardrailOutcome.BLOCKED,
        GuardrailOutcome.REQUIRES_REVIEW,
        GuardrailOutcome.READY_FOR_REVIEW,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_inputs_same_now_produce_identical_reports():
    capture, market_data, analysis, evaluation, params = _perfect_run()

    first = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)
    second = evaluate_guardrails(capture, market_data, analysis, evaluation, params, now=NOW)

    assert first == second


def test_determinism_holds_for_a_blocked_scenario_too():
    capture, market_data, analysis, evaluation, params = _perfect_run()
    stale_capture = _fresh_capture(captured_at=NOW - timedelta(hours=5))

    first = evaluate_guardrails(stale_capture, market_data, analysis, evaluation, params, now=NOW)
    second = evaluate_guardrails(stale_capture, market_data, analysis, evaluation, params, now=NOW)

    assert first == second
    assert first.outcome == GuardrailOutcome.BLOCKED


# ---------------------------------------------------------------------------
# Milestone 9 fix: a real DEMO run must reach REQUIRES_REVIEW, never
# BLOCKED and never READY_FOR_REVIEW. Uses the REAL DemoProvider and
# DemoMarketDataProvider (not the hand-built _fresh_* fixtures above) so
# this actually exercises the fixed timestamp-generation code, not just
# a fixture that happens to look fresh.
# ---------------------------------------------------------------------------


def test_real_demo_market_data_fetch_passes_market_data_fresh():
    capture, _m, analysis, _e, params = _perfect_run()
    real_demo_market_data = DemoMarketDataProvider().get_quote("EURUSD")
    assert real_demo_market_data.status == MarketDataStatus.SUCCESS  # sanity check
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(
        capture, real_demo_market_data, analysis, evaluation, params, now=datetime.now(timezone.utc)
    )

    assert _checks_by_name(report)["MARKET_DATA_FRESH"].passed is True


def test_real_demo_capture_passes_capture_fresh():
    _c, market_data, analysis, _e, params = _perfect_run()
    real_demo_capture = DemoProvider().capture("EURUSD", "1h")
    assert real_demo_capture.status == CaptureStatus.SUCCESS  # sanity check
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(
        real_demo_capture, market_data, analysis, evaluation, params, now=datetime.now(timezone.utc)
    )

    assert _checks_by_name(report)["CAPTURE_FRESH"].passed is True


def test_full_real_demo_run_reaches_requires_review_with_synthetic_data_as_the_reason():
    """
    The actual regression this fix closes: a complete DEMO-mode run
    (real DemoProvider + real DemoMarketDataProvider, not hand-built
    fixtures), with an otherwise-perfect agent analysis, must land on
    REQUIRES_REVIEW -- never BLOCKED (the bug: MARKET_DATA_FRESH used to
    fail on the fixture's fixed 2024 timestamp) and never READY_FOR_REVIEW
    (SYNTHETIC_DATA must still catch it). SYNTHETIC_DATA must be the
    *only* failing rule.
    """
    # `now` is captured AFTER both provider calls, not before -- capture()
    # and get_quote() each generate their own datetime.now(utc) a moment
    # later than any "now" captured earlier would be, which would make
    # captured_at/timestamp look like they're from the future relative to
    # an earlier "now" and trip the (correct, intentional) "timestamp is
    # in the future" rejection. Real callers don't have this problem --
    # they compute `now` once, right before checking, same as here.
    demo_capture = DemoProvider().capture("EURUSD", "1h")
    demo_market_data = DemoMarketDataProvider().get_quote("EURUSD")
    now = datetime.now(timezone.utc)
    analysis = _good_analysis(timestamp=now)
    params = _long_params()
    evaluation = evaluate(analysis, params)
    assert evaluation.total_score == 100  # a genuinely perfect score

    report = evaluate_guardrails(demo_capture, demo_market_data, analysis, evaluation, params, now=now)

    assert report.outcome == GuardrailOutcome.REQUIRES_REVIEW
    checks = _checks_by_name(report)
    failing = [c.name for c in report.checks if not c.passed]
    assert failing == ["SYNTHETIC_DATA"]
    assert checks["MARKET_DATA_FRESH"].passed is True
    assert checks["CAPTURE_FRESH"].passed is True


def test_full_real_demo_run_never_reaches_ready_for_review():
    demo_capture = DemoProvider().capture("EURUSD", "1h")
    demo_market_data = DemoMarketDataProvider().get_quote("EURUSD")
    now = datetime.now(timezone.utc)
    analysis = _good_analysis(timestamp=now)
    params = _long_params()
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(demo_capture, demo_market_data, analysis, evaluation, params, now=now)

    assert report.outcome != GuardrailOutcome.READY_FOR_REVIEW
    assert report.outcome != GuardrailOutcome.BLOCKED


def test_genuinely_stale_live_quote_still_blocks_freshness_not_weakened():
    """Confirms today's fix is scoped to the demo provider only -- LIVE
    freshness enforcement is exactly as strict as it was before."""
    capture, _m, analysis, _e, params = _perfect_run()
    stale_live_market_data = _fresh_market_data(
        mode=MarketDataMode.LIVE, timestamp=NOW - timedelta(hours=3)
    )
    evaluation = evaluate(analysis, params)

    report = evaluate_guardrails(capture, stale_live_market_data, analysis, evaluation, params, now=NOW)

    assert _checks_by_name(report)["MARKET_DATA_FRESH"].passed is False
    assert report.outcome == GuardrailOutcome.BLOCKED
