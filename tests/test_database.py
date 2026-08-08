# TradePilot AI — tests for the database layer (Milestone 3).
#
# Every test here builds its own in-memory SQLite database, so running
# these never touches the real database/tradepilot.db file on disk.

import inspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import crud, models  # noqa: F401 -- models registers tables on Base.metadata
from database.database import Base, init_db

EXPECTED_TABLES = {
    "runs",
    "captures",
    "market_data",
    "agent_analyses",
    "evaluations",
    "guardrail_results",
    "human_reviews",
    "audit_events",
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def test_foreign_keys_are_enforced_on_a_fresh_engine():
    """
    PRAGMA foreign_keys=ON is applied via an event listener registered on
    the SQLAlchemy Engine class itself (see database/database.py), which
    means it fires for every connection on every engine in the process --
    not just the app's main engine. This test builds its own brand-new
    engine (never touched by any other test or by database.py's
    module-level engine) to prove the listener really does apply globally,
    not just to a connection someone happened to set up by hand.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()

    orphan_capture = models.Capture(
        run_id="does-not-exist",
        capture_mode="demo",
        symbol="EURUSD",
        timeframe="1h",
        status="success",
    )
    db.add(orphan_capture)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()
    db.close()


def test_database_initialization_creates_all_tables():
    engine = create_engine("sqlite:///:memory:")

    init_db(engine)

    assert set(sa_inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_init_db_creates_database_file(tmp_path):
    db_path = tmp_path / "test_tradepilot.db"
    engine = create_engine(f"sqlite:///{db_path}")

    init_db(engine)

    assert db_path.exists()
    assert set(sa_inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_create_run(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    assert run.id
    assert run.symbol == "EURUSD"
    assert run.timeframe == "1h"
    assert run.status == "pending"
    assert run.created_at is not None
    assert run.completed_at is None


def test_save_capture(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    capture = crud.add_capture(
        session,
        run_id=run.id,
        capture_mode="demo",
        symbol="EURUSD",
        timeframe="1h",
        status="success",
        screenshot_path="screenshots/demo/eurusd_1h.png",
    )

    assert capture.run_id == run.id
    assert capture.capture_mode == "demo"
    assert capture.status == "success"
    assert capture.error_message is None


def test_save_capture_failure_records_error(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    capture = crud.add_capture(
        session,
        run_id=run.id,
        capture_mode="live",
        symbol="EURUSD",
        timeframe="1h",
        status="error",
        error_message="TradingView page did not load in time",
    )

    assert capture.status == "error"
    assert capture.screenshot_path is None
    assert "did not load" in capture.error_message


def test_capture_timestamp_round_trips_as_timezone_aware_utc(session):
    """
    SQLite has no native datetime type -- by default SQLAlchemy stores
    datetimes as plain text and drops the UTC offset entirely, so a value
    that goes in timezone-aware comes back out naive. That would silently
    break the freshness guardrail later (it needs to subtract captured_at
    from "now", which raises an error -- or silently misbehaves -- if one
    side has a timezone and the other doesn't). This test forces a real
    round trip through the database (not just reading the same Python
    object back) to prove that no longer happens.
    """
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")
    captured_at = datetime.now(timezone.utc)

    capture = crud.add_capture(
        session,
        run_id=run.id,
        capture_mode="demo",
        symbol="EURUSD",
        timeframe="1h",
        status="success",
        screenshot_path="screenshots/demo/eurusd_1h.png",
        captured_at=captured_at,
    )

    session.expire(capture)
    reloaded = session.get(models.Capture, capture.id)

    assert reloaded.captured_at.tzinfo is not None
    assert reloaded.captured_at.utcoffset() == timedelta(0)


def test_run_created_at_round_trips_as_timezone_aware_utc(session):
    """Same round-trip check as above, but for an auto-generated timestamp
    (created_at uses the default=_now on the model, not a caller-supplied
    value) -- confirms both kinds of timestamp are consistent."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    session.expire(run)
    reloaded = session.get(models.Run, run.id)

    assert reloaded.created_at.tzinfo is not None
    assert reloaded.created_at.utcoffset() == timedelta(0)


def test_save_market_data(session):
    """Milestone 10.5 fix 3: mode is stored directly on the record, not
    just inferable from `source`."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        mode="DEMO",
        symbol="EURUSD",
        source="demo_fixture",
        status="success",
        price=1.0921,
    )

    assert data.run_id == run.id
    assert data.price == 1.0921
    assert data.status == "success"
    assert data.mode == "DEMO"


def test_save_market_data_failure_records_error(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        mode="LIVE",
        symbol="EURUSD",
        source="demo_fixture",
        status="error",
        error_message="No price available for this symbol",
    )

    assert data.status == "error"
    assert data.price is None
    assert data.mode == "LIVE"


def test_save_market_data_mode_is_demo_for_a_demo_run(session):
    """Requirement: a DEMO run stores mode DEMO, a LIVE run stores LIVE
    (mirrored by test_save_market_data_mode_is_live_for_a_live_run
    below)."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        mode="DEMO",
        symbol="EURUSD",
        source="demo_fixture",
        status="success",
        price=1.0921,
    )

    assert data.mode == "DEMO"


def test_save_market_data_mode_is_live_for_a_live_run(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        mode="LIVE",
        symbol="EURUSD",
        source="alpha_vantage",
        status="success",
        price=1.0921,
    )

    assert data.mode == "LIVE"


def test_add_market_data_rejects_an_out_of_set_mode(session):
    """Milestone 10.5 fix 3, application-level check: an out-of-set mode
    value is rejected before anything is written."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    with pytest.raises(ValueError, match="mode"):
        crud.add_market_data(
            session,
            run_id=run.id,
            mode="SIMULATED",  # not a real value
            symbol="EURUSD",
            source="demo_fixture",
            status="success",
            price=1.0921,
        )

    reloaded = crud.get_run(session, run.id)
    assert reloaded.market_data == []


def test_check_constraint_rejects_an_out_of_set_market_data_mode(session):
    """Milestone 10.5 fix 3, database-level check: bypassing crud.py
    entirely, the CHECK constraint on MarketData.mode still refuses an
    out-of-set value."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    bad_data = models.MarketData(
        run_id=run.id,
        mode="SIMULATED",  # not a real value
        symbol="EURUSD",
        source="demo_fixture",
        status="success",
        price=1.0921,
    )
    session.add(bad_data)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_save_agent_analysis(session):
    """Milestone 10.5 fix 2: a SUCCESS analysis stores all five
    categorical fields the evaluator scores from, not just the prose --
    they're required parameters, so a real SUCCESS row can never be
    missing them."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    analysis = crud.add_agent_analysis(
        session,
        run_id=run.id,
        analysis_text="Price is respecting the rising trendline on the 1h.",
        trend_assessment="uptrend",
        structure_assessment="higher highs and higher lows",
        setup_assessment="pullback to support",
        uncertainty="medium",
        trend_direction="UP",
        trend_quality="STRONG",
        structure_quality="CLEAN",
        setup_quality="ACCEPTABLE",
        context_risk="LOW",
    )

    assert analysis.run_id == run.id
    assert analysis.trend_assessment == "uptrend"
    assert analysis.status == "SUCCESS"
    assert analysis.error_message is None
    assert analysis.trend_direction == "UP"
    assert analysis.trend_quality == "STRONG"
    assert analysis.structure_quality == "CLEAN"
    assert analysis.setup_quality == "ACCEPTABLE"
    assert analysis.context_risk == "LOW"


def test_save_agent_analysis_categorical_fields_round_trip(session):
    """The five categorical fields survive a real commit + refresh cycle
    unchanged -- not just held in the Python object before it's saved."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    crud.add_agent_analysis(
        session,
        run_id=run.id,
        analysis_text="Choppy, no clean structure.",
        trend_assessment="sideways",
        structure_assessment="overlapping candles",
        setup_assessment="no clear entry",
        uncertainty="high",
        trend_direction="SIDEWAYS",
        trend_quality="WEAK",
        structure_quality="CHOPPY",
        setup_quality="NONE",
        context_risk="ELEVATED",
    )

    reloaded = crud.get_run(session, run.id)
    stored = reloaded.analyses[0]
    assert stored.trend_direction == "SIDEWAYS"
    assert stored.trend_quality == "WEAK"
    assert stored.structure_quality == "CHOPPY"
    assert stored.setup_quality == "NONE"
    assert stored.context_risk == "ELEVATED"


def test_add_agent_analysis_rejects_an_out_of_set_categorical_value(session):
    """Milestone 10.5 fix 2, application-level check: an out-of-set
    categorical value is rejected before anything is written -- the same
    values agents/trade_agent.py's own validation already rejects, caught
    a second time at the write boundary."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    with pytest.raises(ValueError, match="trend_direction"):
        crud.add_agent_analysis(
            session,
            run_id=run.id,
            analysis_text="x",
            trend_assessment="x",
            structure_assessment="x",
            setup_assessment="x",
            uncertainty="medium",
            trend_direction="DIAGONAL",  # not a real value
            trend_quality="STRONG",
            structure_quality="CLEAN",
            setup_quality="ACCEPTABLE",
            context_risk="LOW",
        )

    # Nothing was written -- the rejected attempt left no row behind.
    reloaded = crud.get_run(session, run.id)
    assert reloaded.analyses == []


def test_check_constraint_rejects_an_out_of_set_categorical_value(session):
    """Milestone 10.5 fix 2, database-level check: even bypassing
    crud.py entirely and constructing AgentAnalysis directly, the CHECK
    constraint on each categorical column refuses an out-of-set value --
    the backstop for the case where some future code doesn't go through
    add_agent_analysis()."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    bad_analysis = models.AgentAnalysis(
        run_id=run.id,
        status="SUCCESS",
        analysis_text="x",
        trend_assessment="x",
        structure_assessment="x",
        setup_assessment="x",
        uncertainty="MEDIUM",
        trend_direction="DIAGONAL",  # not a real value
        trend_quality="STRONG",
        structure_quality="CLEAN",
        setup_quality="ACCEPTABLE",
        context_risk="LOW",
    )
    session.add(bad_analysis)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_agent_categorical_allowed_values_match_the_agent_layer():
    """Drift guard: database.models.AGENT_CATEGORICAL_FIELDS is
    duplicated from agents.trade_agent.CATEGORICAL_FIELDS on purpose (so
    database/ stays a leaf module with no dependency on the agent layer)
    -- this test is what keeps the two from silently diverging."""
    from agents.trade_agent import CATEGORICAL_FIELDS
    from database.models import AGENT_CATEGORICAL_FIELDS

    assert {k: set(v) for k, v in AGENT_CATEGORICAL_FIELDS.items()} == CATEGORICAL_FIELDS


def test_save_failed_agent_analysis_stores_status_and_error_with_null_fields(session):
    """Milestone 10.5 fix: a failed analysis is a real row, not just an
    audit_events entry -- status FAILED, the real reason, and every
    qualitative field null (never a fabricated placeholder), including
    the five categorical fields (Milestone 10.5 fix 2)."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    analysis = crud.add_failed_agent_analysis(
        session,
        run_id=run.id,
        error_message="Claude's response could not be used: malformed JSON",
    )

    assert analysis.run_id == run.id
    assert analysis.status == "FAILED"
    assert analysis.error_message == "Claude's response could not be used: malformed JSON"
    assert analysis.analysis_text is None
    assert analysis.trend_assessment is None
    assert analysis.structure_assessment is None
    assert analysis.setup_assessment is None
    assert analysis.uncertainty is None
    assert analysis.trend_direction is None
    assert analysis.trend_quality is None
    assert analysis.structure_quality is None
    assert analysis.setup_quality is None
    assert analysis.context_risk is None


def test_save_evaluation_computes_total_score(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    evaluation = crud.add_evaluation(
        session,
        run_id=run.id,
        trend_score=18,
        structure_score=15,
        entry_score=12,
        risk_reward_score=20,
        timing_context_score=10,
        risk_reward_ratio=2.0,
    )

    assert evaluation.total_score == 18 + 15 + 12 + 20 + 10
    assert evaluation.status == "SUCCESS"
    assert evaluation.error_message is None
    assert evaluation.risk_reward_ratio == 2.0


def test_save_evaluation_risk_reward_ratio_round_trips(session):
    """Milestone 10.5 fix 3: the stored ratio matches exactly what the
    evaluator computed, surviving a real commit + refresh cycle."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    crud.add_evaluation(
        session,
        run_id=run.id,
        trend_score=20,
        structure_score=20,
        entry_score=20,
        risk_reward_score=20,
        timing_context_score=20,
        risk_reward_ratio=2.5,
    )

    reloaded = crud.get_run(session, run.id)
    assert reloaded.evaluations[0].risk_reward_ratio == 2.5


def test_save_failed_evaluation_stores_status_and_error_with_null_scores_not_zeros(session):
    """Milestone 10.5 fix: a failed evaluation is a real row, not just an
    audit_events entry -- status FAILED, the real reason, and every score
    column NULL. Specifically not zero: zero is a real, meaningful score,
    and storing it here would be indistinguishable from a genuine
    all-zero evaluation."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    evaluation = crud.add_failed_evaluation(
        session,
        run_id=run.id,
        error_message="Cannot compute risk/reward: missing trade parameter(s): entry, stop, target",
    )

    assert evaluation.run_id == run.id
    assert evaluation.status == "FAILED"
    assert evaluation.error_message == (
        "Cannot compute risk/reward: missing trade parameter(s): entry, stop, target"
    )
    assert evaluation.trend_score is None
    assert evaluation.structure_score is None
    assert evaluation.entry_score is None
    assert evaluation.risk_reward_score is None
    assert evaluation.timing_context_score is None
    assert evaluation.total_score is None
    assert evaluation.risk_reward_ratio is None


def test_add_evaluation_has_no_total_score_parameter():
    """
    This is what actually enforces "the AI must not write the final
    score" at the function level: there is no parameter to pass one in
    through, so attempting to costs a TypeError before anything is saved.
    """
    params = inspect.signature(crud.add_evaluation).parameters

    assert "total_score" not in params


def test_add_evaluation_rejects_a_smuggled_total_score(session):
    """Directly proves the boundary: passing total_score into
    add_evaluation() is rejected outright (Python raises before any SQL
    runs), and a legitimately-saved evaluation's total always equals the
    sum of its five components."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    with pytest.raises(TypeError):
        crud.add_evaluation(
            session,
            run_id=run.id,
            trend_score=18,
            structure_score=15,
            entry_score=12,
            risk_reward_score=20,
            timing_context_score=10,
            risk_reward_ratio=2.0,
            total_score=999,  # not a real parameter -- must be rejected
        )

    evaluation = crud.add_evaluation(
        session,
        run_id=run.id,
        trend_score=18,
        structure_score=15,
        entry_score=12,
        risk_reward_score=20,
        timing_context_score=10,
        risk_reward_ratio=2.0,
    )

    assert evaluation.total_score == 18 + 15 + 12 + 20 + 10


def test_evaluation_check_constraint_rejects_mismatched_total_score(session):
    """
    Even bypassing crud.py entirely and constructing the Evaluation model
    directly, the database itself refuses to store a total_score that
    doesn't match the sum of the five components. This is the backstop
    for the case where some future code (not crud.add_evaluation) ends up
    building an Evaluation row by hand.
    """
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    bad_evaluation = models.Evaluation(
        run_id=run.id,
        trend_score=1,
        structure_score=1,
        entry_score=1,
        risk_reward_score=1,
        timing_context_score=1,
        total_score=9999,
    )
    session.add(bad_evaluation)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_check_constraint_rejects_a_success_row_with_mismatched_total(session):
    """Milestone 10.5 fix: proves the adapted CHECK constraint still
    enforces the original Milestone 3 rule for SUCCESS rows specifically
    -- status is set explicitly here (unlike the older test above, which
    leaves it unset and would fail on the NOT NULL constraint alone) so
    this is unambiguously testing the total-equals-sum-of-components half
    of the constraint, not just any IntegrityError."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    bad_evaluation = models.Evaluation(
        run_id=run.id,
        status="SUCCESS",
        trend_score=1,
        structure_score=1,
        entry_score=1,
        risk_reward_score=1,
        timing_context_score=1,
        total_score=9999,
    )
    session.add(bad_evaluation)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_check_constraint_permits_a_failed_row_with_all_null_scores(session):
    """The other half of the same constraint: a FAILED row with every
    score column (including total_score) null is a valid row -- this is
    what makes it possible to store a failed evaluation at all."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    failed_evaluation = models.Evaluation(
        run_id=run.id,
        status="FAILED",
        trend_score=None,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        error_message="no successful agent analysis to score",
    )
    session.add(failed_evaluation)
    session.commit()  # must not raise

    session.refresh(failed_evaluation)
    assert failed_evaluation.status == "FAILED"
    assert failed_evaluation.total_score is None


def test_check_constraint_rejects_a_failed_row_with_a_non_null_score(session):
    """Guards the other direction too: a FAILED row is not allowed to
    carry a real score on any component -- a half-failed, half-scored row
    would be exactly the ambiguous state this whole fix exists to rule
    out."""
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    inconsistent_evaluation = models.Evaluation(
        run_id=run.id,
        status="FAILED",
        trend_score=0,
        structure_score=None,
        entry_score=None,
        risk_reward_score=None,
        timing_context_score=None,
        total_score=None,
        error_message="should be rejected",
    )
    session.add(inconsistent_evaluation)

    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()


def test_save_guardrail_result(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    result = crud.add_guardrail_result(
        session,
        run_id=run.id,
        guardrail_name="risk_reward_minimum",
        passed=False,
        reason="RR of 1.2 is below the 1.5 minimum",
    )

    assert result.passed is False
    assert "1.5 minimum" in result.reason


def test_save_human_review(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    review = crud.add_human_review(
        session,
        run_id=run.id,
        decision="approved",
        comment="Setup looks clean, structure confirms trend.",
    )

    assert review.decision == "approved"
    assert review.run_id == run.id


def test_save_audit_event(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    event = crud.add_audit_event(
        session,
        run_id=run.id,
        event_type="run_created",
        event_message="Run created for EURUSD 1h",
    )

    assert event.event_type == "run_created"
    assert event.run_id == run.id


def test_run_relationships_reach_all_child_records(session):
    """
    A full run should let you walk from the Run to every child row — that
    is what makes the audit trail actually usable, not just stored.
    """
    run = crud.create_run(session, symbol="GBPUSD", timeframe="4h")
    crud.add_capture(
        session,
        run_id=run.id,
        capture_mode="demo",
        symbol="GBPUSD",
        timeframe="4h",
        status="success",
        screenshot_path="screenshots/demo/gbpusd_4h.png",
    )
    crud.add_market_data(
        session,
        run_id=run.id,
        mode="DEMO",
        symbol="GBPUSD",
        source="demo_fixture",
        status="success",
        price=1.27,
    )
    crud.add_agent_analysis(
        session,
        run_id=run.id,
        analysis_text="Ranging price action, no clear trend.",
        trend_assessment="range",
        structure_assessment="equal highs and lows",
        setup_assessment="no clear setup",
        uncertainty="high",
        trend_direction="SIDEWAYS",
        trend_quality="WEAK",
        structure_quality="MIXED",
        setup_quality="NONE",
        context_risk="MODERATE",
    )
    crud.add_evaluation(
        session,
        run_id=run.id,
        trend_score=10,
        structure_score=10,
        entry_score=10,
        risk_reward_score=10,
        timing_context_score=10,
        risk_reward_ratio=1.5,
    )
    crud.add_guardrail_result(
        session, run_id=run.id, guardrail_name="data_freshness", passed=True
    )
    crud.add_human_review(session, run_id=run.id, decision="rejected")
    crud.add_audit_event(
        session, run_id=run.id, event_type="run_completed", event_message="done"
    )

    session.refresh(run)

    assert len(run.captures) == 1
    assert len(run.market_data) == 1
    assert len(run.analyses) == 1
    assert len(run.evaluations) == 1
    assert len(run.guardrail_results) == 1
    assert run.human_review is not None
    assert len(run.audit_events) == 1
