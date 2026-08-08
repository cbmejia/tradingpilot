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
    The agent's qualitative read of the chart and market data.

    Deliberately no numeric fields here — trend/structure/setup/uncertainty
    are all text. Turning qualitative analysis into a number is the
    Evaluation table's job, not the agent's.
    """

    __tablename__ = "agent_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    analysis_text: Mapped[str] = mapped_column(Text)
    trend_assessment: Mapped[str] = mapped_column(String(200))
    structure_assessment: Mapped[str] = mapped_column(String(200))
    setup_assessment: Mapped[str] = mapped_column(String(200))
    uncertainty: Mapped[str] = mapped_column(String(200))
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="analyses")


class Evaluation(Base):
    """
    The deterministic rubric score for a run.

    IMPORTANT: total_score is meant to always be computed by
    crud.add_evaluation() as the sum of the five component scores below.
    That's enforced at the Python level, but Python-level discipline alone
    can be bypassed by constructing Evaluation(...) directly with whatever
    total_score you like — so the CHECK constraint below enforces the same
    rule at the database level. SQLite will refuse to commit any row,
    however it was created, where total_score doesn't equal the sum of the
    five components.
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "total_score = trend_score + structure_score + entry_score "
            "+ risk_reward_score + timing_context_score",
            name="ck_evaluations_total_score_is_sum_of_components",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    trend_score: Mapped[int] = mapped_column()
    structure_score: Mapped[int] = mapped_column()
    entry_score: Mapped[int] = mapped_column()
    risk_reward_score: Mapped[int] = mapped_column()
    timing_context_score: Mapped[int] = mapped_column()
    total_score: Mapped[int] = mapped_column()
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
