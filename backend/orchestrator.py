# TradePilot AI — workflow orchestrator (Milestone 10.5).
#
# In plain terms: this file is the only thing that actually runs the
# 12-step workflow from docs/architecture.md, steps 4-10, for one run.
# Everything it calls already exists and is already tested
# (capture/, tools/market_data.py, agents/trade_agent.py,
# evals/trade_evaluator.py, guardrails/rules.py) — this file adds no new
# capture logic, no new scoring, no new guardrail rules. It only calls
# those five modules in the documented order and saves what they return,
# via database/crud.py, the same sanctioned way every other write in this
# app happens.
#
# FAIL FAST, HONESTLY:
# - Chart capture and market data are independent tool calls -- neither
#   depends on the other succeeding (docs/architecture.md steps 4 and 5
#   are separate inputs to step 6) -- so both are always attempted, even
#   if one already failed.
# - The agent is only called if BOTH capture and market data succeeded.
#   Calling it on a failed capture or a failed quote would mean asking it
#   to reason about data that was never actually retrieved -- the same
#   "no fabricated data" principle agents/trade_agent.py already enforces
#   internally, enforced a second time here so a bad upstream result never
#   even reaches the agent, not even to have it short-circuit itself.
# - The evaluator is only called if the agent succeeded. There is nothing
#   to score otherwise.
# - Guardrails ALWAYS run, no matter what failed upstream, using whatever
#   result objects exist (even FAILED ones) -- a blocked run must still
#   get its complete eleven-rule breakdown explaining exactly why.
#
# A run can only be analyzed once. A second attempt is refused with
# RunAlreadyAnalyzedError, the same way backend/api/routes_runs.py refuses
# a second human decision on the same run -- pipeline results, once
# recorded, are final.
#
# Milestone 10.5 fix: agent_analyses and evaluations now carry
# status/error_message, matching the shape captures and market_data
# already had -- so a FAILED agent analysis or a FAILED evaluation is
# stored as a real row (crud.add_failed_agent_analysis /
# add_failed_evaluation), not just described in audit_events. Exactly one
# row is written to each table for every analyzed run, whether the stage
# succeeded, failed, or was never attempted because an upstream stage
# failed first -- so GET /runs/{id} can always show success or failure by
# reading the record itself. The audit trail still gets an event either
# way, for the same reason it always has: a structured row says "what,"
# the audit trail says "when, in what order, alongside what else."
#
# Milestone 8's gap (agent_analyses' missing categorical columns) was
# closed by Milestone 10.5 fix 2; see docs/iterations.md for the full
# history.
#
# Milestone 12 — force_scenario, a testing-only affordance:
# POST /runs/{run_id}/analyze accepts an optional force_scenario query
# parameter (backend/api/routes_runs.py), gated behind
# TESTING_CONTROLS_ENABLED (off by default -- see backend/config.py).
# When set, run_pipeline() deliberately substitutes a synthetic result
# for exactly one stage -- a real, honest FAILED result shaped identically
# to what that stage would produce on a genuine failure, an artificially
# aged timestamp on an otherwise-real successful result, or a synthetic
# SUCCESS analysis whose prose says plainly it's synthetic -- so every
# guardrail can be proven against a real, reproducible, screenshottable
# run instead of only asserted in a unit test. See docs/failure_modes.md
# for the full scenario list and docs/iterations.md's Milestone 12 entry
# for the design reasoning.
#
# THE HARD RULE THIS MECHANISM FOLLOWS: it only ever fabricates a
# STAGE'S INPUT to the next stage (a capture result, a quote, an agent
# analysis) -- never a score, never a guardrail verdict, never the
# outcome itself. Evaluation and guardrails always run for real, on
# whatever result (real or forced) the earlier stages produced. A forced
# "perfect" run still has its 100 computed by the real evaluator from
# synthetic-but-realistic categorical fields, not a hardcoded 100 --
# proving the SYNTHETIC_DATA guardrail actually catches it, rather than
# asserting a fabricated outcome. Every forced run is marked unmistakably
# in its own audit trail (a testing_scenario_forced event, first thing
# written) and every synthetic value's text says "TESTING" plainly, so
# it can never be mistaken for a real result after the fact.

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from agents.trade_agent import (
    AgentAnalysisResult,
    AgentAnalysisStatus,
    ConfirmationAnalysisResult,
    ConfirmationAnalysisStatus,
    TradeAgent,
    TradeParams,
)
from capture.base import CaptureResult, CaptureStatus
from capture.manager import CaptureManager
from database import crud
from database.models import Run
from evals.trade_evaluator import EvaluationResult, EvaluationStatus, compute_risk_reward, evaluate
from guardrails.rules import evaluate_guardrails
from tools.market_data import MarketDataManager, MarketDataStatus, MarketQuote

# The only values force_scenario ever accepts. Validated again in
# backend/api/routes_runs.py (a clean 422 before this function is even
# called) and here (defense in depth, same pattern as every other
# validated value in this codebase).
FORCE_SCENARIOS: frozenset[str] = frozenset(
    {
        "capture_fails",
        "capture_stale",
        "market_data_fails",
        "market_data_stale",
        "agent_fails",
        "high_uncertainty",
        "perfect_demo_score",
    }
)

# 7A Iteration 1: which committed DEMO fixture (capture) / paired quote
# (market data) to serve. Independent of FORCE_SCENARIOS -- this picks
# between two real, honest sample data sets, it never fabricates a
# failure or an outcome the way force_scenario does, so it is NOT gated
# behind TESTING_CONTROLS_ENABLED. None (the default, and the only value
# every caller before this addendum ever used) reproduces the exact
# original single-fixture behavior. Only meaningful in DEMO mode --
# CaptureManager/MarketDataManager both simply ignore it when running
# LIVE. See capture/demo_provider.py and tools/market_data.py's own
# CHART_VARIANT_* constants for the two allowed values.
DEMO_CHART_VARIANTS: frozenset[str] = frozenset({"unreadable_chart", "readable_chart"})

# 7A Iteration 2 -- multi-timeframe capture + cross-timeframe agreement.
# A run's primary timeframe (run.timeframe, unchanged from before this
# iteration) is paired with exactly one CONFIRMATION timeframe: the next
# rung up this fixed ladder. Chosen over a user-configurable set for the
# same reason a fixed set of allowed timeframes already exists in
# backend/schemas.py -- one deterministic, always-the-same-answer rule,
# no new UI configuration needed. If the primary is already at the top of
# the ladder (or isn't a recognized rung at all -- shouldn't happen, since
# backend/schemas.py's ALLOWED_TIMEFRAMES already restricts what a client
# can submit, but this function doesn't trust that from a distance), there
# is no confirmation timeframe -- N/A, not a failure; see
# guardrails/rules.py's _cross_timeframe_agreement() for how N/A is scored.
TIMEFRAME_LADDER: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")


def _confirmation_timeframe(primary_timeframe: str) -> Optional[str]:
    """The next rung up TIMEFRAME_LADDER, or None if primary_timeframe is
    already at the top (or isn't a recognized rung at all)."""
    try:
        index = TIMEFRAME_LADDER.index(primary_timeframe.strip().lower())
    except ValueError:
        return None
    if index + 1 >= len(TIMEFRAME_LADDER):
        return None
    return TIMEFRAME_LADDER[index + 1]


def _hash_file(path: Optional[str]) -> Optional[str]:
    """
    SHA-256 of a screenshot file's actual bytes -- used to detect a real
    failure mode that would otherwise be invisible: if the TradingView
    timeframe switch silently doesn't take, the confirmation capture is
    byte-identical to the primary one, the two "independent" reads would
    trivially agree, and CROSS_TIMEFRAME_AGREEMENT would pass on zero
    actual information. Computed here, in the orchestrator (which already
    has both screenshot paths in hand right after capturing them), not in
    guardrails/rules.py -- that module stays a pure function over
    explicit inputs, the same "no ambient state" principle CAPTURE_FRESH/
    MARKET_DATA_FRESH already apply to `now`. Returns None (never raises)
    if the file can't be read -- the caller treats that as "can't compare,"
    not as a hash collision.
    """
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


# How far in the past a "stale" forced timestamp is set -- comfortably
# past any sane CAPTURE_MAX_AGE_SECONDS/MARKET_DATA_MAX_AGE_SECONDS
# (defaults 300s/900s), so the freshness guardrail fails regardless of
# local threshold tuning. Matches the "2-hour-old" example already used
# in README.md's hand-run guardrails walkthrough.
_STALE_AGE = timedelta(hours=2)

# The categorical profile a synthetic SUCCESS agent result uses for each
# forced scenario that needs the agent to have "succeeded" upstream of
# it. Never used to fabricate a score directly -- evals/trade_evaluator.py
# still computes the real score from these fields, same as it would from
# a real agent response.
_SYNTHETIC_AGENT_PROFILES: dict[str, dict[str, str]] = {
    "capture_stale": {
        "uncertainty": "MEDIUM",
        "trend_direction": "UP",
        "trend_quality": "STRONG",
        "structure_quality": "CLEAN",
        "setup_quality": "ACCEPTABLE",
        "context_risk": "LOW",
    },
    "market_data_stale": {
        "uncertainty": "MEDIUM",
        "trend_direction": "UP",
        "trend_quality": "STRONG",
        "structure_quality": "CLEAN",
        "setup_quality": "ACCEPTABLE",
        "context_risk": "LOW",
    },
    "high_uncertainty": {
        "uncertainty": "HIGH",
        "trend_direction": "UP",
        "trend_quality": "STRONG",
        "structure_quality": "CLEAN",
        "setup_quality": "ACCEPTABLE",
        "context_risk": "LOW",
    },
    "perfect_demo_score": {
        "uncertainty": "LOW",
        "trend_direction": "UP",
        "trend_quality": "STRONG",
        "structure_quality": "CLEAN",
        "setup_quality": "TEXTBOOK",
        "context_risk": "LOW",
    },
}


class RunAlreadyAnalyzedError(Exception):
    """
    Raised when the pipeline is run for a run that already has pipeline
    results. Mirrors the "a decision is final" rule the human-review
    endpoint already applies to a second approve/reject attempt --
    analysis results, once recorded, are final too, and are never
    silently re-run or overwritten.
    """


def _has_existing_pipeline_results(run: Run) -> bool:
    return bool(
        run.captures
        or run.market_data
        or run.analyses
        or run.evaluations
        or run.guardrail_results
    )


def _skipped_agent_result(reason: str) -> AgentAnalysisResult:
    """A stand-in FAILED result for a stage that was never actually
    attempted -- shaped identically to what TradeAgent itself would return
    on a validation failure, so guardrails/rules.py sees exactly the same
    thing either way. Never fabricates a category or a status; every
    qualitative field is None, same as any other failure."""
    return AgentAnalysisResult(
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
        # No real call was ever attempted -- this stage was skipped
        # entirely, never even reached the point of knowing which model
        # it would have used.
        model=None,
        timestamp=None,
        error_message=reason,
    )


def _skipped_evaluation_result(reason: str) -> EvaluationResult:
    """Same idea as _skipped_agent_result, for a stage that was never
    attempted -- shaped identically to what evals/trade_evaluator.py's
    own _failed() would return."""
    return EvaluationResult(
        status=EvaluationStatus.FAILED,
        trend_score=None,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        risk_reward_ratio=None,
        error_message=reason,
    )


def _forced_failed_capture(mode, symbol: str, timeframe: str, force_scenario: str) -> CaptureResult:
    """A synthetic FAILED capture, shaped exactly like a real one --
    labeled with the real configured mode (so the UI's DEMO/LIVE badge
    stays accurate) and an error message that says plainly this was a
    deliberate test, not a genuine capture failure."""
    return CaptureResult(
        mode=mode,
        symbol=symbol,
        timeframe=timeframe,
        screenshot_path=None,
        captured_at=None,
        status=CaptureStatus.FAILED,
        error_message=(
            f"TESTING: capture deliberately forced to fail (force_scenario={force_scenario!r}) "
            f"for guardrail verification. This is not a real capture failure."
        ),
    )


def _forced_failed_market_data(mode, symbol: str, force_scenario: str) -> MarketQuote:
    """Same idea as _forced_failed_capture, for market data."""
    return MarketQuote(
        mode=mode,
        symbol=symbol,
        price=None,
        timestamp=None,
        source="testing_forced_failure",
        status=MarketDataStatus.FAILED,
        error_message=(
            f"TESTING: market data fetch deliberately forced to fail "
            f"(force_scenario={force_scenario!r}) for guardrail verification. "
            f"This is not a real fetch failure."
        ),
    )


def _forced_agent_result(force_scenario: str) -> AgentAnalysisResult:
    """
    Builds the agent's result for a forced test scenario -- never a real
    Claude call, so this is free and fully deterministic. Two shapes
    only: a FAILED result (force_scenario == "agent_fails") shaped
    exactly like a real failure, or a SUCCESS result built from
    _SYNTHETIC_AGENT_PROFILES whose every prose field says plainly it's
    synthetic. Either way, the *score* that comes out of this is still
    computed for real by evals/trade_evaluator.py from these categorical
    fields -- this function only ever fabricates the agent's input to the
    scorer, never the score itself.
    """
    if force_scenario == "agent_fails":
        return AgentAnalysisResult(
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
            # No Claude request was made -- see the message below.
            model=None,
            timestamp=None,
            error_message=(
                f"TESTING: agent deliberately forced to fail (force_scenario={force_scenario!r}) "
                f"for guardrail verification. No Claude request was made."
            ),
        )

    profile = _SYNTHETIC_AGENT_PROFILES[force_scenario]
    note = (
        f"TESTING: synthetic analysis (force_scenario={force_scenario!r}) for guardrail "
        f"verification -- not a real reading of the chart."
    )
    return AgentAnalysisResult(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text=note,
        trend_assessment=note,
        structure_assessment=note,
        setup_assessment=note,
        uncertainty=profile["uncertainty"],
        trend_direction=profile["trend_direction"],
        trend_quality=profile["trend_quality"],
        structure_quality=profile["structure_quality"],
        setup_quality=profile["setup_quality"],
        context_risk=profile["context_risk"],
        # A forced scenario never simulates a proposal -- always a clean
        # decline, same as a real Claude call this mechanism never makes.
        proposal_has_proposal=False,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
        # A synthetic profile, never a real Claude call -- see the note
        # above.
        model=None,
        timestamp=datetime.now(timezone.utc),
        error_message=None,
    )


def _capture_summary(result: CaptureResult) -> str:
    if result.status == CaptureStatus.SUCCESS:
        return f"Chart capture succeeded ({result.mode.value} mode)."
    return f"Chart capture failed ({result.mode.value} mode): {result.error_message}"


def _market_data_summary(result: MarketQuote) -> str:
    if result.status == MarketDataStatus.SUCCESS:
        return f"Market data fetch succeeded ({result.mode.value} mode, price={result.price})."
    return f"Market data fetch failed ({result.mode.value} mode): {result.error_message}"


def _confirmation_capture_summary(result: CaptureResult) -> str:
    if result.status == CaptureStatus.SUCCESS:
        return f"Confirmation chart capture succeeded ({result.mode.value} mode, {result.timeframe})."
    return f"Confirmation chart capture failed ({result.mode.value} mode): {result.error_message}"


def _confirmation_analysis_summary(result: ConfirmationAnalysisResult) -> str:
    if result.status == ConfirmationAnalysisStatus.SUCCESS:
        return (
            f"Confirmation analysis succeeded. visible_timeframe={result.visible_timeframe!r}, "
            f"trend_direction={result.trend_direction}, trend_quality={result.trend_quality}."
        )
    return f"Confirmation analysis failed: {result.error_message}"


def _persist_agent_proposal(session: Session, run_id: str, agent_result: AgentAnalysisResult) -> str:
    """
    7A Iteration 1. Called only for a SUCCESSFUL agent analysis -- the
    only case where there's a real yes/no answer about whether the agent
    proposed levels. Persists either a decline or a proposal, and returns
    a short summary folded into the agent_analysis_finished audit event
    (no new audit event type or stage is introduced -- this piggybacks on
    the existing agent stage's own event).

    Coherence is computed exactly once, right here, by calling
    evals.trade_evaluator.compute_risk_reward() on the PROPOSED levels --
    the same function guardrails/rules.py's TRADE_PARAMS_VALID rule
    already reuses for the run's own trade params, not a second
    implementation. This has no bearing on the current run's own
    evaluation or guardrails: evals/trade_evaluator.py's evaluate() and
    guardrails/rules.py's evaluate_guardrails() are never called with
    anything proposal-related, and neither is touched by this function.
    """
    if not agent_result.proposal_has_proposal:
        crud.add_declined_proposal(session, run_id=run_id)
        return "No trade level proposal (agent declined)."

    ratio, error = compute_risk_reward(
        agent_result.proposal_direction,
        agent_result.proposal_entry,
        agent_result.proposal_stop,
        agent_result.proposal_target,
    )
    levels = (
        f"{agent_result.proposal_direction} entry={agent_result.proposal_entry}, "
        f"stop={agent_result.proposal_stop}, target={agent_result.proposal_target}"
    )
    if error is None:
        crud.add_agent_proposal(
            session,
            run_id=run_id,
            direction=agent_result.proposal_direction,
            entry=agent_result.proposal_entry,
            stop=agent_result.proposal_stop,
            target=agent_result.proposal_target,
            is_coherent=True,
            risk_reward_ratio=ratio,
        )
        return f"Agent proposed {levels} (coherent, risk/reward ratio={ratio:.2f})."

    crud.add_agent_proposal(
        session,
        run_id=run_id,
        direction=agent_result.proposal_direction,
        entry=agent_result.proposal_entry,
        stop=agent_result.proposal_stop,
        target=agent_result.proposal_target,
        is_coherent=False,
        coherence_error=error,
    )
    return f"Agent proposed {levels} (incoherent: {error})."


def _agent_summary(result: AgentAnalysisResult) -> str:
    if result.status == AgentAnalysisStatus.SUCCESS:
        return (
            f"Agent analysis succeeded. uncertainty={result.uncertainty}, "
            f"trend_direction={result.trend_direction}, trend_quality={result.trend_quality}, "
            f"structure_quality={result.structure_quality}, setup_quality={result.setup_quality}, "
            f"context_risk={result.context_risk}."
        )
    return f"Agent analysis failed: {result.error_message}"


def _evaluation_summary(result: EvaluationResult) -> str:
    if result.status == EvaluationStatus.SUCCESS:
        return (
            f"Evaluation succeeded. total_score={result.total_score} "
            f"(trend={result.trend_score}, structure={result.structure_score}, "
            f"entry={result.entry_score}, risk_reward={result.risk_reward_score} "
            f"[ratio={result.risk_reward_ratio}], timing_context={result.timing_context_score})."
        )
    return f"Evaluation failed: {result.error_message}"


def run_pipeline(
    session: Session,
    run_id: str,
    *,
    force_scenario: Optional[str] = None,
    chart_variant: Optional[str] = None,
) -> Run:
    """
    Runs the full capture -> market data -> agent -> evaluation ->
    guardrails pipeline for one run and persists every step, in order, as
    it happens. Returns the updated Run.

    force_scenario: Milestone 12 testing affordance, see the module
    docstring above. None (the default, and the only value any real run
    ever uses) means every stage runs for real, exactly as before this
    parameter existed. A non-None value must be one of FORCE_SCENARIOS --
    callers (backend/api/routes_runs.py) are expected to have already
    validated this and checked TESTING_CONTROLS_ENABLED; this function
    re-validates anyway, the same defense-in-depth pattern used
    everywhere else in this codebase.

    chart_variant (7A Iteration 1): which committed DEMO fixture/paired
    quote to use, see DEMO_CHART_VARIANTS above. None (the default)
    reproduces the original single-fixture behavior exactly. Re-validated
    here too, same defense-in-depth pattern as force_scenario.

    Raises RunAlreadyAnalyzedError if this run already has any pipeline
    results. Callers are expected to have already confirmed the run
    exists -- this function assumes it does.
    """
    if force_scenario is not None and force_scenario not in FORCE_SCENARIOS:
        allowed = ", ".join(sorted(FORCE_SCENARIOS))
        raise ValueError(f"force_scenario must be one of: {allowed} (got {force_scenario!r})")
    if chart_variant is not None and chart_variant not in DEMO_CHART_VARIANTS:
        allowed = ", ".join(sorted(DEMO_CHART_VARIANTS))
        raise ValueError(f"chart_variant must be one of: {allowed} (got {chart_variant!r})")

    run = crud.get_run(session, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")

    if _has_existing_pipeline_results(run):
        raise RunAlreadyAnalyzedError(
            f"Run {run_id} has already been analyzed. Pipeline results are never "
            f"re-run or overwritten -- this is the same rule the human-review "
            f"endpoint applies to a second decision."
        )

    trade_params = TradeParams(
        direction=run.direction, entry=run.entry, stop=run.stop, target=run.target
    )

    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="analysis_started",
        event_message=f"Pipeline analysis started for {run.symbol} {run.timeframe}.",
    )
    crud.update_run_status(session, run_id=run_id, status="ANALYZING")

    if force_scenario is not None:
        # Written first, before any stage runs, so it's the very first
        # thing anyone reading this run's audit trail sees -- this run's
        # results are not a real analysis.
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="testing_scenario_forced",
            event_message=(
                f"TESTING: this run's pipeline was deliberately altered to force "
                f"scenario {force_scenario!r} for guardrail verification. This is "
                f"not a real analysis."
            ),
        )

    # --- Step 4: chart capture ---
    crud.add_audit_event(
        session, run_id=run_id, event_type="capture_started", event_message="Chart capture started."
    )
    capture_manager = CaptureManager()
    if force_scenario == "capture_fails":
        capture_result = _forced_failed_capture(
            capture_manager.mode, run.symbol, run.timeframe, force_scenario
        )
    else:
        capture_result = capture_manager.capture(
            run.symbol, run.timeframe, chart_variant=chart_variant
        )
        if force_scenario == "capture_stale" and capture_result.status == CaptureStatus.SUCCESS:
            capture_result = dataclasses.replace(
                capture_result, captured_at=capture_result.captured_at - _STALE_AGE
            )
    crud.add_capture(
        session,
        run_id=run_id,
        capture_mode=capture_result.mode.value,
        timeframe_role="PRIMARY",
        symbol=capture_result.symbol,
        timeframe=capture_result.timeframe,
        status=capture_result.status.value,
        screenshot_path=capture_result.screenshot_path,
        captured_at=capture_result.captured_at,
        error_message=capture_result.error_message,
    )
    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="capture_finished",
        event_message=_capture_summary(capture_result),
    )

    # --- Step 4b (7A Iteration 2): confirmation chart capture ---
    # Suppressed entirely whenever force_scenario is active -- Milestone
    # 12's testing affordance exists specifically so guardrail behavior
    # can be proven for free and deterministically, and the confirmation
    # stage makes a genuinely real (uncontrolled, billed) Claude call via
    # analyze_confirmation() below with no force_scenario equivalent of
    # its own. Extending force_scenario to also cover the confirmation
    # path was out of this iteration's scope, so the simplest, safest
    # rule is: force_scenario and multi-timeframe confirmation never both
    # run in the same pipeline execution. Treated identically to N/A (top
    # of the ladder) everywhere downstream -- confirmation_timeframe is
    # simply None either way -- with only the audit message text
    # distinguishing which reason applies.
    #
    # Otherwise independent of the primary capture's own outcome: a
    # failed primary capture already guarantees BLOCKED via
    # CAPTURE_SUCCEEDED, so a confirmation attempt in that case can't
    # change the outcome, but it costs nothing to still attempt it for a
    # complete audit trail (capture doesn't touch Alpha Vantage's quota --
    # only market data does).
    confirmation_timeframe = None if force_scenario is not None else _confirmation_timeframe(run.timeframe)
    if confirmation_timeframe is not None:
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="confirmation_capture_started",
            event_message=f"Confirmation chart capture started ({confirmation_timeframe}).",
        )
        confirmation_capture_result = capture_manager.capture(
            run.symbol, confirmation_timeframe, chart_variant=chart_variant
        )
        crud.add_capture(
            session,
            run_id=run_id,
            capture_mode=confirmation_capture_result.mode.value,
            timeframe_role="CONFIRMATION",
            symbol=confirmation_capture_result.symbol,
            timeframe=confirmation_capture_result.timeframe,
            status=confirmation_capture_result.status.value,
            screenshot_path=confirmation_capture_result.screenshot_path,
            captured_at=confirmation_capture_result.captured_at,
            error_message=confirmation_capture_result.error_message,
        )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="confirmation_capture_finished",
            event_message=_confirmation_capture_summary(confirmation_capture_result),
        )
    else:
        confirmation_capture_result = None
        if force_scenario is not None:
            skip_reason = (
                f"Confirmation capture skipped: force_scenario={force_scenario!r} is active for "
                f"this run -- 7A Iteration 2's multi-timeframe path is not exercised by Milestone "
                f"12's testing affordance. This is not a failure."
            )
        else:
            skip_reason = (
                f"Confirmation capture skipped: {run.timeframe} is already at the top of the "
                f"timeframe ladder ({', '.join(TIMEFRAME_LADDER)}) -- no confirmation timeframe "
                f"exists. N/A, not a failure."
            )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="confirmation_capture_skipped",
            event_message=skip_reason,
        )

    # The hash comparison itself: computed here (this is the one place
    # that already has both real screenshot paths in hand), fed into
    # guardrails/rules.py as a plain boolean below -- see _hash_file()'s
    # own docstring for why this check exists at all.
    confirmation_capture_matches_primary_hash = False
    if (
        confirmation_capture_result is not None
        and confirmation_capture_result.status == CaptureStatus.SUCCESS
        and capture_result.status == CaptureStatus.SUCCESS
    ):
        primary_hash = _hash_file(capture_result.screenshot_path)
        confirmation_hash = _hash_file(confirmation_capture_result.screenshot_path)
        if primary_hash is not None and primary_hash == confirmation_hash:
            confirmation_capture_matches_primary_hash = True
            crud.add_audit_event(
                session,
                run_id=run_id,
                event_type="confirmation_capture_identical_to_primary",
                event_message=(
                    "The confirmation capture is byte-identical to the primary capture "
                    "(SHA-256 hash match) -- the timeframe switch may not have taken "
                    "effect. Cross-timeframe agreement cannot be confirmed from this pair."
                ),
            )

    # --- Step 5: market data (independent of capture -- always attempted) ---
    crud.add_audit_event(
        session, run_id=run_id, event_type="market_data_started", event_message="Market data fetch started."
    )
    market_data_manager = MarketDataManager()
    if force_scenario == "market_data_fails":
        market_data_result = _forced_failed_market_data(
            market_data_manager.mode, run.symbol, force_scenario
        )
    else:
        market_data_result = market_data_manager.get_quote(run.symbol, chart_variant=chart_variant)
        if force_scenario == "market_data_stale" and market_data_result.status == MarketDataStatus.SUCCESS:
            market_data_result = dataclasses.replace(
                market_data_result, timestamp=market_data_result.timestamp - _STALE_AGE
            )
    crud.add_market_data(
        session,
        run_id=run_id,
        mode=market_data_result.mode.value,
        symbol=market_data_result.symbol,
        source=market_data_result.source,
        status=market_data_result.status.value,
        price=market_data_result.price,
        timestamp=market_data_result.timestamp,
        error_message=market_data_result.error_message,
    )
    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="market_data_finished",
        event_message=_market_data_summary(market_data_result),
    )

    # One TradeAgent instance, reused for both the primary analyze() call
    # below and the confirmation analyze_confirmation() call further down
    # (7A Iteration 2) -- same underlying credentials/model, genuinely
    # separate calls. Constructing it makes no API call and is always
    # safe/free, so it happens unconditionally here rather than being
    # duplicated inside each stage's own gate.
    agent = TradeAgent()

    # --- Steps 6-7: agent analysis -- only if BOTH inputs are usable ---
    # Either way, exactly one AgentAnalysis row is written -- SUCCESS,
    # FAILED (Claude was called and rejected/errored), or FAILED (never
    # called at all because an upstream stage failed first). Milestone
    # 10.5 fix: this is what lets GET /runs/{id} show success or failure
    # on the record itself, not only in audit_events.
    if capture_result.status == CaptureStatus.SUCCESS and market_data_result.status == MarketDataStatus.SUCCESS:
        crud.add_audit_event(
            session, run_id=run_id, event_type="agent_analysis_started", event_message="Agent analysis started."
        )
        # Reaching this branch means both upstream stages reported
        # SUCCESS, so any force_scenario still active here is one of
        # capture_stale/market_data_stale/agent_fails/high_uncertainty/
        # perfect_demo_score (capture_fails/market_data_fails never reach
        # this branch at all -- they always produce a FAILED upstream
        # result). Never a real Claude call while any of those is active:
        # free, deterministic, and the whole point is a reproducible run.
        if force_scenario is not None:
            agent_result = _forced_agent_result(force_scenario)
        else:
            agent_result = agent.analyze(capture_result, market_data_result, trade_params)
        if agent_result.status == AgentAnalysisStatus.SUCCESS:
            crud.add_agent_analysis(
                session,
                run_id=run_id,
                analysis_text=agent_result.analysis_text,
                trend_assessment=agent_result.trend_assessment,
                structure_assessment=agent_result.structure_assessment,
                setup_assessment=agent_result.setup_assessment,
                uncertainty=agent_result.uncertainty,
                trend_direction=agent_result.trend_direction,
                trend_quality=agent_result.trend_quality,
                structure_quality=agent_result.structure_quality,
                setup_quality=agent_result.setup_quality,
                context_risk=agent_result.context_risk,
                model=agent_result.model,
            )
            proposal_summary = _persist_agent_proposal(session, run_id, agent_result)
        else:
            crud.add_failed_agent_analysis(
                session,
                run_id=run_id,
                error_message=agent_result.error_message,
                model=agent_result.model,
            )
            proposal_summary = None
        finished_message = _agent_summary(agent_result)
        if proposal_summary is not None:
            finished_message = f"{finished_message} {proposal_summary}"
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="agent_analysis_finished",
            event_message=finished_message,
        )
    else:
        agent_result = _skipped_agent_result(
            "Agent analysis skipped -- capture and market data must both succeed "
            "before the agent is called."
        )
        crud.add_failed_agent_analysis(
            session,
            run_id=run_id,
            error_message=agent_result.error_message,
            model=agent_result.model,
        )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="agent_analysis_skipped",
            event_message=(
                "Agent analysis skipped: capture and market data must both succeed "
                "first. No Claude request was made."
            ),
        )

    # --- Step 7b (7A Iteration 2): confirmation analysis ---
    # A SEPARATE Claude call from the primary agent_result above -- see
    # agents/trade_agent.py's TradeAgent.analyze_confirmation() and its
    # module docstring for why this is never folded into the primary call
    # as a second image. Gated on the CONFIRMATION capture's own success,
    # independent of the primary capture/market-data/agent outcome --
    # capture and analysis stages stay independent of each other the same
    # way the primary capture and market-data stages already are. If this
    # call fails, it fails closed (see guardrails/rules.py's
    # _cross_timeframe_agreement()) -- it never retries into the primary
    # call, and the primary call is never used as a fallback for it.
    if confirmation_timeframe is not None:
        if confirmation_capture_result is not None and confirmation_capture_result.status == CaptureStatus.SUCCESS:
            crud.add_audit_event(
                session,
                run_id=run_id,
                event_type="confirmation_analysis_started",
                event_message="Confirmation analysis started.",
            )
            confirmation_agent_result = agent.analyze_confirmation(confirmation_capture_result)
            if confirmation_agent_result.status == ConfirmationAnalysisStatus.SUCCESS:
                crud.add_confirmation_analysis(
                    session,
                    run_id=run_id,
                    visible_timeframe=confirmation_agent_result.visible_timeframe,
                    trend_direction=confirmation_agent_result.trend_direction,
                    trend_quality=confirmation_agent_result.trend_quality,
                    model=confirmation_agent_result.model,
                )
            else:
                crud.add_failed_confirmation_analysis(
                    session,
                    run_id=run_id,
                    error_message=confirmation_agent_result.error_message,
                    model=confirmation_agent_result.model,
                )
            crud.add_audit_event(
                session,
                run_id=run_id,
                event_type="confirmation_analysis_finished",
                event_message=_confirmation_analysis_summary(confirmation_agent_result),
            )
        else:
            confirmation_agent_result = ConfirmationAnalysisResult(
                status=ConfirmationAnalysisStatus.FAILED,
                visible_timeframe=None,
                trend_direction=None,
                trend_quality=None,
                # Never even reached the point of calling analyze_confirmation().
                model=None,
                timestamp=None,
                error_message=(
                    "Confirmation analysis skipped -- confirmation capture did not succeed."
                ),
            )
            crud.add_failed_confirmation_analysis(
                session,
                run_id=run_id,
                error_message=confirmation_agent_result.error_message,
                model=confirmation_agent_result.model,
            )
            crud.add_audit_event(
                session,
                run_id=run_id,
                event_type="confirmation_analysis_skipped",
                event_message=(
                    "Confirmation analysis skipped: confirmation capture did not succeed. "
                    "No Claude request was made."
                ),
            )
    else:
        confirmation_agent_result = None  # N/A -- no row written, see ConfirmationAnalysis's own docstring

    # --- Step 8: evaluation -- only if the agent succeeded ---
    # Same shape as above: exactly one Evaluation row is always written.
    if agent_result.status == AgentAnalysisStatus.SUCCESS:
        crud.add_audit_event(
            session, run_id=run_id, event_type="evaluation_started", event_message="Evaluation started."
        )
        evaluation_result = evaluate(agent_result, trade_params)
        if evaluation_result.status == EvaluationStatus.SUCCESS:
            crud.add_evaluation(
                session,
                run_id=run_id,
                trend_score=evaluation_result.trend_score,
                structure_score=evaluation_result.structure_score,
                entry_score=evaluation_result.entry_score,
                risk_reward_score=evaluation_result.risk_reward_score,
                timing_context_score=evaluation_result.timing_context_score,
                risk_reward_ratio=evaluation_result.risk_reward_ratio,
            )
        else:
            crud.add_failed_evaluation(
                session, run_id=run_id, error_message=evaluation_result.error_message
            )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="evaluation_finished",
            event_message=_evaluation_summary(evaluation_result),
        )
    else:
        evaluation_result = _skipped_evaluation_result(
            "Evaluation skipped -- there is no successful agent analysis to score."
        )
        crud.add_failed_evaluation(
            session, run_id=run_id, error_message=evaluation_result.error_message
        )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="evaluation_skipped",
            event_message="Evaluation skipped: there is no successful agent analysis to score.",
        )

    # --- Step 9: guardrails -- ALWAYS run, no matter what failed above ---
    crud.add_audit_event(
        session, run_id=run_id, event_type="guardrails_started", event_message="Guardrail checks started."
    )
    report = evaluate_guardrails(
        capture_result,
        market_data_result,
        agent_result,
        evaluation_result,
        trade_params,
        confirmation_timeframe=confirmation_timeframe,
        confirmation_capture_result=confirmation_capture_result,
        confirmation_agent_result=confirmation_agent_result,
        confirmation_capture_matches_primary_hash=confirmation_capture_matches_primary_hash,
        force_scenario_active=force_scenario is not None,
    )
    for check in report.checks:
        crud.add_guardrail_result(
            session,
            run_id=run_id,
            guardrail_name=check.name,
            passed=check.passed,
            reason=check.reason,
        )
    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="guardrails_finished",
        event_message=f"Guardrail outcome: {report.outcome.value}.",
    )

    # --- Step 10: the pipeline's own recommendation is the guardrail
    # outcome itself -- BLOCKED / REQUIRES_REVIEW / READY_FOR_REVIEW.
    # Never APPROVED, never REJECTED -- only a human, via
    # POST /runs/{run_id}/review, can write either of those (Milestone 10).
    completed_at = datetime.now(timezone.utc)
    updated_run = crud.update_run_status(
        session, run_id=run_id, status=report.outcome.value, completed_at=completed_at
    )
    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="analysis_finished",
        event_message=f"Pipeline analysis finished. Outcome: {report.outcome.value}.",
    )

    return updated_run
