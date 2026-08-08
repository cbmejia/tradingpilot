# TradePilot AI — the only sanctioned way application code reads and
# writes the audit trail tables.
#
# In plain terms: instead of letting every part of the app build database
# rows (or queries) by hand, they all go through one of the functions
# below. That way there's exactly one place that knows how to correctly
# save or fetch a Run, a Capture, an Evaluation, and so on.
#
# The important one is add_evaluation(): it does NOT accept a total_score
# argument. It always computes the total itself from the five component
# scores. That's how "the AI must not be allowed to write the final score"
# is enforced — there simply is no parameter for it.

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from database.models import (
    AGENT_CATEGORICAL_FIELDS,
    AgentAnalysis,
    AuditEvent,
    Capture,
    Evaluation,
    GuardrailResult,
    HumanReview,
    MarketData,
    Run,
)


def _validate_categorical_fields(**fields: Optional[str]) -> None:
    """
    Application-level half of the categorical-field check (the other half
    is the CHECK constraint on AgentAnalysis in database/models.py).
    Enforced here too, not just at the database level, because a Python
    ValueError with the actual bad value and its allowed set is a much
    clearer failure than a generic SQLite IntegrityError -- and because
    this is the same defense-in-depth pattern the rest of this file
    already uses (e.g. the Evaluation CHECK constraint backstops
    add_evaluation()'s own total_score computation). agents/trade_agent.py
    already validates these before an analysis is ever accepted as
    SUCCESS, so in the normal path this never fires -- it exists for
    whatever calls this function next, including a future caller that
    isn't as careful.
    """
    for name, value in fields.items():
        if value is None:
            continue
        allowed = AGENT_CATEGORICAL_FIELDS[name]
        if value not in allowed:
            raise ValueError(f"{name}={value!r} is not one of the allowed values {allowed}")


def create_run(
    session: Session,
    *,
    symbol: str,
    timeframe: str,
    direction: Optional[str] = None,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    status: str = "pending",
) -> Run:
    run = Run(
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        status=status,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str) -> Optional[Run]:
    """Fetch one run by id, or None if it doesn't exist."""
    return session.get(Run, run_id)


def update_run_status(
    session: Session,
    *,
    run_id: str,
    status: str,
    completed_at: Optional[datetime] = None,
) -> Optional[Run]:
    """
    Updates a run's status and, optionally, its completion timestamp.
    Used by the human-review endpoint (Milestone 10) to move a run to its
    terminal state after a decision is recorded. Returns None if the run
    doesn't exist (callers are expected to have already checked).
    """
    run = session.get(Run, run_id)
    if run is None:
        return None
    run.status = status
    if completed_at is not None:
        run.completed_at = completed_at
    session.commit()
    session.refresh(run)
    return run


def list_runs(session: Session, *, limit: int = 20, offset: int = 0) -> tuple[list[Run], int]:
    """
    Fetch a page of runs, newest first, plus the total count of all runs
    (so the caller can build paging info without a second round trip).
    """
    total = session.query(Run).count()
    runs = (
        session.query(Run)
        .order_by(Run.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return runs, total


def add_capture(
    session: Session,
    *,
    run_id: str,
    capture_mode: str,
    symbol: str,
    timeframe: str,
    status: str,
    screenshot_path: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> Capture:
    capture = Capture(
        run_id=run_id,
        capture_mode=capture_mode,
        symbol=symbol,
        timeframe=timeframe,
        screenshot_path=screenshot_path,
        captured_at=captured_at,
        status=status,
        error_message=error_message,
    )
    session.add(capture)
    session.commit()
    session.refresh(capture)
    return capture


def add_market_data(
    session: Session,
    *,
    run_id: str,
    symbol: str,
    source: str,
    status: str,
    price: Optional[float] = None,
    timestamp: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> MarketData:
    data = MarketData(
        run_id=run_id,
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        source=source,
        status=status,
        error_message=error_message,
    )
    session.add(data)
    session.commit()
    session.refresh(data)
    return data


def add_agent_analysis(
    session: Session,
    *,
    run_id: str,
    analysis_text: str,
    trend_assessment: str,
    structure_assessment: str,
    setup_assessment: str,
    uncertainty: str,
    trend_direction: str,
    trend_quality: str,
    structure_quality: str,
    setup_quality: str,
    context_risk: str,
) -> AgentAnalysis:
    """
    Record a SUCCESSFUL agent analysis -- including the five categorical
    fields the evaluator actually scores from (Milestone 10.5 fix 2), so
    a run's score can always be traced back to the observation that
    produced it. All five are required (not optional/defaulted): a real
    SUCCESS analysis always has all of them, and a caller that forgot one
    should get a loud TypeError, not a silently incomplete row.

    Each categorical value is validated against its own allowed set
    before anything is written -- see _validate_categorical_fields()
    above for why this check exists here too, not just as the CHECK
    constraint on AgentAnalysis.

    For a failed analysis, see add_failed_agent_analysis() below --
    status is always "SUCCESS" here, never a parameter, so this function
    can never be used to store a failure with fabricated qualitative
    fields.
    """
    _validate_categorical_fields(
        trend_direction=trend_direction,
        trend_quality=trend_quality,
        structure_quality=structure_quality,
        setup_quality=setup_quality,
        context_risk=context_risk,
    )
    analysis = AgentAnalysis(
        run_id=run_id,
        status="SUCCESS",
        analysis_text=analysis_text,
        trend_assessment=trend_assessment,
        structure_assessment=structure_assessment,
        setup_assessment=setup_assessment,
        uncertainty=uncertainty,
        trend_direction=trend_direction,
        trend_quality=trend_quality,
        structure_quality=structure_quality,
        setup_quality=setup_quality,
        context_risk=context_risk,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def add_failed_agent_analysis(
    session: Session,
    *,
    run_id: str,
    error_message: str,
) -> AgentAnalysis:
    """
    Record a FAILED agent analysis -- e.g. Claude's response was
    unusable, or the analysis was never attempted because an upstream
    stage (capture, market data) failed first. Every qualitative field is
    null; nothing here is guessed or filled in. Milestone 10.5 fix: the
    reason this function exists is so a failure has somewhere real to
    live besides the audit_events text trail.
    """
    analysis = AgentAnalysis(
        run_id=run_id,
        status="FAILED",
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
        error_message=error_message,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def add_evaluation(
    session: Session,
    *,
    run_id: str,
    trend_score: int,
    structure_score: int,
    entry_score: int,
    risk_reward_score: int,
    timing_context_score: int,
) -> Evaluation:
    """
    Record a SUCCESSFUL rubric evaluation for a run.

    total_score is always the sum of the five component scores, computed
    right here. There is deliberately no total_score parameter — the
    caller (including the future AI evaluation engine) cannot pass one in.
    status is always "SUCCESS" here, never a parameter -- for a failed
    evaluation, see add_failed_evaluation() below, which cannot be used to
    smuggle in a score either (it has no score parameters at all).
    """
    total_score = (
        trend_score
        + structure_score
        + entry_score
        + risk_reward_score
        + timing_context_score
    )
    evaluation = Evaluation(
        run_id=run_id,
        status="SUCCESS",
        trend_score=trend_score,
        structure_score=structure_score,
        entry_score=entry_score,
        risk_reward_score=risk_reward_score,
        timing_context_score=timing_context_score,
        total_score=total_score,
    )
    session.add(evaluation)
    session.commit()
    session.refresh(evaluation)
    return evaluation


def add_failed_evaluation(
    session: Session,
    *,
    run_id: str,
    error_message: str,
) -> Evaluation:
    """
    Record a FAILED evaluation -- e.g. the risk/reward numbers were
    incoherent, or there was no successful agent analysis to score in the
    first place. Every score column, including total_score, is left null
    -- never zero, since zero is a real, meaningful score and storing it
    here would be indistinguishable from a genuine all-zero result.
    Milestone 10.5 fix: the reason this function exists is so a failure
    has somewhere real to live besides the audit_events text trail.
    """
    evaluation = Evaluation(
        run_id=run_id,
        status="FAILED",
        trend_score=None,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        error_message=error_message,
    )
    session.add(evaluation)
    session.commit()
    session.refresh(evaluation)
    return evaluation


def add_guardrail_result(
    session: Session,
    *,
    run_id: str,
    guardrail_name: str,
    passed: bool,
    reason: Optional[str] = None,
) -> GuardrailResult:
    result = GuardrailResult(
        run_id=run_id,
        guardrail_name=guardrail_name,
        passed=passed,
        reason=reason,
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def add_human_review(
    session: Session,
    *,
    run_id: str,
    decision: str,
    comment: Optional[str] = None,
) -> HumanReview:
    review = HumanReview(run_id=run_id, decision=decision, comment=comment)
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def add_audit_event(
    session: Session,
    *,
    run_id: str,
    event_type: str,
    event_message: str,
) -> AuditEvent:
    event = AuditEvent(run_id=run_id, event_type=event_type, event_message=event_message)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
