# TradePilot AI — tests for the orchestrator (Milestone 10.5).
#
# The real DEMO capture and market-data providers run for real in most of
# these tests -- no network, no mocking needed (they read committed
# fixture files, same as tests/test_guardrails.py's Milestone 9 fix
# tests). CAPTURE_MODE/MARKET_DATA_MODE are pinned to DEMO via monkeypatch
# in every test that hits the real endpoint, so behavior never depends on
# whatever happens to be in a developer's local .env.
#
# The only thing ever mocked is the agent -- a real Claude call costs
# money and needs a real API key. Every test that needs to control the
# agent's output patches backend.orchestrator.TradeAgent directly, so no
# anthropic client is ever constructed and no network call is ever made.
# Two tests also patch backend.orchestrator.CaptureManager /
# MarketDataManager to force a clean, deterministic failure without
# depending on which fixture files happen to exist on disk.

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus
from backend.main import app
from capture.base import CaptureMode, CaptureResult, CaptureStatus
from database import models  # noqa: F401 -- registers tables on Base.metadata
from database.database import Base, get_session
from guardrails.rules import BLOCKING_RULES, GuardrailOutcome, REVIEW_FORCING_RULES
from tools.market_data import MarketDataMode, MarketDataStatus, MarketQuote


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTURE_MODE", "DEMO")
    monkeypatch.setenv("MARKET_DATA_MODE", "DEMO")

    db_path = tmp_path / "test_orchestrator.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_session():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


ALL_GUARDRAIL_NAMES = BLOCKING_RULES | REVIEW_FORCING_RULES

GOOD_RUN_PAYLOAD = {
    "symbol": "EURUSD",
    "timeframe": "1h",
    "direction": "long",
    "entry": 1.0950,
    "stop": 1.0900,
    "target": 1.1050,
}


def _good_agent_result(**overrides) -> AgentAnalysisResult:
    defaults = dict(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="Clean pullback into a rising trendline.",
        trend_assessment="uptrend",
        structure_assessment="higher highs and higher lows",
        setup_assessment="pullback holding the trendline, not yet confirmed",
        uncertainty="MEDIUM",
        trend_direction="UP",
        trend_quality="STRONG",
        structure_quality="CLEAN",
        setup_quality="ACCEPTABLE",
        context_risk="LOW",
        timestamp=datetime.now(timezone.utc),
        error_message=None,
    )
    defaults.update(overrides)
    return AgentAnalysisResult(**defaults)


def _failed_agent_result(message="Claude's response could not be used: malformed JSON") -> AgentAnalysisResult:
    return AgentAnalysisResult(
        status=AgentAnalysisStatus.FAILED,
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
        timestamp=None,
        error_message=message,
    )


def _failed_capture(message="Chart element never appeared.") -> CaptureResult:
    return CaptureResult(
        mode=CaptureMode.DEMO,
        symbol="EURUSD",
        timeframe="1h",
        screenshot_path=None,
        captured_at=None,
        status=CaptureStatus.FAILED,
        error_message=message,
    )


def _failed_market_data(message="No demo quote for EURUSD.") -> MarketQuote:
    return MarketQuote(
        mode=MarketDataMode.DEMO,
        symbol="EURUSD",
        price=None,
        timestamp=None,
        source="demo_fixture",
        status=MarketDataStatus.FAILED,
        error_message=message,
    )


def _patched_agent(result: AgentAnalysisResult):
    mock_agent = MagicMock()
    mock_agent.analyze.return_value = result
    return patch("backend.orchestrator.TradeAgent", return_value=mock_agent)


def _patched_capture_manager(result: CaptureResult):
    mock_manager = MagicMock()
    mock_manager.capture.return_value = result
    return patch("backend.orchestrator.CaptureManager", return_value=mock_manager)


def _patched_market_data_manager(result: MarketQuote):
    mock_manager = MagicMock()
    mock_manager.get_quote.return_value = result
    return patch("backend.orchestrator.MarketDataManager", return_value=mock_manager)


# ---------------------------------------------------------------------------
# A full, real DEMO run
# ---------------------------------------------------------------------------


def test_full_demo_run_reaches_requires_review_with_synthetic_data_the_only_failure(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    assert body["guardrail_outcome"] == "REQUIRES_REVIEW"
    assert body["status"] == "REQUIRES_REVIEW"

    failing_rules = {g["guardrail_name"] for g in body["guardrail_results"] if not g["passed"]}
    assert failing_rules == {"SYNTHETIC_DATA"}
    assert len(body["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)


# ---------------------------------------------------------------------------
# Every stage's results are persisted and readable via GET /runs/{id}
# ---------------------------------------------------------------------------


def test_every_stage_result_is_persisted_and_readable_via_get_run(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):
        client.post(f"/runs/{created['id']}/analyze")

    full_run = client.get(f"/runs/{created['id']}").json()

    assert len(full_run["captures"]) == 1
    assert full_run["captures"][0]["status"] == "SUCCESS"
    assert full_run["captures"][0]["capture_mode"] == "DEMO"
    assert full_run["captures"][0]["screenshot_path"] is not None

    assert len(full_run["market_data"]) == 1
    assert full_run["market_data"][0]["status"] == "SUCCESS"
    assert full_run["market_data"][0]["price"] == 1.0921
    assert full_run["market_data"][0]["source"] == "demo_fixture"

    assert len(full_run["analyses"]) == 1
    assert full_run["analyses"][0]["uncertainty"] == "MEDIUM"
    assert full_run["analyses"][0]["analysis_text"]

    assert len(full_run["evaluations"]) == 1
    # MEDIUM uncertainty caps each subjective component at 14; RR = 2.0
    # (entry 1.0950/stop 1.0900/target 1.1050) scores the full 20 --
    # matches docs/rubric.md's worked example: 76 total.
    assert full_run["evaluations"][0]["total_score"] == 76
    assert full_run["evaluations"][0]["risk_reward_score"] == 20

    assert len(full_run["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)
    assert full_run["completed_at"] is not None


# ---------------------------------------------------------------------------
# A failed capture
# ---------------------------------------------------------------------------


def test_failed_capture_stops_pipeline_does_not_call_agent_but_guardrails_still_run(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    mock_agent = MagicMock()
    with _patched_capture_manager(_failed_capture()), patch(
        "backend.orchestrator.TradeAgent", return_value=mock_agent
    ):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    mock_agent.analyze.assert_not_called()

    assert body["captures"][0]["status"] == "FAILED"
    assert body["captures"][0]["error_message"] == "Chart element never appeared."
    assert body["analyses"] == []
    assert body["evaluations"] == []

    assert len(body["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)
    capture_check = next(g for g in body["guardrail_results"] if g["guardrail_name"] == "CAPTURE_SUCCEEDED")
    assert capture_check["passed"] is False

    assert body["guardrail_outcome"] == "BLOCKED"
    assert body["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# A failed market data fetch
# ---------------------------------------------------------------------------


def test_failed_market_data_stops_pipeline_does_not_call_agent_but_guardrails_still_run(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    mock_agent = MagicMock()
    with _patched_market_data_manager(_failed_market_data()), patch(
        "backend.orchestrator.TradeAgent", return_value=mock_agent
    ):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    mock_agent.analyze.assert_not_called()

    assert body["market_data"][0]["status"] == "FAILED"
    assert body["market_data"][0]["error_message"] == "No demo quote for EURUSD."
    assert body["analyses"] == []
    assert body["evaluations"] == []

    assert len(body["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)
    market_check = next(
        g for g in body["guardrail_results"] if g["guardrail_name"] == "MARKET_DATA_SUCCEEDED"
    )
    assert market_check["passed"] is False

    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# A failed agent analysis
# ---------------------------------------------------------------------------


def test_failed_agent_analysis_is_recorded_and_not_evaluated(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_failed_agent_result("Claude's response could not be used: malformed JSON")):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    # Capture and market data both succeeded (real DEMO providers), but
    # there is no structured analysis row -- the agent_analyses table has
    # no way to store a failure (see backend/orchestrator.py's module
    # docstring) -- the failure is recorded in the audit trail instead.
    assert body["captures"][0]["status"] == "SUCCESS"
    assert body["market_data"][0]["status"] == "SUCCESS"
    assert body["analyses"] == []
    assert body["evaluations"] == []

    audit_messages = " ".join(e["event_message"] for e in body["audit_events"])
    assert "malformed JSON" in audit_messages

    analysis_check = next(g for g in body["guardrail_results"] if g["guardrail_name"] == "ANALYSIS_SUCCEEDED")
    assert analysis_check["passed"] is False
    evaluation_check = next(
        g for g in body["guardrail_results"] if g["guardrail_name"] == "EVALUATION_SUCCEEDED"
    )
    assert evaluation_check["passed"] is False

    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Audit event ordering
# ---------------------------------------------------------------------------


def test_audit_events_appear_in_the_correct_order(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):
        client.post(f"/runs/{created['id']}/analyze")

    full_run = client.get(f"/runs/{created['id']}").json()
    event_types = [e["event_type"] for e in full_run["audit_events"]]

    assert event_types == [
        "run_created",
        "analysis_started",
        "capture_started",
        "capture_finished",
        "market_data_started",
        "market_data_finished",
        "agent_analysis_started",
        "agent_analysis_finished",
        "evaluation_started",
        "evaluation_finished",
        "guardrails_started",
        "guardrails_finished",
        "analysis_finished",
    ]


def test_audit_events_appear_in_order_when_capture_fails(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_capture_manager(_failed_capture()), patch(
        "backend.orchestrator.TradeAgent", return_value=MagicMock()
    ):
        client.post(f"/runs/{created['id']}/analyze")

    full_run = client.get(f"/runs/{created['id']}").json()
    event_types = [e["event_type"] for e in full_run["audit_events"]]

    assert event_types == [
        "run_created",
        "analysis_started",
        "capture_started",
        "capture_finished",
        "market_data_started",
        "market_data_finished",
        "agent_analysis_skipped",
        "evaluation_skipped",
        "guardrails_started",
        "guardrails_finished",
        "analysis_finished",
    ]


# ---------------------------------------------------------------------------
# Analyzing twice
# ---------------------------------------------------------------------------


def test_analyzing_an_already_analyzed_run_is_refused_and_original_results_unchanged(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):
        first = client.post(f"/runs/{created['id']}/analyze")
    assert first.status_code == 200
    first_body = first.json()

    with _patched_agent(_good_agent_result(uncertainty="LOW")):
        second = client.post(f"/runs/{created['id']}/analyze")

    assert second.status_code == 409
    assert "already been analyzed" in second.json()["detail"].lower()

    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["evaluations"] == first_body["evaluations"]
    assert full_run["analyses"] == first_body["analyses"]
    assert len(full_run["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)

    # The refused second attempt wrote nothing new to the audit trail.
    finished_events = [e for e in full_run["audit_events"] if e["event_type"] == "analysis_finished"]
    assert len(finished_events) == 1


def test_analyzing_a_nonexistent_run_returns_404(client):
    response = client.post("/runs/does-not-exist/analyze")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# No code path produces an approved state
# ---------------------------------------------------------------------------


def test_no_code_path_produces_an_approved_state(client):
    assert {o.value for o in GuardrailOutcome} == {"BLOCKED", "REQUIRES_REVIEW", "READY_FOR_REVIEW"}

    with _patched_agent(_good_agent_result()):
        response = client.post(
            f"/runs/{client.post('/runs', json=GOOD_RUN_PAYLOAD).json()['id']}/analyze"
        )

    body = response.json()
    assert body["status"] in ("BLOCKED", "REQUIRES_REVIEW", "READY_FOR_REVIEW")
    assert body["human_review"] is None
