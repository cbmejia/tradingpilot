# TradePilot AI — Milestone 12: one automated test per documented failure
# scenario in docs/failure_modes.md, run through the real API (real
# DemoProvider/DemoMarketDataProvider fixtures, real orchestrator, real
# guardrails) so these are genuine end-to-end proofs, not isolated unit
# tests with hand-built fixtures. The only thing ever synthetic is the
# agent's output, via force_scenario -- and even then, every score is
# still computed for real by evals/trade_evaluator.py from that input.
#
# force_scenario is gated behind TESTING_CONTROLS_ENABLED (off by
# default in real use); every test here explicitly turns it on via
# monkeypatch, scoped to the test, so the gate itself gets exercised too
# (see test_force_scenario_refused_when_testing_controls_disabled).

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import config
from backend.main import app
from database import models  # noqa: F401 -- registers tables on Base.metadata
from database.database import Base, get_session


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTURE_MODE", "DEMO")
    monkeypatch.setenv("MARKET_DATA_MODE", "DEMO")
    monkeypatch.setattr(config, "TESTING_CONTROLS_ENABLED", True)

    db_path = tmp_path / "test_failure_scenarios.db"
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


GOOD_PARAMS = {
    "symbol": "EURUSD",
    "timeframe": "1h",
    "direction": "long",
    "entry": 1.0950,
    "stop": 1.0900,
    "target": 1.1050,  # RR = 2.0
}


def _create_and_analyze(client, payload=None, force_scenario=None):
    created = client.post("/runs", json=payload or GOOD_PARAMS).json()
    params = {"force_scenario": force_scenario} if force_scenario else {}
    response = client.post(f"/runs/{created['id']}/analyze", params=params)
    return created["id"], response


def _guardrail(body, name):
    return next(g for g in body["guardrail_results"] if g["guardrail_name"] == name)


# ---------------------------------------------------------------------------
# The safety gate itself
# ---------------------------------------------------------------------------


def test_force_scenario_refused_when_testing_controls_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "TESTING_CONTROLS_ENABLED", False)
    created = client.post("/runs", json=GOOD_PARAMS).json()

    response = client.post(
        f"/runs/{created['id']}/analyze", params={"force_scenario": "capture_fails"}
    )

    assert response.status_code == 403
    assert "TESTING_CONTROLS_ENABLED" in response.json()["detail"]
    # Refused before anything ran -- no pipeline results at all.
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["captures"] == []


def test_unknown_force_scenario_value_is_rejected(client):
    created = client.post("/runs", json=GOOD_PARAMS).json()

    response = client.post(
        f"/runs/{created['id']}/analyze", params={"force_scenario": "not_a_real_scenario"}
    )

    assert response.status_code == 422


def test_a_normal_analysis_without_force_scenario_is_unaffected(client):
    """The mechanism existing at all must not change ordinary behavior."""
    mock_agent = MagicMock()
    from agents.trade_agent import AgentAnalysisResult, AgentAnalysisStatus
    from datetime import datetime, timezone

    mock_agent.analyze.return_value = AgentAnalysisResult(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="Real analysis.", trend_assessment="x", structure_assessment="x", setup_assessment="x",
        uncertainty="MEDIUM", trend_direction="UP", trend_quality="STRONG", structure_quality="CLEAN",
        setup_quality="ACCEPTABLE", context_risk="LOW", timestamp=datetime.now(timezone.utc), error_message=None,
    )
    with patch("backend.orchestrator.TradeAgent", return_value=mock_agent):
        _, response = _create_and_analyze(client)

    assert response.status_code == 200
    body = response.json()
    assert body["analyses"][0]["analysis_text"] == "Real analysis."
    audit_types = [e["event_type"] for e in body["audit_events"]]
    assert "testing_scenario_forced" not in audit_types


# ---------------------------------------------------------------------------
# Scenario 1 — CAPTURE FAILS
# ---------------------------------------------------------------------------


def test_scenario_1_capture_fails(client):
    mock_agent = MagicMock()
    with patch("backend.orchestrator.TradeAgent", return_value=mock_agent):
        run_id, response = _create_and_analyze(client, force_scenario="capture_fails")

    assert response.status_code == 200
    body = response.json()

    assert body["captures"][0]["status"] == "FAILED"
    assert "TESTING" in body["captures"][0]["error_message"]
    mock_agent.analyze.assert_not_called()
    assert body["analyses"][0]["status"] == "FAILED"
    assert len(body["guardrail_results"]) == 11
    assert _guardrail(body, "CAPTURE_SUCCEEDED")["passed"] is False
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 2 — CAPTURE STALE
# ---------------------------------------------------------------------------


def test_scenario_2_capture_stale(client):
    run_id, response = _create_and_analyze(client, force_scenario="capture_stale")

    assert response.status_code == 200
    body = response.json()

    assert body["captures"][0]["status"] == "SUCCESS"  # the capture itself is real and valid
    assert _guardrail(body, "CAPTURE_SUCCEEDED")["passed"] is True
    assert _guardrail(body, "CAPTURE_FRESH")["passed"] is False
    assert "old" in _guardrail(body, "CAPTURE_FRESH")["reason"].lower()
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 3 — MARKET DATA FAILS
# ---------------------------------------------------------------------------


def test_scenario_3_market_data_fails(client):
    mock_agent = MagicMock()
    with patch("backend.orchestrator.TradeAgent", return_value=mock_agent):
        run_id, response = _create_and_analyze(client, force_scenario="market_data_fails")

    assert response.status_code == 200
    body = response.json()

    assert body["market_data"][0]["status"] == "FAILED"
    assert body["market_data"][0]["price"] is None  # never an invented price
    assert "TESTING" in body["market_data"][0]["error_message"]
    mock_agent.analyze.assert_not_called()
    assert _guardrail(body, "MARKET_DATA_SUCCEEDED")["passed"] is False
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 4 — MARKET DATA STALE
# ---------------------------------------------------------------------------


def test_scenario_4_market_data_stale(client):
    run_id, response = _create_and_analyze(client, force_scenario="market_data_stale")

    assert response.status_code == 200
    body = response.json()

    assert body["market_data"][0]["status"] == "SUCCESS"
    assert _guardrail(body, "MARKET_DATA_SUCCEEDED")["passed"] is True
    assert _guardrail(body, "MARKET_DATA_FRESH")["passed"] is False
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 5 — AGENT FAILS
# ---------------------------------------------------------------------------


def test_scenario_5_agent_fails(client):
    run_id, response = _create_and_analyze(client, force_scenario="agent_fails")

    assert response.status_code == 200
    body = response.json()

    assert body["captures"][0]["status"] == "SUCCESS"
    assert body["market_data"][0]["status"] == "SUCCESS"
    assert body["analyses"][0]["status"] == "FAILED"
    assert "TESTING" in body["analyses"][0]["error_message"]
    assert body["evaluations"][0]["status"] == "FAILED"
    assert body["evaluations"][0]["total_score"] is None  # no evaluation score at all
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 6 — RISK/REWARD BELOW MINIMUM
# ---------------------------------------------------------------------------


def test_scenario_6_risk_reward_below_minimum(client):
    bad_rr_params = {**GOOD_PARAMS, "entry": 1.0950, "stop": 1.0900, "target": 1.0960}  # RR = 0.2
    run_id, response = _create_and_analyze(
        client, payload=bad_rr_params, force_scenario="perfect_demo_score"
    )

    assert response.status_code == 200
    body = response.json()

    assert body["evaluations"][0]["status"] == "SUCCESS"
    assert body["evaluations"][0]["risk_reward_score"] == 0
    assert _guardrail(body, "RISK_REWARD_MINIMUM")["passed"] is False
    # Review-forcing, not blocking -- the pipeline worked, the setup is
    # just not good enough.
    assert body["guardrail_outcome"] == "REQUIRES_REVIEW"


# ---------------------------------------------------------------------------
# Scenario 7 — INCOHERENT TRADE PARAMS
# ---------------------------------------------------------------------------


def test_scenario_7_incoherent_trade_params(client):
    incoherent_params = {
        **GOOD_PARAMS,
        "entry": 1.0950,
        "stop": 1.1000,  # stop ABOVE entry on a LONG -- wrong side
        "target": 1.1050,
    }
    run_id, response = _create_and_analyze(
        client, payload=incoherent_params, force_scenario="perfect_demo_score"
    )

    assert response.status_code == 200
    body = response.json()

    # A FAILED evaluation, not a guessed score.
    assert body["evaluations"][0]["status"] == "FAILED"
    assert body["evaluations"][0]["total_score"] is None
    assert body["evaluations"][0]["risk_reward_score"] is None
    assert "wrong side" in body["evaluations"][0]["error_message"].lower()
    assert _guardrail(body, "TRADE_PARAMS_VALID")["passed"] is False
    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Scenario 8 — HIGH AGENT UNCERTAINTY
# ---------------------------------------------------------------------------


def test_scenario_8_high_uncertainty_can_never_reach_ready_for_review(client):
    run_id, response = _create_and_analyze(client, force_scenario="high_uncertainty")

    assert response.status_code == 200
    body = response.json()

    assert body["analyses"][0]["uncertainty"] == "HIGH"
    # Ceiling for HIGH is 52 (docs/rubric.md) even with the best
    # categories -- still nowhere near a guessed/inflated score.
    assert body["evaluations"][0]["total_score"] <= 52
    assert _guardrail(body, "UNCERTAINTY_ACCEPTABLE")["passed"] is False
    assert body["guardrail_outcome"] != "READY_FOR_REVIEW"


# ---------------------------------------------------------------------------
# Scenario 9 — DEMO RUN WITH A PERFECT SCORE
# ---------------------------------------------------------------------------


def test_scenario_9_demo_run_with_perfect_score_never_reaches_ready_for_review(client):
    run_id, response = _create_and_analyze(client, force_scenario="perfect_demo_score")

    assert response.status_code == 200
    body = response.json()

    assert body["evaluations"][0]["total_score"] == 100
    failing = {g["guardrail_name"] for g in body["guardrail_results"] if not g["passed"]}
    assert failing == {"SYNTHETIC_DATA"}
    assert body["guardrail_outcome"] == "REQUIRES_REVIEW"
    assert body["guardrail_outcome"] != "READY_FOR_REVIEW"


# ---------------------------------------------------------------------------
# Scenario 10 — APPROVING A BLOCKED RUN
# ---------------------------------------------------------------------------


def test_scenario_10_approving_a_blocked_run_is_refused(client):
    mock_agent = MagicMock()
    with patch("backend.orchestrator.TradeAgent", return_value=mock_agent):
        run_id, analyze_response = _create_and_analyze(client, force_scenario="capture_fails")
    assert analyze_response.json()["guardrail_outcome"] == "BLOCKED"

    response = client.post(f"/runs/{run_id}/review", json={"decision": "APPROVED"})

    assert response.status_code == 409
    assert "block" in response.json()["detail"].lower()
    full_run = client.get(f"/runs/{run_id}").json()
    assert full_run["human_review"] is None

    # REJECT, unlike APPROVE, is never gated.
    reject_response = client.post(f"/runs/{run_id}/review", json={"decision": "REJECTED"})
    assert reject_response.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 11 — DECIDING TWICE
# ---------------------------------------------------------------------------


def test_scenario_11_deciding_twice_is_refused_original_unchanged(client):
    run_id, _ = _create_and_analyze(client, force_scenario="perfect_demo_score")

    first = client.post(
        f"/runs/{run_id}/review", json={"decision": "REJECTED", "comment": "first decision"}
    )
    assert first.status_code == 200

    second = client.post(
        f"/runs/{run_id}/review", json={"decision": "APPROVED", "comment": "trying to change it"}
    )

    assert second.status_code == 409
    assert "final" in second.json()["detail"].lower() or "already" in second.json()["detail"].lower()

    full_run = client.get(f"/runs/{run_id}").json()
    assert full_run["human_review"]["decision"] == "REJECTED"
    assert full_run["human_review"]["comment"] == "first decision"
