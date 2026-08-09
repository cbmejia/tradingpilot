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
        proposal_has_proposal=False,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
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
        proposal_has_proposal=None,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
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
    # Milestone 10.5 fix 3: mode is stored directly, not just inferable
    # from `source`.
    assert full_run["market_data"][0]["mode"] == "DEMO"

    assert len(full_run["analyses"]) == 1
    analysis = full_run["analyses"][0]
    assert analysis["status"] == "SUCCESS"
    assert analysis["error_message"] is None
    assert analysis["uncertainty"] == "MEDIUM"
    assert analysis["analysis_text"]
    # Milestone 10.5 fix 2: the categorical fields the evaluator actually
    # scored from are on the record itself -- a Trend score of 14 (below)
    # can be traced back to trend_direction=UP + trend_quality=STRONG.
    assert analysis["trend_direction"] == "UP"
    assert analysis["trend_quality"] == "STRONG"
    assert analysis["structure_quality"] == "CLEAN"
    assert analysis["setup_quality"] == "ACCEPTABLE"
    assert analysis["context_risk"] == "LOW"

    assert len(full_run["evaluations"]) == 1
    assert full_run["evaluations"][0]["status"] == "SUCCESS"
    assert full_run["evaluations"][0]["error_message"] is None
    # MEDIUM uncertainty caps each subjective component at 14; RR = 2.0
    # (entry 1.0950/stop 1.0900/target 1.1050) scores the full 20 --
    # matches docs/rubric.md's worked example: 76 total.
    assert full_run["evaluations"][0]["total_score"] == 76
    assert full_run["evaluations"][0]["risk_reward_score"] == 20
    # Milestone 10.5 fix 3: the raw ratio behind that banded 20 is on the
    # record too -- risk_reward_score=20 traces back to ratio=2.0.
    assert full_run["evaluations"][0]["risk_reward_ratio"] == pytest.approx(2.0)

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

    # Milestone 10.5 fix: even though the agent was never called, a
    # FAILED AgentAnalysis/Evaluation row is still stored -- one row each,
    # never zero rows -- so the failure is visible on the record itself.
    assert len(body["analyses"]) == 1
    assert body["analyses"][0]["status"] == "FAILED"
    assert body["analyses"][0]["error_message"] is not None
    assert body["analyses"][0]["analysis_text"] is None
    assert body["analyses"][0]["uncertainty"] is None

    assert len(body["evaluations"]) == 1
    assert body["evaluations"][0]["status"] == "FAILED"
    assert body["evaluations"][0]["error_message"] is not None
    assert body["evaluations"][0]["total_score"] is None

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

    assert len(body["analyses"]) == 1
    assert body["analyses"][0]["status"] == "FAILED"

    assert len(body["evaluations"]) == 1
    assert body["evaluations"][0]["status"] == "FAILED"

    assert len(body["guardrail_results"]) == len(ALL_GUARDRAIL_NAMES)
    market_check = next(
        g for g in body["guardrail_results"] if g["guardrail_name"] == "MARKET_DATA_SUCCEEDED"
    )
    assert market_check["passed"] is False

    assert body["guardrail_outcome"] == "BLOCKED"


# ---------------------------------------------------------------------------
# A failed agent analysis
# ---------------------------------------------------------------------------


def test_failed_agent_analysis_is_recorded_as_a_row_and_not_evaluated(client):
    """Milestone 10.5 fix: a failed agent analysis is now stored as a real
    AgentAnalysis row -- status FAILED, the real error message, and every
    qualitative field null (never a fabricated placeholder). evaluate()
    is still never called (nothing to score), and the resulting
    Evaluation row is itself a FAILED row too, not an empty list."""
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_failed_agent_result("Claude's response could not be used: malformed JSON")):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    assert body["captures"][0]["status"] == "SUCCESS"
    assert body["market_data"][0]["status"] == "SUCCESS"

    # The failure is on the record itself -- GET /runs/{id} doesn't
    # require parsing audit_events to know this analysis failed.
    assert len(body["analyses"]) == 1
    analysis = body["analyses"][0]
    assert analysis["status"] == "FAILED"
    assert analysis["error_message"] == "Claude's response could not be used: malformed JSON"
    assert analysis["analysis_text"] is None
    assert analysis["trend_assessment"] is None
    assert analysis["structure_assessment"] is None
    assert analysis["setup_assessment"] is None
    assert analysis["uncertainty"] is None
    assert analysis["trend_direction"] is None
    assert analysis["trend_quality"] is None
    assert analysis["structure_quality"] is None
    assert analysis["setup_quality"] is None
    assert analysis["context_risk"] is None

    # Not evaluated -- but still recorded as a FAILED row, not an absence.
    assert len(body["evaluations"]) == 1
    evaluation = body["evaluations"][0]
    assert evaluation["status"] == "FAILED"
    assert evaluation["error_message"] is not None
    assert evaluation["trend_score"] is None
    assert evaluation["structure_score"] is None
    assert evaluation["entry_score"] is None
    assert evaluation["risk_reward_score"] is None
    assert evaluation["timing_context_score"] is None
    assert evaluation["total_score"] is None
    assert evaluation["risk_reward_ratio"] is None

    # The audit trail still describes it too -- both are kept.
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
# 7A Iteration 1 -- agent-proposed trade levels, never self-scored.
# Coherence is computed once, in the orchestrator, by reusing
# evals.trade_evaluator.compute_risk_reward() -- the same function
# guardrails/rules.py already reuses for the run's own trade params.
# ---------------------------------------------------------------------------


def test_agent_proposing_coherent_levels_is_recorded_and_does_not_affect_scoring(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    proposing_agent = _good_agent_result(
        proposal_has_proposal=True,
        proposal_direction="LONG",
        proposal_entry=1.1000,
        proposal_stop=1.0950,
        proposal_target=1.1100,
    )
    with _patched_agent(proposing_agent):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    proposal = body["proposal"]
    assert proposal["has_proposal"] is True
    assert proposal["direction"] == "LONG"
    assert proposal["entry"] == 1.1000
    assert proposal["stop"] == 1.0950
    assert proposal["target"] == 1.1100
    assert proposal["is_coherent"] is True
    assert proposal["risk_reward_ratio"] == pytest.approx(2.0)
    assert proposal["coherence_error"] is None

    # The proposal never touches this run's own evaluation -- identical
    # total_score (76) to the non-proposal happy path in
    # test_every_stage_result_is_persisted_and_readable_via_get_run above,
    # computed from GOOD_RUN_PAYLOAD's own entry/stop/target, not the
    # proposal's.
    assert body["evaluations"][0]["total_score"] == 76
    assert body["evaluations"][0]["risk_reward_ratio"] == pytest.approx(2.0)

    # Nor this run's own guardrails -- TRADE_PARAMS_VALID reads the run's
    # OWN trade params, never the proposal.
    trade_params_check = next(
        g for g in body["guardrail_results"] if g["guardrail_name"] == "TRADE_PARAMS_VALID"
    )
    assert trade_params_check["passed"] is True


def test_agent_proposing_incoherent_levels_is_recorded_with_a_reason(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    proposing_agent = _good_agent_result(
        proposal_has_proposal=True,
        proposal_direction="LONG",
        proposal_entry=1.0950,
        proposal_stop=1.1000,  # stop above entry on a LONG -- incoherent
        proposal_target=1.1050,
    )
    with _patched_agent(proposing_agent):
        response = client.post(f"/runs/{created['id']}/analyze")

    assert response.status_code == 200
    body = response.json()

    proposal = body["proposal"]
    assert proposal["has_proposal"] is True
    assert proposal["is_coherent"] is False
    assert proposal["risk_reward_ratio"] is None
    assert "wrong side" in proposal["coherence_error"]

    # Still doesn't affect this run's own (coherent) evaluation/guardrails.
    assert body["evaluations"][0]["total_score"] == 76
    trade_params_check = next(
        g for g in body["guardrail_results"] if g["guardrail_name"] == "TRADE_PARAMS_VALID"
    )
    assert trade_params_check["passed"] is True


def test_agent_declining_a_proposal_is_recorded(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):  # declines by default
        response = client.post(f"/runs/{created['id']}/analyze")

    body = response.json()
    assert body["proposal"]["has_proposal"] is False
    assert body["proposal"]["direction"] is None
    assert body["proposal"]["risk_reward_ratio"] is None
    assert body["proposal"]["is_coherent"] is None


def test_agent_analysis_finished_audit_event_mentions_the_proposal_outcome(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    with _patched_agent(_good_agent_result()):
        client.post(f"/runs/{created['id']}/analyze")

    full_run = client.get(f"/runs/{created['id']}").json()
    finished_event = next(
        e for e in full_run["audit_events"] if e["event_type"] == "agent_analysis_finished"
    )
    assert "declined" in finished_event["event_message"].lower()


# ---------------------------------------------------------------------------
# 7A Iteration 1 -- POST /runs/{run_id}/accept-proposal
# ---------------------------------------------------------------------------


def test_accept_proposal_creates_a_new_run_with_provenance(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()
    proposing_agent = _good_agent_result(
        proposal_has_proposal=True,
        proposal_direction="LONG",
        proposal_entry=1.1000,
        proposal_stop=1.0950,
        proposal_target=1.1100,
    )
    with _patched_agent(proposing_agent):
        client.post(f"/runs/{created['id']}/analyze")

    response = client.post(f"/runs/{created['id']}/accept-proposal")

    assert response.status_code == 201
    body = response.json()
    assert body["id"] != created["id"]
    assert body["accepted_from_run_id"] == created["id"]
    assert body["symbol"] == "EURUSD"
    assert body["timeframe"] == "1h"
    assert body["direction"] == "LONG"
    assert body["entry"] == 1.1000
    assert body["stop"] == 1.0950
    assert body["target"] == 1.1100
    assert body["status"] == "CREATED"

    new_run = client.get(f"/runs/{body['id']}").json()
    assert new_run["accepted_from_run_id"] == created["id"]
    assert new_run["entry"] == 1.1000
    new_run_event_types = [e["event_type"] for e in new_run["audit_events"]]
    assert "accepted_from_proposal" in new_run_event_types

    source_run = client.get(f"/runs/{created['id']}").json()
    source_event_types = [e["event_type"] for e in source_run["audit_events"]]
    assert "proposal_accepted" in source_event_types
    # Accepting a proposal never rescores or reruns the source run -- its
    # own evaluation is exactly what it was before accepting.
    assert source_run["evaluations"][0]["total_score"] == 76


def test_accept_proposal_can_accept_an_incoherent_proposal(client):
    """Accepting doesn't imply endorsing the math -- an incoherent
    proposal can still be accepted, exactly as a human could type in bad
    numbers themselves; the new run just carries those same numbers and
    will fail TRADE_PARAMS_VALID once analyzed."""
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()
    proposing_agent = _good_agent_result(
        proposal_has_proposal=True,
        proposal_direction="LONG",
        proposal_entry=1.0950,
        proposal_stop=1.1000,  # incoherent
        proposal_target=1.1050,
    )
    with _patched_agent(proposing_agent):
        client.post(f"/runs/{created['id']}/analyze")

    response = client.post(f"/runs/{created['id']}/accept-proposal")

    assert response.status_code == 201
    assert response.json()["stop"] == 1.1000


def test_accept_proposal_on_a_declined_run_is_refused(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()
    with _patched_agent(_good_agent_result()):  # declines by default
        client.post(f"/runs/{created['id']}/analyze")

    response = client.post(f"/runs/{created['id']}/accept-proposal")

    assert response.status_code == 409
    assert "no agent-proposed" in response.json()["detail"].lower()


def test_accept_proposal_on_a_run_with_no_proposal_row_at_all_is_refused(client):
    """A failed capture means the agent is never called, so there's no
    AgentProposal row at all -- not even a declined one."""
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()
    mock_agent = MagicMock()
    with _patched_capture_manager(_failed_capture()), patch(
        "backend.orchestrator.TradeAgent", return_value=mock_agent
    ):
        client.post(f"/runs/{created['id']}/analyze")

    response = client.post(f"/runs/{created['id']}/accept-proposal")

    assert response.status_code == 409


def test_accept_proposal_on_an_unanalyzed_run_is_refused(client):
    created = client.post("/runs", json=GOOD_RUN_PAYLOAD).json()

    response = client.post(f"/runs/{created['id']}/accept-proposal")

    assert response.status_code == 409


def test_accept_proposal_on_a_nonexistent_run_returns_404(client):
    response = client.post("/runs/does-not-exist/accept-proposal")

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
