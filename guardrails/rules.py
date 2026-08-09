# TradePilot AI — deterministic guardrails: the last line of defense
# before a human ever sees a run.
#
# In plain terms: this file never decides a run is good. It only ever
# decides whether a run is trustworthy enough to be worth a human's
# attention, or broken enough that there's nothing meaningful to show
# them at all. Eleven independent checks run every time, every one of
# them is recorded (pass or fail), and the worst outcome among them wins.
#
# THE HARD RULES:
# - Deterministic. No AI call anywhere in this file. No randomness. Same
#   inputs (including the same `now`) always produce the same verdict.
#   Freshness checks are explicitly time-dependent by design -- that's
#   the one place "same inputs" includes a clock reading, and it's
#   supplied as a real parameter (see `now` below), not read implicitly,
#   so tests can pin it and get fully reproducible results.
# - Guardrails can only DOWNGRADE. There is no code path anywhere in this
#   file that raises a score, approves a run, or upgrades a failing run
#   into a passing one. The three possible outcomes are BLOCKED,
#   REQUIRES_REVIEW, and READY_FOR_REVIEW -- notice there is no
#   "APPROVED" among them. Nothing in this system approves a run without
#   a human; that's Milestone 10.
# - Every rule runs independently, every time. Nothing short-circuits on
#   an earlier failure -- all eleven checks are always evaluated and all
#   eleven results are always returned, so the audit trail always shows
#   the complete picture of what passed and what didn't, not just the
#   first problem found.

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from dotenv import load_dotenv

from agents.trade_agent import (
    AgentAnalysisResult,
    AgentAnalysisStatus,
    ConfirmationAnalysisResult,
    ConfirmationAnalysisStatus,
    TradeParams,
)
from capture.base import CaptureMode, CaptureResult, CaptureStatus
from evals.trade_evaluator import EvaluationResult, EvaluationStatus, compute_risk_reward
from tools.market_data import MarketDataMode, MarketDataStatus, MarketQuote

load_dotenv()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


# All thresholds are read from .env, with the defaults below used when
# unset. Never hardcoded inline elsewhere in this file -- change a
# threshold here (or in .env), not in the middle of a rule function.
CAPTURE_MAX_AGE_SECONDS = _env_float("CAPTURE_MAX_AGE_SECONDS", 300.0)
MARKET_DATA_MAX_AGE_SECONDS = _env_float("MARKET_DATA_MAX_AGE_SECONDS", 900.0)
MIN_RISK_REWARD = _env_float("MIN_RISK_REWARD", 1.0)
MIN_TOTAL_SCORE = _env_int("MIN_TOTAL_SCORE", 60)


class GuardrailOutcome(str, Enum):
    """
    The only three states a run can end up in after guardrails run.
    There is deliberately no "APPROVED" state -- see Milestone 10.
    """

    BLOCKED = "BLOCKED"  # a hard prerequisite failed -- nothing to review
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # scored, but a human must decide
    READY_FOR_REVIEW = "READY_FOR_REVIEW"  # passed every rule, still needs a human


@dataclass(frozen=True)
class GuardrailCheck:
    """One rule's result. Every field here is what gets persisted to the
    GuardrailResult table (guardrail_name/passed/reason/timestamp)."""

    name: str
    passed: bool
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class GuardrailReport:
    """The complete guardrail pass for one run: every check's result, and
    the single overall outcome derived from them."""

    outcome: GuardrailOutcome
    checks: tuple[GuardrailCheck, ...]


# ---------------------------------------------------------------------------
# Individual rules. Each returns (passed, reason) -- pure functions, no
# side effects, no shared state between them.
# ---------------------------------------------------------------------------


def _capture_succeeded(capture_result: CaptureResult) -> tuple[bool, str]:
    if capture_result.status == CaptureStatus.SUCCESS:
        return True, "Chart capture succeeded."
    detail = capture_result.error_message or "no error message provided"
    return False, f"Chart capture did not succeed (status={capture_result.status.value}): {detail}"


def _capture_fresh(
    capture_result: CaptureResult, now: datetime, max_age_seconds: float
) -> tuple[bool, str]:
    if capture_result.captured_at is None:
        return False, "No capture timestamp available to check freshness."

    age_seconds = (now - capture_result.captured_at).total_seconds()
    if age_seconds < 0:
        return False, (
            f"Capture timestamp ({capture_result.captured_at.isoformat()}) is in the "
            f"future relative to now ({now.isoformat()}); refusing to trust it."
        )
    if age_seconds > max_age_seconds:
        return False, (
            f"Chart is {age_seconds:.0f}s old, older than the {max_age_seconds:.0f}s limit "
            f"(captured_at={capture_result.captured_at.isoformat()})."
        )
    return True, f"Chart is {age_seconds:.0f}s old, within the {max_age_seconds:.0f}s limit."


def _market_data_succeeded(market_data_result: MarketQuote) -> tuple[bool, str]:
    if market_data_result.status == MarketDataStatus.SUCCESS:
        return True, "Market data fetch succeeded."
    detail = market_data_result.error_message or "no error message provided"
    return False, (
        f"Market data fetch did not succeed (status={market_data_result.status.value}): {detail}"
    )


def _market_data_fresh(
    market_data_result: MarketQuote, now: datetime, max_age_seconds: float
) -> tuple[bool, str]:
    if market_data_result.timestamp is None:
        return False, "No market data quote timestamp available to check freshness."

    # This is the SOURCE's own quote timestamp, not the time we fetched
    # it -- see MarketQuote's docstring in tools/market_data.py.
    age_seconds = (now - market_data_result.timestamp).total_seconds()
    if age_seconds < 0:
        return False, (
            f"Quote timestamp ({market_data_result.timestamp.isoformat()}) is in the "
            f"future relative to now ({now.isoformat()}); refusing to trust it."
        )
    if age_seconds > max_age_seconds:
        return False, (
            f"Quote is {age_seconds:.0f}s old, older than the {max_age_seconds:.0f}s limit "
            f"(source timestamp={market_data_result.timestamp.isoformat()})."
        )
    return True, f"Quote is {age_seconds:.0f}s old, within the {max_age_seconds:.0f}s limit."


def _analysis_succeeded(agent_analysis: AgentAnalysisResult) -> tuple[bool, str]:
    if agent_analysis.status == AgentAnalysisStatus.SUCCESS:
        return True, "Agent analysis succeeded."
    detail = agent_analysis.error_message or "no error message provided"
    return False, f"Agent analysis did not succeed (status={agent_analysis.status.value}): {detail}"


def _evaluation_succeeded(evaluation_result: EvaluationResult) -> tuple[bool, str]:
    if evaluation_result.status == EvaluationStatus.SUCCESS:
        return True, "Evaluation succeeded."
    detail = evaluation_result.error_message or "no error message provided"
    return False, f"Evaluation did not succeed (status={evaluation_result.status.value}): {detail}"


def _risk_reward_minimum(
    evaluation_result: EvaluationResult, min_risk_reward: float
) -> tuple[bool, str]:
    if evaluation_result.risk_reward_ratio is None:
        return False, "No risk/reward ratio available to check against the minimum."
    ratio = evaluation_result.risk_reward_ratio
    if ratio < min_risk_reward:
        return False, f"Risk/reward ratio {ratio:.2f} is below the minimum of {min_risk_reward:.2f}."
    return True, f"Risk/reward ratio {ratio:.2f} meets the minimum of {min_risk_reward:.2f}."


def _trade_params_valid(trade_params: TradeParams) -> tuple[bool, str]:
    # Reuses the evaluator's own RR arithmetic (not a second, potentially
    # divergent implementation of the same LONG/SHORT logic) so "valid"
    # means exactly what it means to the evaluator, and no more.
    _ratio, error = compute_risk_reward(
        trade_params.direction, trade_params.entry, trade_params.stop, trade_params.target
    )
    if error is not None:
        return False, f"Trade parameters are not valid: {error}"
    return True, "Entry, stop, and target are present and coherent for the stated direction."


def _uncertainty_acceptable(agent_analysis: AgentAnalysisResult) -> tuple[bool, str]:
    if agent_analysis.uncertainty is None:
        return False, "No agent uncertainty value available to check."
    if agent_analysis.uncertainty == "HIGH":
        return False, "Agent uncertainty is HIGH; a human must review this run."
    return True, f"Agent uncertainty is {agent_analysis.uncertainty}."


def _score_threshold(evaluation_result: EvaluationResult, min_total_score: int) -> tuple[bool, str]:
    if evaluation_result.total_score is None:
        return False, "No total score available to check against the minimum."
    score = evaluation_result.total_score
    if score < min_total_score:
        return False, f"Total score {score} is below the minimum of {min_total_score}."
    return True, f"Total score {score} meets the minimum of {min_total_score}."


def _synthetic_data(
    capture_result: CaptureResult, market_data_result: MarketQuote
) -> tuple[bool, str]:
    demo_sources = []
    if capture_result.mode == CaptureMode.DEMO:
        demo_sources.append("chart capture")
    if market_data_result.mode == MarketDataMode.DEMO:
        demo_sources.append("market data")

    if demo_sources:
        return False, (
            f"Run uses DEMO/sample data ({', '.join(demo_sources)}). A run built on "
            f"sample data must always require human review and must never be "
            f"presentable as a validated live one."
        )
    return True, "Both chart capture and market data are LIVE-sourced -- not synthetic."


def _cross_timeframe_agreement(
    primary_agent_analysis: AgentAnalysisResult,
    confirmation_timeframe: Optional[str],
    confirmation_capture_result: Optional[CaptureResult],
    confirmation_agent_result: Optional[ConfirmationAnalysisResult],
    confirmation_capture_matches_primary_hash: bool,
    force_scenario_active: bool = False,
) -> tuple[bool, str]:
    """
    7A Iteration 2. Orchestrator-derived, never agent-stated: the
    confirmation call (agents/trade_agent.py's TradeAgent.
    analyze_confirmation(), a SEPARATE Claude call from the primary
    analyze()) only ever reports its OWN trend_direction/trend_quality for
    the confirmation chart -- this function is the one place that decides
    whether that agrees with the primary read. The agent never states
    "agreement" itself, the same reason 7A Iteration 1's proposal
    coherence is derived here-in-spirit (backend/orchestrator.py, via
    compute_risk_reward()) rather than trusted from the model.

    Fails closed in every case where agreement genuinely cannot be
    confirmed -- a real disagreement, a failed confirmation capture, an
    identical-hash capture (the timeframe switch may not have taken
    effect), a visible-timeframe mismatch, or either side being
    SIDEWAYS/UNCLEAR must never look the same as a real, confirmed
    agreement. The two exceptions are both N/A, but for genuinely
    different reasons, and are reported with genuinely different reason
    text -- never collapsed into one generic "N/A" string: the primary
    timeframe already being at the top of the fixed ladder (nothing to
    compare against, structurally), vs. a Milestone 12 force_scenario run
    deliberately never exercising the confirmation path at all (see
    backend/orchestrator.py's run_pipeline() docstring). Both pass rather
    than penalizing a run for a reason that has nothing to do with its own
    chart.

    Every FAILING branch below also gets its own distinct reason text, not
    shared with any other branch -- in particular, "primary read
    non-directional" and "confirmation read non-directional" are reported
    separately (checked in that order; if both sides are non-directional,
    the primary-side reason wins, since that's the more fundamental
    problem) rather than the earlier "X and/or Y is not directional"
    phrasing, which made it impossible to tell which side actually failed
    without reading raw category values out of the message by hand.

    confirmation_capture_matches_primary_hash is computed by
    backend/orchestrator.py (which already has both screenshot paths in
    hand right after capturing them), not here -- this function stays a
    pure comparison over its inputs, the same "no ambient state, only
    explicit parameters" principle CAPTURE_FRESH/MARKET_DATA_FRESH already
    use for `now`.

    force_scenario_active: True whenever backend/orchestrator.py's
    run_pipeline() is running under a Milestone 12 force_scenario -- see
    that function's own module docstring for why the confirmation path is
    never exercised in that case. Only ever affects this function's
    behavior when confirmation_timeframe is None (which the orchestrator
    guarantees whenever force_scenario is active); otherwise ignored.
    """
    if confirmation_timeframe is None:
        if force_scenario_active:
            return True, (
                "N/A: suppressed by force_scenario -- this run's pipeline was deliberately "
                "altered by a Milestone 12 testing scenario, which never exercises 7A "
                "Iteration 2's multi-timeframe confirmation path. This is not a failure."
            )
        return True, (
            "N/A: primary at top of ladder -- the primary timeframe is already at the top "
            "of the fixed ladder; no confirmation timeframe exists to compare against."
        )

    if confirmation_capture_result is None or confirmation_capture_result.status != CaptureStatus.SUCCESS:
        detail = (
            f": {confirmation_capture_result.error_message}"
            if confirmation_capture_result and confirmation_capture_result.error_message
            else "."
        )
        return False, (
            f"Confirmation capture failed{detail} Cross-timeframe agreement cannot be "
            f"confirmed."
        )

    if confirmation_capture_matches_primary_hash:
        return False, (
            "Identical image hash: the confirmation capture is byte-identical to the "
            "primary capture, suggesting the timeframe switch did not actually take "
            "effect. Cross-timeframe agreement cannot be confirmed."
        )

    if confirmation_agent_result is None or confirmation_agent_result.status != ConfirmationAnalysisStatus.SUCCESS:
        detail = (
            f": {confirmation_agent_result.error_message}"
            if confirmation_agent_result and confirmation_agent_result.error_message
            else "."
        )
        return False, (
            f"Confirmation analysis did not succeed{detail} Cross-timeframe agreement "
            f"cannot be confirmed."
        )

    visible = (confirmation_agent_result.visible_timeframe or "").strip().lower()
    if visible != confirmation_timeframe.strip().lower():
        return False, (
            f"Timeframe echo mismatch: the confirmation call reported a visible timeframe "
            f"of {confirmation_agent_result.visible_timeframe!r}, which does not match the "
            f"requested confirmation timeframe {confirmation_timeframe!r}. Cross-timeframe "
            f"agreement cannot be confirmed."
        )

    if primary_agent_analysis.status != AgentAnalysisStatus.SUCCESS:
        return False, "Primary analysis did not succeed. Cross-timeframe agreement cannot be confirmed."

    primary_direction = primary_agent_analysis.trend_direction
    confirmation_direction = confirmation_agent_result.trend_direction

    if primary_direction in ("SIDEWAYS", "UNCLEAR"):
        return False, (
            f"Primary read non-directional: primary trend is {primary_direction}. "
            f"Cross-timeframe agreement cannot be confirmed."
        )

    if confirmation_direction in ("SIDEWAYS", "UNCLEAR"):
        return False, (
            f"Confirmation read non-directional: confirmation trend is "
            f"{confirmation_direction}. Cross-timeframe agreement cannot be confirmed."
        )

    if primary_direction == confirmation_direction:
        return True, (
            f"Primary trend ({primary_direction}) and confirmation trend "
            f"({confirmation_direction}) agree."
        )

    return False, (
        f"Primary trend ({primary_direction}) and confirmation trend "
        f"({confirmation_direction}) disagree."
    )


# Rules whose failure means there is nothing meaningful to review -- the
# pipeline itself didn't produce usable output. Any failure here forces
# BLOCKED, regardless of what any other rule says.
BLOCKING_RULES = frozenset(
    {
        "CAPTURE_SUCCEEDED",
        "CAPTURE_FRESH",
        "MARKET_DATA_SUCCEEDED",
        "MARKET_DATA_FRESH",
        "ANALYSIS_SUCCEEDED",
        "EVALUATION_SUCCEEDED",
        "TRADE_PARAMS_VALID",
    }
)

# Rules whose failure means the pipeline worked, but the result isn't
# good, certain, or real enough to skip a human's judgment. Any failure
# here forces REQUIRES_REVIEW (unless a BLOCKING rule also failed, which
# takes priority).
REVIEW_FORCING_RULES = frozenset(
    {
        "RISK_REWARD_MINIMUM",
        "UNCERTAINTY_ACCEPTABLE",
        "SCORE_THRESHOLD",
        "SYNTHETIC_DATA",
        "CROSS_TIMEFRAME_AGREEMENT",
    }
)


def outcome_from_results(results) -> Optional[GuardrailOutcome]:
    """
    Derives the overall GuardrailOutcome from a set of already-stored
    results -- e.g. a run's GuardrailResult database rows, read back as
    (guardrail_name, passed) pairs -- rather than from a live
    evaluate_guardrails() call.

    Uses the exact same BLOCKING_RULES/REVIEW_FORCING_RULES
    classification evaluate_guardrails() uses, so a run's outcome is
    always derived the same way whether it's being computed live or
    reconstructed from storage (e.g. by the human-review endpoint,
    Milestone 10).

    Returns None if `results` is empty -- there is no evidence
    guardrails ever ran for this run, so no outcome can be claimed
    (treated the same as BLOCKED by anything that gates on "must not be
    BLOCKED," since "unknown" is not a safer thing to assume than
    "blocked").

    results: an iterable of (guardrail_name, passed) pairs.
    """
    results = list(results)
    if not results:
        return None

    blocked = any(not passed for name, passed in results if name in BLOCKING_RULES)
    needs_review = any(not passed for name, passed in results if name in REVIEW_FORCING_RULES)

    if blocked:
        return GuardrailOutcome.BLOCKED
    if needs_review:
        return GuardrailOutcome.REQUIRES_REVIEW
    return GuardrailOutcome.READY_FOR_REVIEW


def evaluate_guardrails(
    capture_result: CaptureResult,
    market_data_result: MarketQuote,
    agent_analysis: AgentAnalysisResult,
    evaluation_result: EvaluationResult,
    trade_params: Optional[TradeParams] = None,
    *,
    now: Optional[datetime] = None,
    capture_max_age_seconds: Optional[float] = None,
    market_data_max_age_seconds: Optional[float] = None,
    min_risk_reward: Optional[float] = None,
    min_total_score: Optional[int] = None,
    confirmation_timeframe: Optional[str] = None,
    confirmation_capture_result: Optional[CaptureResult] = None,
    confirmation_agent_result: Optional[ConfirmationAnalysisResult] = None,
    confirmation_capture_matches_primary_hash: bool = False,
    force_scenario_active: bool = False,
) -> GuardrailReport:
    """
    Runs all twelve guardrails and derives the overall outcome. Every
    rule is evaluated regardless of whether an earlier one failed.

    now: the "current time" freshness checks compare against. Defaults
    to datetime.now(timezone.utc) for real use; tests pass a fixed value
    so the same inputs always produce the same verdict, including for
    the two rules that are legitimately time-dependent by design.

    The four *_seconds/min_* keyword arguments override the module-level
    defaults (themselves read from .env) -- mainly for tests; normal
    callers leave them as None and get the configured thresholds.

    confirmation_timeframe/confirmation_capture_result/
    confirmation_agent_result/confirmation_capture_matches_primary_hash/
    force_scenario_active (7A Iteration 2) feed CROSS_TIMEFRAME_AGREEMENT --
    see _cross_timeframe_agreement() above for what each one means. All
    default to values that make the rule report N/A (confirmation_timeframe
    stays None), so a caller that doesn't pass any of them gets the exact
    behavior this function had before this iteration for every other rule.
    """
    trade_params = trade_params or TradeParams()
    now = now or datetime.now(timezone.utc)
    capture_max_age_seconds = (
        capture_max_age_seconds if capture_max_age_seconds is not None else CAPTURE_MAX_AGE_SECONDS
    )
    market_data_max_age_seconds = (
        market_data_max_age_seconds
        if market_data_max_age_seconds is not None
        else MARKET_DATA_MAX_AGE_SECONDS
    )
    min_risk_reward = min_risk_reward if min_risk_reward is not None else MIN_RISK_REWARD
    min_total_score = min_total_score if min_total_score is not None else MIN_TOTAL_SCORE

    rule_results = [
        ("CAPTURE_SUCCEEDED", _capture_succeeded(capture_result)),
        ("CAPTURE_FRESH", _capture_fresh(capture_result, now, capture_max_age_seconds)),
        ("MARKET_DATA_SUCCEEDED", _market_data_succeeded(market_data_result)),
        (
            "MARKET_DATA_FRESH",
            _market_data_fresh(market_data_result, now, market_data_max_age_seconds),
        ),
        ("ANALYSIS_SUCCEEDED", _analysis_succeeded(agent_analysis)),
        ("EVALUATION_SUCCEEDED", _evaluation_succeeded(evaluation_result)),
        ("RISK_REWARD_MINIMUM", _risk_reward_minimum(evaluation_result, min_risk_reward)),
        ("TRADE_PARAMS_VALID", _trade_params_valid(trade_params)),
        ("UNCERTAINTY_ACCEPTABLE", _uncertainty_acceptable(agent_analysis)),
        ("SCORE_THRESHOLD", _score_threshold(evaluation_result, min_total_score)),
        ("SYNTHETIC_DATA", _synthetic_data(capture_result, market_data_result)),
        (
            "CROSS_TIMEFRAME_AGREEMENT",
            _cross_timeframe_agreement(
                agent_analysis,
                confirmation_timeframe,
                confirmation_capture_result,
                confirmation_agent_result,
                confirmation_capture_matches_primary_hash,
                force_scenario_active,
            ),
        ),
    ]

    checks = tuple(
        GuardrailCheck(name=name, passed=passed, reason=reason, timestamp=now)
        for name, (passed, reason) in rule_results
    )

    blocked = any(not c.passed for c in checks if c.name in BLOCKING_RULES)
    needs_review = any(not c.passed for c in checks if c.name in REVIEW_FORCING_RULES)

    if blocked:
        outcome = GuardrailOutcome.BLOCKED
    elif needs_review:
        outcome = GuardrailOutcome.REQUIRES_REVIEW
    else:
        outcome = GuardrailOutcome.READY_FOR_REVIEW

    return GuardrailReport(outcome=outcome, checks=checks)
