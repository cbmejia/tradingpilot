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
    AGENT_PROPOSAL_DIRECTION_ALLOWED_VALUES,
    CAPTURE_TIMEFRAME_ROLE_ALLOWED_VALUES,
    CONFIRMATION_TREND_DIRECTION_ALLOWED_VALUES,
    CONFIRMATION_TREND_QUALITY_ALLOWED_VALUES,
    MARKET_DATA_MODE_ALLOWED_VALUES,
    AgentAnalysis,
    AgentProposal,
    AuditEvent,
    Capture,
    ConfirmationAnalysis,
    Evaluation,
    GuardrailResult,
    HumanReview,
    MarketData,
    Run,
)


def _validate_mode(mode: str) -> None:
    """
    Application-level half of the market-data mode check (the other half
    is the CHECK constraint on MarketData in database/models.py) -- same
    defense-in-depth reasoning as _validate_categorical_fields() below.
    tools/market_data.py's MarketDataManager already only ever produces
    "LIVE" or "DEMO", so in the normal path this never fires.
    """
    if mode not in MARKET_DATA_MODE_ALLOWED_VALUES:
        raise ValueError(f"mode={mode!r} is not one of the allowed values {MARKET_DATA_MODE_ALLOWED_VALUES}")


def _validate_timeframe_role(timeframe_role: str) -> None:
    """
    Application-level half of the timeframe-role check (7A Iteration 2;
    the other half is the CHECK constraint on Capture in
    database/models.py). backend/orchestrator.py is the only caller that
    ever constructs this value, and it only ever uses "PRIMARY" or
    "CONFIRMATION", so in the normal path this never fires.
    """
    if timeframe_role not in CAPTURE_TIMEFRAME_ROLE_ALLOWED_VALUES:
        raise ValueError(
            f"timeframe_role={timeframe_role!r} is not one of the allowed values "
            f"{CAPTURE_TIMEFRAME_ROLE_ALLOWED_VALUES}"
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


def _validate_proposal_direction(direction: str) -> None:
    """
    Application-level half of the proposal-direction check (the other
    half is the CHECK constraint on AgentProposal in database/models.py)
    -- same defense-in-depth reasoning as _validate_categorical_fields()
    above. agents/trade_agent.py's own _parse_response() already rejects
    an out-of-set direction before an analysis is ever accepted as
    SUCCESS, so in the normal path this never fires.
    """
    if direction not in AGENT_PROPOSAL_DIRECTION_ALLOWED_VALUES:
        raise ValueError(
            f"direction={direction!r} is not one of the allowed values "
            f"{AGENT_PROPOSAL_DIRECTION_ALLOWED_VALUES}"
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
    accepted_from_run_id: Optional[str] = None,
) -> Run:
    """
    accepted_from_run_id (7A Iteration 1): set only by
    POST /runs/{run_id}/accept-proposal, pointing back at the run whose
    agent-proposed levels became this run's own entry/stop/target. None
    (the default, and the only value every ordinary POST /runs call ever
    uses) for a ordinary, hand-entered run.
    """
    run = Run(
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        status=status,
        accepted_from_run_id=accepted_from_run_id,
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
    timeframe_role: str,
    symbol: str,
    timeframe: str,
    status: str,
    screenshot_path: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> Capture:
    """
    timeframe_role (7A Iteration 2): "PRIMARY" or "CONFIRMATION" --
    required, not defaulted, same "no silent defaulting" reasoning as
    every other required categorical parameter in this file. A run's
    first (and, before this iteration, only) capture is always PRIMARY;
    a second capture of one higher timeframe, when the ladder has a rung
    above the primary, is CONFIRMATION.
    """
    _validate_timeframe_role(timeframe_role)
    capture = Capture(
        run_id=run_id,
        capture_mode=capture_mode,
        timeframe_role=timeframe_role,
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
    mode: str,
    symbol: str,
    source: str,
    status: str,
    price: Optional[float] = None,
    timestamp: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> MarketData:
    """
    Record a market-data fetch attempt, success or failure alike.

    mode ("LIVE" | "DEMO", Milestone 10.5 fix 3) is required, not
    optional/defaulted -- every real MarketQuote has one, even on
    failure, matching how add_capture()'s capture_mode already works.
    Validated against the allowed set before anything is written; see
    _validate_mode() above for why this check exists here too, not just
    as the CHECK constraint on MarketData.
    """
    _validate_mode(mode)
    data = MarketData(
        run_id=run_id,
        mode=mode,
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
    model: Optional[str] = None,
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

    model (7A Iteration 3): the Claude model id this call used. Optional
    at this layer (unlike the required dataclass field it's read from --
    see AgentAnalysisResult.model) because NULL is a legitimate,
    meaningful value here: it's what every pre-Iteration-3 row already
    has, and what a caller that genuinely doesn't know the model should
    store rather than guess.

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
        model=model,
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
    model: Optional[str] = None,
) -> AgentAnalysis:
    """
    Record a FAILED agent analysis -- e.g. Claude's response was
    unusable, or the analysis was never attempted because an upstream
    stage (capture, market data) failed first. Every qualitative field is
    null; nothing here is guessed or filled in. Milestone 10.5 fix: the
    reason this function exists is so a failure has somewhere real to
    live besides the audit_events text trail.

    model (7A Iteration 3): the model this attempt was configured to
    call, even though it failed -- knowing which model failed is real
    diagnostic information (see AgentAnalysisResult.model's docstring).
    None when no real call was ever attempted at all.
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
        model=model,
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
    risk_reward_ratio: float,
) -> Evaluation:
    """
    Record a SUCCESSFUL rubric evaluation for a run.

    total_score is always the sum of the five component scores, computed
    right here. There is deliberately no total_score parameter — the
    caller (including the future AI evaluation engine) cannot pass one in.
    status is always "SUCCESS" here, never a parameter -- for a failed
    evaluation, see add_failed_evaluation() below, which cannot be used to
    smuggle in a score either (it has no score parameters at all).

    risk_reward_ratio (Milestone 10.5 fix 3) is the raw computed ratio
    (e.g. 2.0) behind risk_reward_score's banded value -- required, not
    optional/defaulted, since a real SUCCESS evaluation always has one.
    It is stored as-is, never included in the total_score sum (that sum
    is int-only, unaffected by this float).
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
        risk_reward_ratio=risk_reward_ratio,
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
        risk_reward_ratio=None,
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


def add_agent_proposal(
    session: Session,
    *,
    run_id: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    is_coherent: bool,
    risk_reward_ratio: Optional[float] = None,
    coherence_error: Optional[str] = None,
) -> AgentProposal:
    """
    Record the agent's proposed trade levels for a run -- has_proposal is
    always True here; for a decline, see add_declined_proposal() below.

    is_coherent, and exactly one of risk_reward_ratio/coherence_error, are
    required together: a coherent proposal has a real ratio and no error;
    an incoherent one has a real error and no ratio. Callers (backend/
    orchestrator.py) compute both by calling
    evals.trade_evaluator.compute_risk_reward() on the proposed levels --
    this function stores whatever that returned, it doesn't recompute it,
    for the same "don't risk two numbers disagreeing" reason
    add_evaluation() stores risk_reward_ratio as-is.
    """
    _validate_proposal_direction(direction)
    if is_coherent:
        if risk_reward_ratio is None:
            raise ValueError("risk_reward_ratio is required when is_coherent is True")
        if coherence_error is not None:
            raise ValueError("coherence_error must be None when is_coherent is True")
    else:
        if coherence_error is None:
            raise ValueError("coherence_error is required when is_coherent is False")
        if risk_reward_ratio is not None:
            raise ValueError("risk_reward_ratio must be None when is_coherent is False")

    proposal = AgentProposal(
        run_id=run_id,
        has_proposal=True,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        risk_reward_ratio=risk_reward_ratio,
        is_coherent=is_coherent,
        coherence_error=coherence_error,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def add_declined_proposal(session: Session, *, run_id: str) -> AgentProposal:
    """
    Record that the agent was asked and explicitly declined to propose
    trade levels for a run -- has_proposal=False, every other field null.
    A real, complete answer, not an error and not the same as no row at
    all (which means the question was never reached -- see AgentProposal's
    docstring in database/models.py).
    """
    proposal = AgentProposal(
        run_id=run_id,
        has_proposal=False,
        direction=None,
        entry=None,
        stop=None,
        target=None,
        risk_reward_ratio=None,
        is_coherent=None,
        coherence_error=None,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def _validate_confirmation_categorical_fields(
    trend_direction: Optional[str], trend_quality: Optional[str]
) -> None:
    """
    Application-level half of the confirmation call's categorical-field
    check (7A Iteration 2; the other half is the CHECK constraint on
    ConfirmationAnalysis in database/models.py) -- same defense-in-depth
    reasoning as _validate_categorical_fields() above.
    agents/trade_agent.py's own _parse_confirmation_response() already
    rejects an out-of-set value before a confirmation analysis is ever
    accepted as SUCCESS, so in the normal path this never fires.
    """
    if trend_direction is not None and trend_direction not in CONFIRMATION_TREND_DIRECTION_ALLOWED_VALUES:
        raise ValueError(
            f"trend_direction={trend_direction!r} is not one of the allowed values "
            f"{CONFIRMATION_TREND_DIRECTION_ALLOWED_VALUES}"
        )
    if trend_quality is not None and trend_quality not in CONFIRMATION_TREND_QUALITY_ALLOWED_VALUES:
        raise ValueError(
            f"trend_quality={trend_quality!r} is not one of the allowed values "
            f"{CONFIRMATION_TREND_QUALITY_ALLOWED_VALUES}"
        )


def add_confirmation_analysis(
    session: Session,
    *,
    run_id: str,
    visible_timeframe: str,
    trend_direction: str,
    trend_quality: str,
    model: Optional[str] = None,
) -> ConfirmationAnalysis:
    """
    Record a SUCCESSFUL confirmation analysis (7A Iteration 2) -- status
    is always "SUCCESS" here, never a parameter, the same pattern
    add_agent_analysis() already uses. For a failed confirmation, see
    add_failed_confirmation_analysis() below.

    model (7A Iteration 3): same optional-with-NULL-default reasoning as
    add_agent_analysis()'s own model parameter.
    """
    _validate_confirmation_categorical_fields(trend_direction, trend_quality)
    analysis = ConfirmationAnalysis(
        run_id=run_id,
        status="SUCCESS",
        visible_timeframe=visible_timeframe,
        trend_direction=trend_direction,
        trend_quality=trend_quality,
        model=model,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def add_failed_confirmation_analysis(
    session: Session,
    *,
    run_id: str,
    error_message: str,
    model: Optional[str] = None,
) -> ConfirmationAnalysis:
    """
    Record a FAILED confirmation analysis -- the confirmation capture
    itself failed, or the confirmation Claude call failed or was
    rejected. Every qualitative field is null, never a fabricated
    placeholder, the same pattern add_failed_agent_analysis() already
    uses.

    model (7A Iteration 3): the model this attempt was configured to
    call, even though it failed. None when no real call was attempted.
    """
    analysis = ConfirmationAnalysis(
        run_id=run_id,
        status="FAILED",
        visible_timeframe=None,
        trend_direction=None,
        trend_quality=None,
        error_message=error_message,
        model=model,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis
