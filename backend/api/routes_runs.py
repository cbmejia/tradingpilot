# TradePilot AI — /runs endpoints: create a run, list runs, fetch one
# run's full audit trail, run the analysis pipeline, serve a run's chart
# image, and record a human's review decision.
#
# In plain terms: this is where a run's lifecycle starts, runs, and (as
# of Milestone 10) ends. Creating a run ONLY writes a database record --
# it does not capture a chart, fetch market data, call the AI agent,
# score anything, or check any guardrails. That's what
# POST /runs/{run_id}/analyze is for (Milestone 10.5): it delegates the
# entire pipeline to backend/orchestrator.py and persists every step's
# result. This route file itself contains none of that logic -- it just
# calls the orchestrator and turns its result (or its refusal) into an
# HTTP response, the same thin-router pattern every other endpoint here
# follows. The review endpoint below is equally narrow: it records a
# human's judgment about results that already exist -- it never
# re-scores, re-evaluates, or re-runs anything.

import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend import config
from backend.orchestrator import FORCE_SCENARIOS, RunAlreadyAnalyzedError, run_pipeline
from backend.schemas import (
    AcceptProposalResponse,
    HumanReviewRequest,
    HumanReviewResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListResponse,
    RunSummary,
)
from capture.base import REPO_ROOT
from database import crud
from database.database import get_session
from database.models import Capture
from guardrails.rules import GuardrailOutcome, outcome_from_results

router = APIRouter(prefix="/runs", tags=["runs"])

# The one directory a served screenshot is ever allowed to come from.
# Resolved once at import time, reusing capture/base.py's own REPO_ROOT
# (the single source of truth for where the repo lives) rather than
# recomputing it a second way.
SCREENSHOTS_ROOT = (REPO_ROOT / "screenshots").resolve()


def _run_to_detail(run) -> RunDetail:
    """
    Builds the RunDetail response for a Run ORM object: the run plus its
    full audit trail, plus the derived guardrail_outcome. Shared by
    GET /runs/{run_id} and POST /runs/{run_id}/analyze so both compute
    "the outcome" the identical way -- from outcome_from_results() over
    whatever GuardrailResult rows actually exist, never a stored column.
    """
    detail = RunDetail.model_validate(run)
    outcome = outcome_from_results(
        (result.guardrail_name, result.passed) for result in run.guardrail_results
    )
    return detail.model_copy(update={"guardrail_outcome": outcome.value if outcome else None})


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

    return _run_to_detail(run)


@router.post("/{run_id}/analyze", response_model=RunDetail)
def analyze_run(
    run_id: str,
    force_scenario: Optional[str] = Query(
        default=None,
        description=(
            "TESTING ONLY (Milestone 12). Deliberately forces one pipeline stage to a "
            "synthetic failed/stale/high-uncertainty/perfect-score result, so a "
            "guardrail's behavior can be proven with a real, reproducible run. Refused "
            "with 403 unless TESTING_CONTROLS_ENABLED=true is set in the backend's own "
            ".env -- off by default, never toggleable from a request alone. See "
            "docs/failure_modes.md."
        ),
    ),
    session: Session = Depends(get_session),
) -> RunDetail:
    """
    Runs the full capture -> market data -> agent -> evaluation ->
    guardrails pipeline for this run (Milestone 10.5) and persists every
    step. Synchronous -- by the time this returns, the pipeline has
    already finished, so the response already reflects the final
    guardrail outcome. A run can only be analyzed once: a second attempt
    is refused with 409, the same way a second human decision is.
    """
    run = crud.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if force_scenario is not None:
        if not config.TESTING_CONTROLS_ENABLED:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Testing controls are disabled. Set TESTING_CONTROLS_ENABLED=true in "
                    "the backend's .env and restart the backend to use force_scenario -- "
                    "this is off by default so a real run's honesty can never be affected "
                    "by it accidentally."
                ),
            )
        if force_scenario not in FORCE_SCENARIOS:
            allowed = ", ".join(sorted(FORCE_SCENARIOS))
            raise HTTPException(
                status_code=422, detail=f"force_scenario must be one of: {allowed}"
            )

    try:
        updated_run = run_pipeline(session, run_id, force_scenario=force_scenario)
    except RunAlreadyAnalyzedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _run_to_detail(updated_run)


def _resolve_screenshot_path(capture: Capture) -> Optional[Path]:
    """
    Resolves a Capture row's stored screenshot_path and confirms it's
    actually inside SCREENSHOTS_ROOT before anything is served.

    Returns None if the path can't be resolved at all, or if it resolves
    outside screenshots/ -- the caller treats both the same as "no image
    available," on purpose. A stored path pointing outside screenshots/
    would mean either a bug elsewhere in this app or a corrupted/tampered
    row; either way, this function's job is only to refuse it, not to
    explain why to the client.
    """
    if not capture.screenshot_path:
        return None
    try:
        resolved = Path(capture.screenshot_path).resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(SCREENSHOTS_ROOT):
        return None
    return resolved


@router.get("/{run_id}/screenshot")
def get_run_screenshot(run_id: str, session: Session = Depends(get_session)) -> FileResponse:
    """
    Serves the chart image for one run's own capture -- and only that
    run's capture. There is no path, filename, or directory parameter
    anywhere on this endpoint; the file to serve is derived entirely from
    run_id by looking up that run's Capture row. A client cannot ask for
    any file but the one this run actually captured, which rules out path
    traversal as a class of bug here rather than merely guarding against
    it.

    Milestone 11 prerequisite: Capture.screenshot_path is an absolute
    path on the server's own filesystem -- meaningless to a browser on
    its own. This is the only way the frontend can actually display a
    captured chart. Deliberately NOT a static file mount: screenshots/
    is never exposed as a browsable directory (a LIVE capture is the
    user's own chart and must not be enumerable by filename), and every
    request is checked against the run it claims to belong to.

    404, never 500, for every way there can be "no image right now":
    the run doesn't exist, the run has no capture yet, the capture
    failed, the stored path resolves outside screenshots/, or the file
    is simply missing from disk. All of these are legitimate states this
    application can be in, not server errors.
    """
    run = crud.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    capture = run.captures[0] if run.captures else None
    if capture is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} has no chart capture yet")

    if capture.status != "SUCCESS":
        detail = capture.error_message or "no error message provided"
        raise HTTPException(
            status_code=404,
            detail=f"Run {run_id}'s chart capture did not succeed (status={capture.status}): {detail}",
        )

    resolved_path = _resolve_screenshot_path(capture)
    if resolved_path is None:
        # Either the path couldn't be resolved at all, or it resolved
        # outside SCREENSHOTS_ROOT. Same generic response either way --
        # deliberately vague, so this response never confirms to a
        # client that path traversal specifically was what happened.
        raise HTTPException(status_code=404, detail=f"No screenshot is available for run {run_id}")

    if not resolved_path.is_file():
        # A legitimate, non-security failure (the file was moved or
        # deleted after the row was written) -- safe to be specific.
        raise HTTPException(
            status_code=404,
            detail=f"Run {run_id}'s screenshot file is missing on disk (expected at {resolved_path}).",
        )

    media_type = mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
    return FileResponse(resolved_path, media_type=media_type)


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


@router.post("/{run_id}/accept-proposal", response_model=AcceptProposalResponse, status_code=201)
def accept_proposal(run_id: str, session: Session = Depends(get_session)) -> AcceptProposalResponse:
    """
    7A Iteration 1. Accepting a proposal never rescores or re-analyzes
    run_id -- it only creates a brand-new run, seeded with the agent's
    proposed entry/stop/target/direction as that new run's own ordinary
    trade params (Run.accepted_from_run_id records where they came from).
    The new run still has to go through POST /runs/{new_run_id}/analyze
    like any other run -- accepting a proposal is not itself an analysis,
    and the accepted levels are not pre-scored by this endpoint in any way.

    409 if this run has no agent proposal at all (the agent's analysis
    never succeeded, so the question was never reached) or the agent
    explicitly declined to propose (has_proposal=False) -- either way,
    there is nothing here to accept. An incoherent proposal (stop on the
    wrong side, zero risk distance) CAN be accepted: the new run just
    carries those same incoherent params, and will fail TRADE_PARAMS_VALID
    when analyzed, exactly as it would if a human had typed those numbers
    in by hand -- no special-casing needed, since accepting doesn't imply
    endorsing the math.
    """
    run = crud.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    proposal = run.proposal
    if proposal is None or not proposal.has_proposal:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} has no agent-proposed trade levels to accept.",
        )

    new_run = crud.create_run(
        session,
        symbol=run.symbol,
        timeframe=run.timeframe,
        direction=proposal.direction,
        entry=proposal.entry,
        stop=proposal.stop,
        target=proposal.target,
        status="CREATED",
        accepted_from_run_id=run.id,
    )
    crud.add_audit_event(
        session,
        run_id=new_run.id,
        event_type="run_created",
        event_message=f"Run created for {new_run.symbol} {new_run.timeframe}",
    )
    crud.add_audit_event(
        session,
        run_id=new_run.id,
        event_type="accepted_from_proposal",
        event_message=(
            f"Created by accepting the agent-proposed trade levels from run {run.id} "
            f"(direction={proposal.direction}, entry={proposal.entry}, stop={proposal.stop}, "
            f"target={proposal.target})."
        ),
    )
    crud.add_audit_event(
        session,
        run_id=run.id,
        event_type="proposal_accepted",
        event_message=(
            f"Agent-proposed trade levels accepted by a human reviewer; new run "
            f"{new_run.id} was created from them."
        ),
    )

    return AcceptProposalResponse(
        id=new_run.id,
        accepted_from_run_id=run.id,
        symbol=new_run.symbol,
        timeframe=new_run.timeframe,
        direction=new_run.direction,
        entry=new_run.entry,
        stop=new_run.stop,
        target=new_run.target,
        status=new_run.status,
    )
