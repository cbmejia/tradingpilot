# TradePilot AI — pydantic request/response models for the API boundary.
#
# In plain terms: every shape of data the API accepts or returns is
# defined here. FastAPI uses these to validate incoming requests
# (rejecting anything that doesn't fit with a 422 error, never a crash)
# and to shape outgoing responses consistently.
#
# Nothing here accepts a total evaluation score from the client, and
# nothing here accepts a guardrail verdict from the client either -- the
# human-review schema below has exactly two fields: a decision and an
# optional comment. Everything else about a run's outcome (its score, its
# guardrail results) is already computed and stored before a human ever
# looks at it; reviewing a run cannot rewrite any of that.

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The only timeframes the app currently understands. Anything else is
# rejected at the API boundary rather than silently stored.
ALLOWED_TIMEFRAMES: frozenset[str] = frozenset(
    {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}
)


class HealthResponse(BaseModel):
    status: str
    database: str


class RunCreateRequest(BaseModel):
    """What the client sends to POST /runs."""

    symbol: str = Field(min_length=1, max_length=20)
    timeframe: str = Field(min_length=1, max_length=10)
    direction: Optional[str] = Field(default=None, max_length=10)
    entry: Optional[float] = Field(default=None, gt=0)
    stop: Optional[float] = Field(default=None, gt=0)
    target: Optional[float] = Field(default=None, gt=0)

    @field_validator("timeframe")
    @classmethod
    def timeframe_must_be_allowed(cls, value: str) -> str:
        if value not in ALLOWED_TIMEFRAMES:
            allowed = ", ".join(sorted(ALLOWED_TIMEFRAMES))
            raise ValueError(f"timeframe must be one of: {allowed}")
        return value


class RunCreateResponse(BaseModel):
    """What POST /runs sends back: just enough to confirm the run exists."""

    id: str
    status: str


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    capture_mode: str
    # 7A Iteration 2: "PRIMARY" | "CONFIRMATION" -- a run can now have up
    # to two captures; this is what distinguishes them (order in the
    # captures list also guarantees PRIMARY first, but this field is the
    # explicit, unambiguous way to tell them apart).
    timeframe_role: str
    symbol: str
    timeframe: str
    screenshot_path: Optional[str]
    captured_at: Optional[datetime]
    status: str
    error_message: Optional[str]


class MarketDataOut(BaseModel):
    """
    Milestone 10.5 fix 3: mode ("LIVE" | "DEMO") exposes the quote's real
    source directly on the record -- a client no longer has to infer it
    from `source` ("demo_fixture" vs. "alpha_vantage"). Always present,
    success or failure alike, matching CaptureOut.capture_mode.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    symbol: str
    price: Optional[float]
    timestamp: Optional[datetime]
    source: str
    status: str
    error_message: Optional[str]


class AgentAnalysisOut(BaseModel):
    """
    Milestone 10.5 fix: status/error_message expose success or failure
    directly on the record -- a client no longer has to infer it from the
    audit trail. The qualitative fields are Optional because a FAILED row
    has every one of them set to null, never a fabricated placeholder.

    Milestone 10.5 fix 2: trend_direction/trend_quality/structure_quality/
    setup_quality/context_risk are the exact categorical fields
    evals/trade_evaluator.py scored from -- exposed here so a client can
    trace trend_score/structure_score/entry_score/timing_context_score
    (on EvaluationOut below) back to the actual observation behind each
    one, not just see the number.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    analysis_text: Optional[str]
    trend_assessment: Optional[str]
    structure_assessment: Optional[str]
    setup_assessment: Optional[str]
    uncertainty: Optional[str]
    trend_direction: Optional[str]
    trend_quality: Optional[str]
    structure_quality: Optional[str]
    setup_quality: Optional[str]
    context_risk: Optional[str]
    error_message: Optional[str]
    timestamp: datetime


class EvaluationOut(BaseModel):
    """
    Milestone 10.5 fix: status/error_message expose success or failure
    directly on the record. The score fields are Optional because a
    FAILED row has every one of them, including total_score, set to
    null -- never zero, which is itself a real, meaningful score.

    Milestone 10.5 fix 3: risk_reward_ratio is the raw computed number
    (e.g. 2.0) behind risk_reward_score's 0/10/20 band -- the same
    traceability the categorical fields give the other four components.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    trend_score: Optional[int]
    structure_score: Optional[int]
    entry_score: Optional[int]
    risk_reward_score: Optional[int]
    timing_context_score: Optional[int]
    total_score: Optional[int]
    risk_reward_ratio: Optional[float]
    error_message: Optional[str]
    timestamp: datetime


class AgentProposalOut(BaseModel):
    """
    7A Iteration 1. has_proposal=False means the agent was asked and
    declined -- direction/entry/stop/target/risk_reward_ratio/is_coherent/
    coherence_error are all null in that case, never a fabricated
    placeholder. has_proposal=True always has direction/entry/stop/target
    populated, and then either risk_reward_ratio (coherent) or
    coherence_error (incoherent) populated, never both.

    This is informational only -- it never appears anywhere
    evals/trade_evaluator.py or guardrails/rules.py reads from for this
    run's own score or guardrail outcome.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    has_proposal: bool
    direction: Optional[str]
    entry: Optional[float]
    stop: Optional[float]
    target: Optional[float]
    risk_reward_ratio: Optional[float]
    is_coherent: Optional[bool]
    coherence_error: Optional[str]
    timestamp: datetime


class ConfirmationAnalysisOut(BaseModel):
    """
    7A Iteration 2. The confirmation call's own read of a run's
    confirmation-timeframe chart -- a SEPARATE Claude call from the
    primary AgentAnalysisOut above (see agents/trade_agent.py's
    TradeAgent.analyze_confirmation()). has_proposal-style absence
    matters here too: no ConfirmationAnalysisOut on a RunDetail at all
    means the question was never reached (the primary timeframe was
    already at the top of the ladder, or force_scenario suppressed it);
    status="FAILED" means it was reached and didn't succeed (a real
    reason in error_message either way).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    visible_timeframe: Optional[str]
    trend_direction: Optional[str]
    trend_quality: Optional[str]
    error_message: Optional[str]
    timestamp: datetime


class GuardrailResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    guardrail_name: str
    passed: bool
    reason: Optional[str]
    timestamp: datetime


class HumanReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision: str
    decided_at: datetime
    comment: Optional[str]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    event_message: str
    timestamp: datetime


class RunSummary(BaseModel):
    """One row of GET /runs -- no child records, just the run itself."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    timeframe: str
    direction: Optional[str]
    entry: Optional[float]
    stop: Optional[float]
    target: Optional[float]
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    # 7A Iteration 1: set only on a run created via
    # POST /runs/{run_id}/accept-proposal -- the id of the run whose
    # agent-proposed levels became this run's own entry/stop/target. Null
    # for every ordinary, hand-entered run.
    accepted_from_run_id: Optional[str] = None


class RunDetail(RunSummary):
    """GET /runs/{id} -- the run plus every child record: the full audit trail."""

    model_config = ConfigDict(from_attributes=True)

    captures: list[CaptureOut] = []
    market_data: list[MarketDataOut] = []
    analyses: list[AgentAnalysisOut] = []
    evaluations: list[EvaluationOut] = []
    guardrail_results: list[GuardrailResultOut] = []
    human_review: Optional[HumanReviewOut] = None
    audit_events: list[AuditEventOut] = []
    # 7A Iteration 1: None if the agent analysis never succeeded (so the
    # question of a proposal was never reached) -- see AgentProposalOut
    # for the has_proposal=False vs. absent distinction.
    proposal: Optional[AgentProposalOut] = None
    # 7A Iteration 2: None if there was no confirmation timeframe to
    # attempt at all (top of the ladder, or force_scenario active) -- see
    # ConfirmationAnalysisOut's own docstring for the absent-vs-FAILED
    # distinction.
    confirmation_analysis: Optional[ConfirmationAnalysisOut] = None

    # Derived, not a database column: "BLOCKED" / "REQUIRES_REVIEW" /
    # "READY_FOR_REVIEW", computed from guardrail_results above using the
    # same rule classification guardrails/rules.py uses live -- or None
    # if no guardrail results exist for this run yet. Added so the review
    # state (this + human_review above) is obvious from one response,
    # without the client re-implementing the blocking/review-forcing
    # rule split itself.
    guardrail_outcome: Optional[str] = None


# --- Human review (Milestone 10) ---

ALLOWED_DECISIONS: frozenset[str] = frozenset({"APPROVED", "REJECTED"})


class HumanReviewRequest(BaseModel):
    """
    What the client sends to POST /runs/{run_id}/review.

    Deliberately just two fields. There is no field here for a score, a
    guardrail outcome, or anything else about the run's results -- a
    human supplies a decision and, optionally, why. Any other data in
    the request body is ignored, not stored, and has no effect.
    """

    decision: str
    comment: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("decision")
    @classmethod
    def decision_must_be_allowed(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in ALLOWED_DECISIONS:
            allowed = ", ".join(sorted(ALLOWED_DECISIONS))
            raise ValueError(f"decision must be one of: {allowed}")
        return normalized


class HumanReviewResponse(BaseModel):
    """What POST /runs/{run_id}/review sends back."""

    run_id: str
    decision: str
    decided_at: datetime
    comment: Optional[str]
    run_status: str


class RunListResponse(BaseModel):
    """GET /runs -- a page of runs, newest first."""

    items: list[RunSummary]
    limit: int
    offset: int
    total: int


# --- Accept a proposal (7A Iteration 1) ---


class AcceptProposalResponse(BaseModel):
    """
    What POST /runs/{run_id}/accept-proposal sends back: the brand-new
    run it just created. This never touches the source run's own score or
    guardrail outcome -- the accepted levels become this new run's
    ordinary Run.entry/stop/target, indistinguishable from a run someone
    typed in by hand, except for accepted_from_run_id recording where they
    actually came from.
    """

    id: str
    accepted_from_run_id: str
    symbol: str
    timeframe: str
    direction: str
    entry: float
    stop: float
    target: float
    status: str
