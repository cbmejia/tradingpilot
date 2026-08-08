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
# Still a known, open gap, NOT addressed by this fix (out of its scope):
# agent_analyses has no columns for the five categorical fields the agent
# produces (trend_direction, trend_quality, structure_quality,
# setup_quality, context_risk) -- a gap from the Milestone 8 revision.
# A successful analysis's audit-event text remains the only place those
# five values are visible after the fact. See docs/iterations.md's
# Milestone 10.5 fix entry.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus, TradeAgent, TradeParams
from capture.base import CaptureResult, CaptureStatus
from capture.manager import CaptureManager
from database import crud
from database.models import Run
from evals.trade_evaluator import EvaluationResult, EvaluationStatus, evaluate
from guardrails.rules import evaluate_guardrails
from tools.market_data import MarketDataManager, MarketDataStatus, MarketQuote


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


def _capture_summary(result: CaptureResult) -> str:
    if result.status == CaptureStatus.SUCCESS:
        return f"Chart capture succeeded ({result.mode.value} mode)."
    return f"Chart capture failed ({result.mode.value} mode): {result.error_message}"


def _market_data_summary(result: MarketQuote) -> str:
    if result.status == MarketDataStatus.SUCCESS:
        return f"Market data fetch succeeded ({result.mode.value} mode, price={result.price})."
    return f"Market data fetch failed ({result.mode.value} mode): {result.error_message}"


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


def run_pipeline(session: Session, run_id: str) -> Run:
    """
    Runs the full capture -> market data -> agent -> evaluation ->
    guardrails pipeline for one run and persists every step, in order, as
    it happens. Returns the updated Run.

    Raises RunAlreadyAnalyzedError if this run already has any pipeline
    results. Callers (backend/api/routes_runs.py) are expected to have
    already confirmed the run exists -- this function assumes it does.
    """
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

    # --- Step 4: chart capture ---
    crud.add_audit_event(
        session, run_id=run_id, event_type="capture_started", event_message="Chart capture started."
    )
    capture_result = CaptureManager().capture(run.symbol, run.timeframe)
    crud.add_capture(
        session,
        run_id=run_id,
        capture_mode=capture_result.mode.value,
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

    # --- Step 5: market data (independent of capture -- always attempted) ---
    crud.add_audit_event(
        session, run_id=run_id, event_type="market_data_started", event_message="Market data fetch started."
    )
    market_data_result = MarketDataManager().get_quote(run.symbol)
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
        agent_result = TradeAgent().analyze(capture_result, market_data_result, trade_params)
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
            )
        else:
            crud.add_failed_agent_analysis(
                session, run_id=run_id, error_message=agent_result.error_message
            )
        crud.add_audit_event(
            session,
            run_id=run_id,
            event_type="agent_analysis_finished",
            event_message=_agent_summary(agent_result),
        )
    else:
        agent_result = _skipped_agent_result(
            "Agent analysis skipped -- capture and market data must both succeed "
            "before the agent is called."
        )
        crud.add_failed_agent_analysis(
            session, run_id=run_id, error_message=agent_result.error_message
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
        capture_result, market_data_result, agent_result, evaluation_result, trade_params
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
