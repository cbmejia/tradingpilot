# TradePilot AI — SQLAlchemy models for the full run audit trail.
#
# In plain terms: each class below is one table. A Run is the parent row
# for one full pass through the workflow (pick a symbol -> get a
# recommendation -> human decides). Every other table stores one step's
# result and points back at the Run it belongs to, via run_id. Together,
# querying a Run and its related rows reconstructs exactly what happened,
# in order, for that run — that's the audit trail.
#
# See docs/architecture.md for how these tables map onto the 12-step
# workflow.

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.types import TZDateTime

# The five categorical fields the agent (agents/trade_agent.py) produces
# and the evaluator (evals/trade_evaluator.py) scores from, and the exact
# allowed set for each. Duplicated here rather than imported from
# agents.trade_agent so database/ stays a leaf module with no dependency
# on the agent layer (database/ is imported BY agents/evals/guardrails
# indirectly via backend/orchestrator.py, never the other way around).
# Kept from drifting apart by a dedicated test in tests/test_database.py
# that asserts this dict is identical to agents.trade_agent.CATEGORICAL_
# FIELDS.
AGENT_CATEGORICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "trend_direction": ("UP", "DOWN", "SIDEWAYS", "UNCLEAR"),
    "trend_quality": ("STRONG", "MODERATE", "WEAK", "UNCLEAR"),
    "structure_quality": ("CLEAN", "MIXED", "CHOPPY", "UNCLEAR"),
    "setup_quality": ("TEXTBOOK", "ACCEPTABLE", "MARGINAL", "NONE", "UNCLEAR"),
    "context_risk": ("LOW", "MODERATE", "ELEVATED", "UNCLEAR"),
}


def _categorical_allowed_check(column_name: str) -> str:
    """Builds a '<column> IS NULL OR <column> IN (...)' CHECK expression
    from AGENT_CATEGORICAL_FIELDS, so the allowed-values list is written
    down exactly once (here) rather than duplicated as a second literal
    string per column."""
    values = "', '".join(AGENT_CATEGORICAL_FIELDS[column_name])
    return f"{column_name} IS NULL OR {column_name} IN ('{values}')"


def _new_run_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """
    One end-to-end TradePilot analysis: the symbol/timeframe/params the
    user picked, plus its current status. Everything else in this file
    hangs off of a Run.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_run_id)
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[str] = mapped_column(String(10))
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Values in actual use: "CREATED" (backend/api/routes_runs.py, on
    # creation); "ANALYZING", then "BLOCKED" / "REQUIRES_REVIEW" /
    # "READY_FOR_REVIEW" (backend/orchestrator.py, Milestone 10.5, as the
    # pipeline runs and finishes -- the same three values
    # GuardrailOutcome can be, never "APPROVED"); "APPROVED" / "REJECTED"
    # (backend/api/routes_runs.py's review endpoint, Milestone 10, after a
    # human decision -- the only two values a human review can set). This
    # column just stores whatever string it's given -- validation of
    # what's allowed lives at the API boundary (backend/schemas.py) and in
    # backend/orchestrator.py, not here.
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    captures: Mapped[list["Capture"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    market_data: Mapped[list["MarketData"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["AgentAnalysis"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    guardrail_results: Mapped[list["GuardrailResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    human_review: Mapped["HumanReview | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Capture(Base):
    """One chart-screenshot attempt (live or demo) for a run."""

    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    capture_mode: Mapped[str] = mapped_column(String(10))  # "live" | "demo"
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[str] = mapped_column(String(10))
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10))  # "success" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="captures")


class MarketData(Base):
    """One market-data snapshot attempt for a run."""

    __tablename__ = "market_data"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))  # "success" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="market_data")


class AgentAnalysis(Base):
    """
    The agent's qualitative read of the chart and market data -- success
    or failure alike (Milestone 10.5 fix), including the five categorical
    fields the evaluator actually scores from (Milestone 10.5 fix 2).

    Deliberately no numeric fields here — trend/structure/setup/uncertainty
    are all text. Turning qualitative analysis into a number is the
    Evaluation table's job, not the agent's.

    status/error_message follow the exact same success-or-failure shape
    Capture and MarketData already use. On FAILED, every qualitative
    field below (including the five categorical ones) is left null and
    error_message carries the real reason -- never a fabricated
    placeholder analysis.

    trend_direction/trend_quality/structure_quality/setup_quality/
    context_risk are the exact fields evals/trade_evaluator.py reads to
    compute trend_score/structure_score/entry_score/timing_context_score
    -- storing them here is what lets a completed run's score be traced
    back to the observation that produced it, rather than showing e.g.
    "Trend: 14" with no record of what was actually observed. Each is
    constrained to its own documented allowed set (AGENT_CATEGORICAL_
    FIELDS above) by a CHECK constraint -- the database-level half of a
    deliberate double check; see database/crud.py's
    add_agent_analysis() for the application-level half, which runs
    first and gives a clearer Python-level error.

    This table intentionally has no CHECK constraint tying status to
    nullability (matching Capture and MarketData, neither of which has
    one either); Evaluation is the one table that needs one, because it
    alone already had to enforce total_score = sum of components.
    """

    __tablename__ = "agent_analyses"
    __table_args__ = (
        CheckConstraint(
            _categorical_allowed_check("trend_direction"),
            name="ck_agent_analyses_trend_direction_allowed",
        ),
        CheckConstraint(
            _categorical_allowed_check("trend_quality"),
            name="ck_agent_analyses_trend_quality_allowed",
        ),
        CheckConstraint(
            _categorical_allowed_check("structure_quality"),
            name="ck_agent_analyses_structure_quality_allowed",
        ),
        CheckConstraint(
            _categorical_allowed_check("setup_quality"),
            name="ck_agent_analyses_setup_quality_allowed",
        ),
        CheckConstraint(
            _categorical_allowed_check("context_risk"),
            name="ck_agent_analyses_context_risk_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(String(10))  # "SUCCESS" | "FAILED"
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend_assessment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    structure_assessment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    setup_assessment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    uncertainty: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trend_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trend_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    structure_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    setup_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    context_risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="analyses")


class Evaluation(Base):
    """
    The deterministic rubric score for a run -- success or failure alike
    (Milestone 10.5 fix).

    IMPORTANT: total_score is meant to always be computed by
    crud.add_evaluation() as the sum of the five component scores below.
    That's enforced at the Python level, but Python-level discipline alone
    can be bypassed by constructing Evaluation(...) directly with whatever
    total_score you like — so the CHECK constraint below enforces the same
    rule at the database level, for a SUCCESS row.

    A FAILED row (the agent analysis failed, or the risk/reward numbers
    were incoherent) stores no scores at all -- every score column,
    including total_score, is NULL. Never zero: zero is a real, meaningful
    score, and storing it for a run that was never actually scored would
    be indistinguishable from a genuine all-zero evaluation.

    The CHECK constraint below enforces both halves of that split at once,
    keyed off status, so there is no third possibility a row could be in:
    - status='SUCCESS' requires all six score columns to be non-null AND
      total_score to exactly equal the sum of the other five (the
      original Milestone 3 rule, unchanged for this case).
    - status='FAILED' requires all six score columns to be null.
    Any other combination (a SUCCESS row with a null score, a FAILED row
    with a non-null score, an unrecognized status value entirely) fails
    the constraint and the row is refused, however it was constructed.
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "("
            "status = 'FAILED' "
            "AND trend_score IS NULL AND structure_score IS NULL "
            "AND entry_score IS NULL AND risk_reward_score IS NULL "
            "AND timing_context_score IS NULL AND total_score IS NULL"
            ") OR ("
            "status = 'SUCCESS' "
            "AND trend_score IS NOT NULL AND structure_score IS NOT NULL "
            "AND entry_score IS NOT NULL AND risk_reward_score IS NOT NULL "
            "AND timing_context_score IS NOT NULL AND total_score IS NOT NULL "
            "AND total_score = trend_score + structure_score + entry_score "
            "+ risk_reward_score + timing_context_score"
            ")",
            name="ck_evaluations_total_score_is_sum_of_components",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    status: Mapped[str] = mapped_column(String(10))  # "SUCCESS" | "FAILED"
    trend_score: Mapped[int | None] = mapped_column(nullable=True)
    structure_score: Mapped[int | None] = mapped_column(nullable=True)
    entry_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_reward_score: Mapped[int | None] = mapped_column(nullable=True)
    timing_context_score: Mapped[int | None] = mapped_column(nullable=True)
    total_score: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="evaluations")


class GuardrailResult(Base):
    """One guardrail's pass/fail outcome for a run (e.g. "is RR high enough?")."""

    __tablename__ = "guardrail_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    guardrail_name: Mapped[str] = mapped_column(String(50))
    passed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="guardrail_results")


class HumanReview(Base):
    """
    The human's approve/reject decision for a run.

    run_id is unique — at most one review per run. This is the only table
    whose contents can move a run to a truly final state.
    """

    __tablename__ = "human_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    decision: Mapped[str] = mapped_column(String(20))  # "APPROVED" | "REJECTED"
    decided_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="human_review")


class AuditEvent(Base):
    """
    A single timestamped log line for a run (e.g. "capture started",
    "guardrail blocked run"). This is the free-text trail alongside the
    structured tables above.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    event_message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="audit_events")
