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
    AgentAnalysis,
    AuditEvent,
    Capture,
    Evaluation,
    GuardrailResult,
    HumanReview,
    MarketData,
    Run,
)


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
) -> AgentAnalysis:
    analysis = AgentAnalysis(
        run_id=run_id,
        analysis_text=analysis_text,
        trend_assessment=trend_assessment,
        structure_assessment=structure_assessment,
        setup_assessment=setup_assessment,
        uncertainty=uncertainty,
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
    Record a rubric evaluation for a run.

    total_score is always the sum of the five component scores, computed
    right here. There is deliberately no total_score parameter — the
    caller (including the future AI evaluation engine) cannot pass one in.
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
