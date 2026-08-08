# TradePilot AI — /runs endpoints: create a run, list runs, fetch one
# run's full audit trail.
#
# In plain terms: this is where a run's lifecycle starts. Creating a run
# ONLY writes a database record — it does not capture a chart, fetch
# market data, call the AI agent, score anything, or check any
# guardrails. Those tools don't exist yet (later milestones), and nothing
# here pretends they do.

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.schemas import (
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListResponse,
    RunSummary,
)
from database import crud
from database.database import get_session

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
    return RunDetail.model_validate(run)
