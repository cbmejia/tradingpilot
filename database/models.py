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


# The two source modes every LIVE/DEMO-split tool in this app can be in
# (capture/base.py's CaptureMode, tools/market_data.py's MarketDataMode).
# Duplicated here for the same reason AGENT_CATEGORICAL_FIELDS is: so
# database/ stays a leaf module that doesn't import capture/ or tools/.
MARKET_DATA_MODE_ALLOWED_VALUES: tuple[str, ...] = ("LIVE", "DEMO")

# 7A Iteration 1: the two directions an agent-proposed trade level can
# take. Duplicated from agents.trade_agent.ALLOWED_PROPOSAL_DIRECTIONS for
# the same leaf-module reason as AGENT_CATEGORICAL_FIELDS above -- kept
# from drifting apart by a dedicated test in tests/test_database.py.
AGENT_PROPOSAL_DIRECTION_ALLOWED_VALUES: tuple[str, ...] = ("LONG", "SHORT")

# 7A Iteration 2: which of a run's (up to two) captures this row is.
# Unlike AGENT_CATEGORICAL_FIELDS/AGENT_PROPOSAL_DIRECTION_ALLOWED_VALUES,
# this has no "real" source of truth in capture/ to duplicate from --
# capture/ stays completely agnostic to "primary vs. confirmation," which
# is purely an orchestration/persistence-layer distinction about WHY a
# capture was taken, never something a CaptureProvider needs to know. Only
# backend/orchestrator.py ever constructs this value, never a client, so
# there's no query-param validation layer for it either -- just this
# constant, the CHECK constraint below, and crud.py's application-level
# check, the same double-enforcement pattern every other validated column
# in this file already uses.
CAPTURE_TIMEFRAME_ROLE_ALLOWED_VALUES: tuple[str, ...] = ("PRIMARY", "CONFIRMATION")

# 7A Iteration 2: the confirmation call's own categorical fields.
# Duplicated from agents.trade_agent.CONFIRMATION_TREND_DIRECTION_ALLOWED/
# CONFIRMATION_TREND_QUALITY_ALLOWED for the same leaf-module reason as
# AGENT_CATEGORICAL_FIELDS above.
CONFIRMATION_TREND_DIRECTION_ALLOWED_VALUES: tuple[str, ...] = ("UP", "DOWN", "SIDEWAYS", "UNCLEAR")
CONFIRMATION_TREND_QUALITY_ALLOWED_VALUES: tuple[str, ...] = ("STRONG", "MODERATE", "WEAK", "UNCLEAR")


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
    # 7A Iteration 1: set only on a run created via POST
    # /runs/{run_id}/accept-proposal -- points back at the run whose
    # agent-proposed levels were accepted. Null for every ordinary run
    # (including every run created before this iteration). A
    # self-referential FK, not a relationship -- nothing in this codebase
    # needs to walk from a run to its source run via the ORM; the
    # accept-proposal endpoint already has both Run objects in hand at the
    # moment it needs them.
    accepted_from_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    # order_by="Capture.id" (7A Iteration 2): a run can now hold up to two
    # captures (PRIMARY, then CONFIRMATION), and the primary must always
    # come back first -- every existing reader of run.captures[0] assumes
    # it's the primary. Ordering by id (assigned in insertion order, and
    # the primary is always persisted before the confirmation) makes that
    # an explicit guarantee rather than incidental SQLite return order.
    captures: Mapped[list["Capture"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Capture.id"
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
    proposal: Mapped["AgentProposal | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    confirmation_analysis: Mapped["ConfirmationAnalysis | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class Capture(Base):
    """
    One chart-screenshot attempt (live or demo) for a run.

    timeframe_role (7A Iteration 2) -- "PRIMARY" or "CONFIRMATION" --
    distinguishes a run's (up to two) captures from each other now that
    `run.captures` can genuinely hold more than one row: the timeframe the
    user actually intends to trade on ("PRIMARY", the only kind that
    existed before this iteration) and, when the ladder has a rung above
    it, one higher timeframe captured purely for cross-timeframe context
    ("CONFIRMATION"). Required, never defaulted -- every capture, from
    every era of this codebase, now has an explicit role; there is no
    third "unspecified" state. Existing rows (from before this column
    existed) were backfilled to "PRIMARY" by a one-time raw-SQL migration
    against the live dev database rather than the usual "delete and
    recreate" -- see the 7A Iteration 2 entry in docs/iterations.md for
    why: the dev database held the only record of a real finding (agent-
    proposed RR varying with what the agent was shown) and deleting it
    would have destroyed that evidence.
    """

    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint(
            "timeframe_role IN ('PRIMARY', 'CONFIRMATION')",
            name="ck_captures_timeframe_role_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    capture_mode: Mapped[str] = mapped_column(String(10))  # "live" | "demo"
    timeframe_role: Mapped[str] = mapped_column(String(20))  # "PRIMARY" | "CONFIRMATION"
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[str] = mapped_column(String(10))
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10))  # "success" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="captures")


class MarketData(Base):
    """
    One market-data snapshot attempt for a run.

    mode ("LIVE" | "DEMO", Milestone 10.5 fix 3) stores MarketQuote.mode
    directly -- always present, success or failure alike, matching how
    Capture.capture_mode already works. Before this fix, whether a quote
    was DEMO-sourced was only inferable indirectly from `source`
    ("demo_fixture" vs. "alpha_vantage"), a string that happens to be
    mode-specific today but isn't a structural guarantee. That mattered
    because the SYNTHETIC_DATA guardrail's whole job is proving a run
    used sample data -- its evidence belongs in a real column, not an
    inference. Constrained to exactly "LIVE"/"DEMO" by the CHECK
    constraint below (database level) and by crud.add_market_data()
    (application level) -- the same double-enforcement pattern used for
    the agent's categorical fields.
    """

    __tablename__ = "market_data"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('LIVE', 'DEMO')",
            name="ck_market_data_mode_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    mode: Mapped[str] = mapped_column(String(10))  # "LIVE" | "DEMO"
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
    # 7A Iteration 3: the Claude model id this attempt was configured to
    # call. Nullable -- NULL means no real call was ever attempted (an
    # upstream stage failed first, or this is a synthetic force_scenario
    # result), never a guess. See agents/trade_agent.py's
    # AgentAnalysisResult.model docstring for the full reasoning.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    total_score you like — so the first CHECK constraint below enforces
    the same rule at the database level, for a SUCCESS row.

    A FAILED row (the agent analysis failed, or the risk/reward numbers
    were incoherent) stores no scores at all -- every score column,
    including total_score, is NULL. Never zero: zero is a real, meaningful
    score, and storing it for a run that was never actually scored would
    be indistinguishable from a genuine all-zero evaluation.

    The first CHECK constraint enforces both halves of that split at
    once, keyed off status, so there is no third possibility a row could
    be in:
    - status='SUCCESS' requires all six score columns to be non-null AND
      total_score to exactly equal the sum of the other five (the
      original Milestone 3 rule, unchanged for this case).
    - status='FAILED' requires all six score columns to be null.
    Any other combination (a SUCCESS row with a null score, a FAILED row
    with a non-null score, an unrecognized status value entirely) fails
    the constraint and the row is refused, however it was constructed.

    risk_reward_ratio (Milestone 10.5 fix 3) is the raw computed number
    (e.g. 2.0) behind risk_reward_score's 0/10/20 band -- the same
    traceability the five categorical fields already give the other four
    components. It is a float, and deliberately kept OUT of the sum-rule
    CHECK constraint above (total_score is a sum of integers; mixing a
    float into that equality would be a correctness risk for no reason,
    since the ratio was never part of what total_score sums). Its own
    nullability is enforced by a SECOND, independent CHECK constraint
    below, following the exact same status-keyed shape as the first:
    null on FAILED, non-null on SUCCESS.
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
        CheckConstraint(
            "(status = 'FAILED' AND risk_reward_ratio IS NULL) "
            "OR (status = 'SUCCESS' AND risk_reward_ratio IS NOT NULL)",
            name="ck_evaluations_risk_reward_ratio_matches_status",
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
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
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


class AgentProposal(Base):
    """
    The agent's own proposed entry/stop/target/direction for a run --
    7A Iteration 1. Deliberately its own table, not new columns on
    agent_analyses or evaluations: evals/trade_evaluator.py never reads
    this table at all, so a proposal can never influence a score by
    accident just because it happens to live next to data the evaluator
    does read. See docs/handoff.md's "The 7A-specific invariant" for why
    that separation is load-bearing, not stylistic.

    run_id is unique -- a run is analyzed at most once (Milestone 10.5),
    so it can have at most one proposal, populated (or explicitly
    declined) at analysis time.

    A row is only ever written when the agent analysis itself SUCCEEDED --
    there's a real yes/no answer about whether the agent proposed levels
    only once it actually produced qualitative output. No row at all means
    the question was never reached (capture/market-data/agent all have to
    succeed first); has_proposal=False means the agent was asked and
    explicitly declined. Those are different facts, and only the second
    one gets a row -- there is no third "not applicable" state to encode.

    has_proposal=False rows have every other column NULL: no direction, no
    levels, no ratio, no coherence note. has_proposal=True rows always have
    direction/entry/stop/target populated, and then split on is_coherent:
    a coherent proposal has risk_reward_ratio (computed once, in
    backend/orchestrator.py, by calling evals/trade_evaluator.py's
    compute_risk_reward() -- the exact same function guardrails/rules.py
    already reuses for the user's own params, not a second implementation)
    and a null coherence_error; an incoherent one (stop on the wrong side,
    zero risk distance) has a null ratio and a real coherence_error
    explaining why, exactly the same "never guess, always record the real
    reason" rule compute_risk_reward() itself already follows for ordinary
    trade params. The CHECK constraint below enforces this three-way shape
    at the database level -- the same double-enforcement pattern (Python
    validation in database/crud.py's add_agent_proposal(), a CHECK
    constraint here as the backstop) every other validated column in this
    file already uses.

    risk_reward_ratio and coherence are informational only -- this table
    has no bearing on the CURRENT run's own guardrails or evaluation.
    Accepting a proposal (POST /runs/{run_id}/accept-proposal) is the only
    way it becomes something that gets scored, and accepting it creates a
    brand-new Run with these levels as ordinary Run.entry/stop/target
    (see Run.accepted_from_run_id), never rescoring this run.
    """

    __tablename__ = "agent_proposals"
    __table_args__ = (
        CheckConstraint(
            "direction IS NULL OR direction IN ('LONG', 'SHORT')",
            name="ck_agent_proposals_direction_allowed",
        ),
        CheckConstraint(
            "("
            "has_proposal = 0 "
            "AND direction IS NULL AND entry IS NULL AND stop IS NULL AND target IS NULL "
            "AND risk_reward_ratio IS NULL AND is_coherent IS NULL AND coherence_error IS NULL"
            ") OR ("
            "has_proposal = 1 "
            "AND direction IS NOT NULL AND entry IS NOT NULL AND stop IS NOT NULL "
            "AND target IS NOT NULL AND is_coherent IS NOT NULL AND ("
            "(is_coherent = 1 AND risk_reward_ratio IS NOT NULL AND coherence_error IS NULL) "
            "OR "
            "(is_coherent = 0 AND risk_reward_ratio IS NULL AND coherence_error IS NOT NULL)"
            "))",
            name="ck_agent_proposals_shape_matches_has_proposal",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    has_proposal: Mapped[bool] = mapped_column(Boolean)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "LONG" | "SHORT"
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_coherent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    coherence_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="proposal")


class ConfirmationAnalysis(Base):
    """
    The confirmation call's own read of a run's confirmation-timeframe
    chart -- 7A Iteration 2. A SEPARATE Claude call from the run's primary
    AgentAnalysis (see agents/trade_agent.py's TradeAgent.
    analyze_confirmation() and its module docstring's Iteration 2 note for
    why); this table is that call's own result, never merged with
    agent_analyses.

    run_id is unique -- a run is analyzed at most once, so at most one
    confirmation analysis. A row exists only when a confirmation stage
    actually applied to this run at all (i.e. the primary timeframe had a
    rung above it on the fixed ladder) -- no row means the question was
    never reached (top of the ladder), the same "no row vs. has_proposal
    =False" distinction AgentProposal already draws. When a row does
    exist, status follows the identical SUCCESS/FAILED shape every other
    pipeline-stage table in this file already uses: SUCCESS has
    visible_timeframe/trend_direction/trend_quality all populated, FAILED
    has all three null and a real error_message -- covering both "the
    confirmation capture itself failed" and "the confirmation Claude call
    failed or was rejected."

    trend_direction/trend_quality are never read by
    evals/trade_evaluator.py -- only by guardrails/rules.py's
    CROSS_TIMEFRAME_AGREEMENT rule, which derives agreement/disagreement
    from these two fields plus the run's own primary trend_direction; the
    agent never states "agreement" itself. Each is constrained to its own
    documented allowed set by a CHECK constraint below, the same
    database-level half of the double-enforcement pattern
    AGENT_CATEGORICAL_FIELDS already uses (database/crud.py's
    add_confirmation_analysis() is the application-level half).
    """

    __tablename__ = "confirmation_analyses"
    __table_args__ = (
        CheckConstraint(
            "trend_direction IS NULL OR trend_direction IN ("
            + ", ".join(f"'{v}'" for v in CONFIRMATION_TREND_DIRECTION_ALLOWED_VALUES)
            + ")",
            name="ck_confirmation_analyses_trend_direction_allowed",
        ),
        CheckConstraint(
            "trend_quality IS NULL OR trend_quality IN ("
            + ", ".join(f"'{v}'" for v in CONFIRMATION_TREND_QUALITY_ALLOWED_VALUES)
            + ")",
            name="ck_confirmation_analyses_trend_quality_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10))  # "SUCCESS" | "FAILED"
    visible_timeframe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trend_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trend_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 7A Iteration 3: same meaning and same NULL-only-when-no-real-call
    # rule as AgentAnalysis.model above.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="confirmation_analysis")
