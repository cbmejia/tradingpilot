# TradePilot AI — /runs endpoints: create a run, list runs, fetch one
# run's full audit trail, and record a human's review decision.
#
# In plain terms: this is where a run's lifecycle starts, and (as of
# Milestone 10) where it can end. Creating a run ONLY writes a database
# record — it does not capture a chart, fetch market data, call the AI
# agent, score anything, or check any guardrails. Those tools exist as
# standalone modules but aren't wired into an orchestrator yet, so
# nothing here pretends a run has gone through the pipeline just because
# it exists. The review endpoint below is equally narrow: it records a
# human's judgment about results that already exist -- it never
# re-scores, re-evaluates, or re-runs anything.

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.schemas import (
    HumanReviewRequest,
    HumanReviewResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListResponse,
    RunSummary,
)
from database import crud
from database.database import get_session
from guardrails.rules import GuardrailOutcome, outcome_from_results

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunCreateResponse, status_code=201)
def create_run(
    payload: RunCreateRequest, session: Session = Depends(get_session)
) -> RunCreateResponse:
    run = crud.create_run(
        session,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        direction=payload.direction,
        entry=payload.entry,
        stop=payload.stop,
        target=payload.target,
        status="CREATED",
    )
    crud.add_audit_event(
        session,
        run_id=run.id,
        event_type="run_created",
        event_message=f"Run created for {run.symbol} {run.timeframe}",
    )
    return RunCreateResponse(id=run.id, status=run.status)


@router.get("", response_model=RunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> RunListResponse:
    runs, total = crud.list_runs(session, limit=limit, offset=offset)
    return RunListResponse(
        items=[RunSummary.model_validate(run) for run in runs],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunDetail:
    run = crud.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    detail = RunDetail.model_validate(run)
    outcome = outcome_from_results(
        (result.guardrail_name, result.passed) for result in run.guardrail_results
    )
    return detail.model_copy(update={"guardrail_outcome": outcome.value if outcome else None})


@router.post("/{run_id}/review", response_model=HumanReviewResponse)
def review_run(
    run_id: str, payload: HumanReviewRequest, session: Session = Depends(get_session)
) -> HumanReviewResponse:
    run = crud.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # A decision is final. No second attempt, ever -- not even to change
    # a mind. The audit trail must never lose or silently overwrite one.
    if run.human_review is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run {run_id} already has a decision "
                f"({run.human_review.decision}, recorded at "
                f"{run.human_review.decided_at.isoformat()}). A decision is final."
            ),
        )

    # REJECTED is always permitted, on any run, in any state. APPROVED is
    # the one that's gated: a BLOCKED run (or one with no guardrail
    # results at all, which is treated the same way -- see
    # outcome_from_results) has nothing to accept.
    if payload.decision == "APPROVED":
        outcome = outcome_from_results(
            (result.guardrail_name, result.passed) for result in run.guardrail_results
        )
        if outcome is None or outcome == GuardrailOutcome.BLOCKED:
            reason = (
                "the guardrails blocked this run"
                if outcome == GuardrailOutcome.BLOCKED
                else "no guardrail results exist for this run yet"
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {run_id} cannot be approved: {reason}. Only REJECTED "
                    f"is permitted."
                ),
            )

    review = crud.add_human_review(
        session, run_id=run_id, decision=payload.decision, comment=payload.comment
    )

    updated_run = crud.update_run_status(
        session, run_id=run_id, status=payload.decision, completed_at=review.decided_at
    )

    comment_suffix = f": {payload.comment}" if payload.comment else "."
    crud.add_audit_event(
        session,
        run_id=run_id,
        event_type="human_review_recorded",
        event_message=f"Run {payload.decision.lower()} by reviewer{comment_suffix}",
    )

    return HumanReviewResponse(
        run_id=run_id,
        decision=review.decision,
        decided_at=review.decided_at,
        comment=review.comment,
        run_status=updated_run.status,
    )
