# TradePilot AI — tests for the repeatability harness (7A Iteration 3).
#
# The real DEMO capture and market-data providers run for real in the
# behavioral tests below -- no network, same pattern tests/test_orchestrator.py
# already uses. The agent is always mocked (backend.orchestrator.TradeAgent
# patched directly) -- no anthropic client is ever constructed, no network
# call is ever made, no real cost.

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agents.trade_agent import (
    AgentAnalysisResult,
    AgentAnalysisStatus,
    ConfirmationAnalysisResult,
    ConfirmationAnalysisStatus,
)
from backend.orchestrator import run_pipeline
from database import crud, models  # noqa: F401 -- models registers tables on Base.metadata
from database.database import Base
from tools import repeatability_harness as harness

HARNESS_SOURCE = Path(harness.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Read-only-with-respect-to-scoring
# ---------------------------------------------------------------------------


def test_harness_source_never_imports_evals():
    """
    The harness is only ever allowed to call run_pipeline() (which
    internally uses evals/trade_evaluator.py, exactly as any other caller
    would) and read results back -- it must never import evals/ itself,
    which would open a path to computing or recomputing a score directly.
    Same source-grep discipline docs/iterations.md's 7A Iteration 1 entry
    used to prove evals/trade_evaluator.py never reads agent_proposals.

    Checked line-by-line (stripped, startswith) rather than a raw
    substring search -- this module's own docstring above *describes*
    the rule in prose, which would otherwise false-positive a naive
    substring check.
    """
    import_lines = [
        line.strip()
        for line in HARNESS_SOURCE.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    assert not any(line.startswith("import evals") for line in import_lines)
    assert not any(line.startswith("from evals") for line in import_lines)


def _good_agent_result() -> AgentAnalysisResult:
    return AgentAnalysisResult(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="Clean uptrend.",
        trend_assessment="up",
        structure_assessment="clean",
        setup_assessment="acceptable",
        uncertainty="MEDIUM",
        trend_direction="UP",
        trend_quality="MODERATE",
        structure_quality="MIXED",
        setup_quality="MARGINAL",
        context_risk="MODERATE",
        proposal_has_proposal=False,
        proposal_direction=None,
        proposal_entry=None,
        proposal_stop=None,
        proposal_target=None,
        model="claude-sonnet-5",
        timestamp=datetime.now(timezone.utc),
        error_message=None,
    )


def _good_confirmation_result() -> ConfirmationAnalysisResult:
    return ConfirmationAnalysisResult(
        status=ConfirmationAnalysisStatus.SUCCESS,
        visible_timeframe="4h",
        trend_direction="UP",
        trend_quality="MODERATE",
        model="claude-sonnet-5",
        timestamp=datetime.now(timezone.utc),
        error_message=None,
    )


@pytest.fixture()
def temp_session_factory(tmp_path):
    db_path = tmp_path / "harness_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _mock_agent():
    agent = MagicMock()
    agent.analyze.return_value = _good_agent_result()
    agent.analyze_confirmation.return_value = _good_confirmation_result()
    return agent


def test_harness_produces_evaluations_identical_to_direct_run_pipeline(temp_session_factory, tmp_path, monkeypatch):
    """
    The harness must add repetition only, never its own scoring logic.
    Proven directly: run one batch of n=1 through the harness, and
    separately create an equivalent run and call run_pipeline() directly
    -- same fixture, same mocked agent response -- against a second,
    independent temp database. The resulting Evaluation rows (every score
    component, not just total_score) must be identical.
    """
    monkeypatch.setattr(harness, "SessionLocal", temp_session_factory)
    monkeypatch.setattr(harness, "MEASUREMENTS_DIR", tmp_path)
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "demo")

    with patch("backend.orchestrator.TradeAgent", return_value=_mock_agent()):
        out_path = harness.run_batch("stability", "levels", n=1, allow_live=False)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    harness_record = payload["records"][0]
    assert harness_record["harness_status"] == "COMPLETED"

    # Independent, direct call -- a fresh temp DB, the same fixture, the
    # same mocked agent -- to compare against.
    direct_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=direct_engine)
    DirectSession = sessionmaker(bind=direct_engine)
    direct_session = DirectSession()
    try:
        run = crud.create_run(
            direct_session,
            symbol="EURUSD",
            timeframe="1h",
            direction="long",
            entry=1.1500,
            stop=1.1450,
            target=1.1600,
        )
        with patch("backend.orchestrator.TradeAgent", return_value=_mock_agent()):
            updated = run_pipeline(direct_session, run.id, chart_variant="readable_chart")
        direct_evaluation = updated.evaluations[0]
    finally:
        direct_session.close()

    assert harness_record["total_score"] == direct_evaluation.total_score
    assert harness_record["trend_score"] == direct_evaluation.trend_score
    assert harness_record["structure_score"] == direct_evaluation.structure_score
    assert harness_record["entry_score"] == direct_evaluation.entry_score
    assert harness_record["risk_reward_score"] == direct_evaluation.risk_reward_score
    assert harness_record["timing_context_score"] == direct_evaluation.timing_context_score


def test_harness_run_gets_a_provenance_audit_event(temp_session_factory, tmp_path, monkeypatch):
    """Every harness-created run is self-identifying via its own audit
    trail -- distinguishing it from an ordinary run without needing a
    schema change or an external doc."""
    monkeypatch.setattr(harness, "SessionLocal", temp_session_factory)
    monkeypatch.setattr(harness, "MEASUREMENTS_DIR", tmp_path)
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "demo")

    with patch("backend.orchestrator.TradeAgent", return_value=_mock_agent()):
        out_path = harness.run_batch("stability", "none", n=1, allow_live=False)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    run_id = payload["records"][0]["run_id"]

    session = temp_session_factory()
    try:
        run = crud.get_run(session, run_id)
        event_types = [e.event_type for e in run.audit_events]
        assert "repeatability_harness_run" in event_types
    finally:
        session.close()


# ---------------------------------------------------------------------------
# LIVE guard (hard constraint 3)
# ---------------------------------------------------------------------------


def test_live_guard_refuses_without_allow_live(monkeypatch):
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "live")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "live")

    proceed, effective_n = harness._live_guard(allow_live=False, requested_n=10)

    assert proceed is False


def test_live_guard_caps_n_at_five_with_allow_live(monkeypatch):
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "live")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "live")

    proceed, effective_n = harness._live_guard(allow_live=True, requested_n=20)

    assert proceed is True
    assert effective_n == harness.LIVE_MODE_HARD_CAP == 5


def test_live_guard_passes_through_unaffected_when_demo(monkeypatch):
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "demo")

    proceed, effective_n = harness._live_guard(allow_live=False, requested_n=37)

    assert proceed is True
    assert effective_n == 37


def test_live_guard_refuses_if_only_one_mode_is_live(monkeypatch):
    """Either mode being non-demo is enough to trigger the guard -- DEMO
    capture with a real LIVE market-data call would still burn quota."""
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "live")

    proceed, _ = harness._live_guard(allow_live=False, requested_n=1)

    assert proceed is False


# ---------------------------------------------------------------------------
# Per-run failure handling (no retries, explicit denominators)
# ---------------------------------------------------------------------------


def test_a_failed_run_does_not_abort_the_batch(temp_session_factory, tmp_path, monkeypatch):
    """A crash on one run is recorded as its own failure record and the
    batch continues to N -- never retried, never silently dropped."""
    monkeypatch.setattr(harness, "SessionLocal", temp_session_factory)
    monkeypatch.setattr(harness, "MEASUREMENTS_DIR", tmp_path)
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "demo")

    call_count = {"n": 0}
    real_run_pipeline = harness.run_pipeline

    def flaky_run_pipeline(session, run_id, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated crash")
        return real_run_pipeline(session, run_id, **kwargs)

    with patch("backend.orchestrator.TradeAgent", return_value=_mock_agent()):
        with patch.object(harness, "run_pipeline", side_effect=flaky_run_pipeline):
            out_path = harness.run_batch("stability", "none", n=3, allow_live=False)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["n_completed"] == 2
    assert payload["n_failed"] == 1
    statuses = [r["harness_status"] for r in payload["records"]]
    assert statuses == ["COMPLETED", "HARNESS_FAILURE", "COMPLETED"]
    assert "simulated crash" in payload["records"][1]["harness_error"]


# ---------------------------------------------------------------------------
# Attribution -- only when exactly one field differs
# ---------------------------------------------------------------------------


def _record(total_score, **overrides):
    base = dict(
        run_id="r" * 32,
        harness_status="COMPLETED",
        trend_direction="UP",
        trend_quality="MODERATE",
        structure_quality="MIXED",
        setup_quality="MARGINAL",
        context_risk="MODERATE",
        uncertainty="MEDIUM",
        total_score=total_score,
    )
    base.update(overrides)
    return base


def test_attribution_names_the_single_field_that_drove_a_score_change():
    records = [
        _record(55, run_id="a" * 32),
        _record(55, run_id="b" * 32),
        _record(55, run_id="c" * 32),
        _record(55, run_id="d" * 32),
        _record(45, run_id="e" * 32, trend_quality="WEAK"),
    ]

    notes = harness._attribution_notes(records)

    assert len(notes) == 1
    assert "trend_quality" in notes[0]
    assert "MODERATE -> WEAK" in notes[0]


def test_attribution_declines_to_guess_when_multiple_fields_differ():
    records = [
        _record(55, run_id="a" * 32),
        _record(55, run_id="b" * 32),
        _record(55, run_id="c" * 32),
        _record(35, run_id="d" * 32, trend_quality="WEAK", context_risk="ELEVATED"),
    ]

    notes = harness._attribution_notes(records)

    assert len(notes) == 1
    assert "NOT cleanly attributable" in notes[0]


def test_attribution_is_empty_when_every_run_matches():
    records = [_record(55, run_id=chr(97 + i) * 32) for i in range(4)]

    notes = harness._attribution_notes(records)

    assert notes == []


# ---------------------------------------------------------------------------
# RR clustering -- N/A when no proposals, never fabricated
# ---------------------------------------------------------------------------


def test_rr_clustering_is_na_with_zero_proposals():
    records = [
        dict(harness_status="COMPLETED", has_proposal=False, proposal_risk_reward_ratio=None)
        for _ in range(5)
    ]

    result = harness._rr_clustering(records, supplied_rr=2.0)

    assert result["applicable"] is False
    assert "N/A" in result["note"]
    assert "0/5" in result["note"]


def test_rr_clustering_reports_ratios_when_proposals_exist():
    records = [
        dict(harness_status="COMPLETED", has_proposal=True, proposal_risk_reward_ratio=2.0),
        dict(harness_status="COMPLETED", has_proposal=True, proposal_risk_reward_ratio=1.83),
        dict(harness_status="COMPLETED", has_proposal=False, proposal_risk_reward_ratio=None),
    ]

    result = harness._rr_clustering(records, supplied_rr=2.0)

    assert result["applicable"] is True
    assert result["n_proposals"] == 2
    assert result["n_completed"] == 3
    assert result["ratios"] == [2.0, 1.83]
    assert result["supplied_rr"] == 2.0


# ---------------------------------------------------------------------------
# Model identifier unavailable -- warned loudly, never guessed
# ---------------------------------------------------------------------------


def test_model_none_on_every_run_prints_a_loud_warning(temp_session_factory, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "SessionLocal", temp_session_factory)
    monkeypatch.setattr(harness, "MEASUREMENTS_DIR", tmp_path)
    monkeypatch.setattr("backend.config.CAPTURE_MODE", "demo")
    monkeypatch.setattr("backend.config.MARKET_DATA_MODE", "demo")

    no_model_agent_result = AgentAnalysisResult(
        status=AgentAnalysisStatus.SUCCESS,
        analysis_text="x", trend_assessment="x", structure_assessment="x", setup_assessment="x",
        uncertainty="MEDIUM", trend_direction="UP", trend_quality="MODERATE",
        structure_quality="MIXED", setup_quality="MARGINAL", context_risk="MODERATE",
        proposal_has_proposal=False, proposal_direction=None, proposal_entry=None,
        proposal_stop=None, proposal_target=None,
        model=None,  # simulates an unresolvable model identifier
        timestamp=datetime.now(timezone.utc), error_message=None,
    )
    agent = MagicMock()
    agent.analyze.return_value = no_model_agent_result
    agent.analyze_confirmation.return_value = _good_confirmation_result()

    with patch("backend.orchestrator.TradeAgent", return_value=agent):
        harness.run_batch("stability", "none", n=1, allow_live=False)

    captured = capsys.readouterr()
    assert "model identifier unavailable" in captured.out
