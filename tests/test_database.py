# TradePilot AI — tests for the database layer (Milestone 3).
#
# Every test here builds its own in-memory SQLite database, so running
# these never touches the real database/tradepilot.db file on disk.

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect
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


def test_save_market_data(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        symbol="EURUSD",
        source="demo_fixture",
        status="success",
        price=1.0921,
    )

    assert data.run_id == run.id
    assert data.price == 1.0921
    assert data.status == "success"


def test_save_market_data_failure_records_error(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    data = crud.add_market_data(
        session,
        run_id=run.id,
        symbol="EURUSD",
        source="demo_fixture",
        status="error",
        error_message="No price available for this symbol",
    )

    assert data.status == "error"
    assert data.price is None


def test_save_agent_analysis(session):
    run = crud.create_run(session, symbol="EURUSD", timeframe="1h")

    analysis = crud.add_agent_analysis(
        session,
        run_id=run.id,
        analysis_text="Price is respecting the rising trendline on the 1h.",
        trend_assessment="uptrend",
        structure_assessment="higher highs and higher lows",
        setup_assessment="pullback to support",
        uncertainty="medium",
    )

    assert analysis.run_id == run.id
    assert analysis.trend_assessment == "uptrend"


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
    )

    assert evaluation.total_score == 18 + 15 + 12 + 20 + 10


def test_add_evaluation_has_no_total_score_parameter():
    """
    This is what actually enforces "the AI must not write the final
    score": there is no parameter to pass one in through.
    """
    params = inspect.signature(crud.add_evaluation).parameters

    assert "total_score" not in params


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
    )
    crud.add_evaluation(
        session,
        run_id=run.id,
        trend_score=10,
        structure_score=10,
        entry_score=10,
        risk_reward_score=10,
        timing_context_score=10,
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
