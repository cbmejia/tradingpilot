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
    symbol: str
    timeframe: str
    screenshot_path: Optional[str]
    captured_at: Optional[datetime]
    status: str
    error_message: Optional[str]


class MarketDataOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    price: Optional[float]
    timestamp: Optional[datetime]
    source: str
    status: str
    error_message: Optional[str]


class AgentAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_text: str
    trend_assessment: str
    structure_assessment: str
    setup_assessment: str
    uncertainty: str
    timestamp: datetime


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trend_score: int
    structure_score: int
    entry_score: int
    risk_reward_score: int
    timing_context_score: int
    total_score: int
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
