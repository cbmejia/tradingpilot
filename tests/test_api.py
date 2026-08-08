# TradePilot AI — tests for the backend API (Milestone 4).
#
# Every test here gets its own temporary SQLite file via a FastAPI
# dependency override, so running these never touches the real
# database/tradepilot.db file. (tests/conftest.py adds a second layer of
# protection: it points the app's own fallback database at a throwaway
# file too, in case the override were ever missing.)

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app
from database import crud, models  # noqa: F401 -- models registers tables on Base.metadata
from database.database import Base, get_session
from guardrails.rules import BLOCKING_RULES, REVIEW_FORCING_RULES


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test_api.db"
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
        # Milestone 10: there's no orchestrator yet to populate guardrail
        # results for real, so tests that need a run in a specific
        # guardrail state (BLOCKED / REQUIRES_REVIEW / READY_FOR_REVIEW)
        # insert GuardrailResult rows directly, via this session factory,
        # against the exact same database the API test client uses.
        test_client.session_factory = TestSessionLocal
        yield test_client
    app.dependency_overrides.clear()


def _seed_guardrail_results(client, run_id: str, failing_rule: str = None) -> None:
    """
    Inserts one passing GuardrailResult row per known rule, except for
    `failing_rule` (if given), which is inserted as failing. With no
    failing_rule, this produces a READY_FOR_REVIEW run. A failing
    BLOCKING_RULES member produces BLOCKED; a failing REVIEW_FORCING_RULES
    member produces REQUIRES_REVIEW.
    """
    session = client.session_factory()
    try:
        for name in sorted(BLOCKING_RULES | REVIEW_FORCING_RULES):
            crud.add_guardrail_result(
                session,
                run_id=run_id,
                guardrail_name=name,
                passed=(name != failing_rule),
                reason="test setup",
            )
    finally:
        session.close()


VALID_RUN_PAYLOAD = {
    "symbol": "EURUSD",
    "timeframe": "1h",
    "direction": "long",
    "entry": 1.0921,
    "stop": 1.0890,
    "target": 1.1000,
}


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_create_valid_run(client):
    response = client.post("/runs", json=VALID_RUN_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["status"] == "CREATED"


def test_create_run_requires_only_symbol_and_timeframe(client):
    response = client.post("/runs", json={"symbol": "EURUSD", "timeframe": "1h"})

    assert response.status_code == 201


def test_create_run_with_invalid_timeframe_returns_422(client):
    response = client.post(
        "/runs", json={"symbol": "EURUSD", "timeframe": "3h"}
    )

    assert response.status_code == 422


def test_create_run_with_negative_entry_returns_422(client):
    payload = {**VALID_RUN_PAYLOAD, "entry": -1.5}

    response = client.post("/runs", json=payload)

    assert response.status_code == 422


def test_create_run_with_zero_stop_returns_422(client):
    """gt=0 means zero is rejected too, not just negative numbers."""
    payload = {**VALID_RUN_PAYLOAD, "stop": 0}

    response = client.post("/runs", json=payload)

    assert response.status_code == 422


def test_get_nonexistent_run_returns_404(client):
    response = client.get("/runs/does-not-exist")

    assert response.status_code == 404


def test_list_runs_returns_newest_first(client):
    first = client.post("/runs", json={"symbol": "EURUSD", "timeframe": "1h"}).json()
    second = client.post("/runs", json={"symbol": "GBPUSD", "timeframe": "4h"}).json()

    response = client.get("/runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0

    ids_in_order = [item["id"] for item in body["items"]]
    assert ids_in_order.index(second["id"]) < ids_in_order.index(first["id"])

    created_at_values = [
        datetime.fromisoformat(item["created_at"]) for item in body["items"]
    ]
    assert created_at_values == sorted(created_at_values, reverse=True)


def test_list_runs_paging(client):
    for i in range(3):
        client.post("/runs", json={"symbol": f"SYM{i}", "timeframe": "1h"})

    response = client.get("/runs", params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2


def test_get_full_run_includes_creation_audit_event(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.get(f"/runs/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["symbol"] == "EURUSD"
    assert body["status"] == "CREATED"

    # No pipeline has run yet -- every child list is empty except the
    # audit trail, which should have exactly the creation event.
    assert body["captures"] == []
    assert body["market_data"] == []
    assert body["analyses"] == []
    assert body["evaluations"] == []
    assert body["guardrail_results"] == []
    assert body["human_review"] is None

    assert len(body["audit_events"]) == 1
    assert body["audit_events"][0]["event_type"] == "run_created"
    assert "EURUSD" in body["audit_events"][0]["event_message"]


def test_run_timestamps_are_timezone_aware_iso8601(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.get(f"/runs/{created['id']}")
    created_at_raw = response.json()["created_at"]

    parsed = datetime.fromisoformat(created_at_raw)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# Milestone 10 — POST /runs/{run_id}/review
# ---------------------------------------------------------------------------


def test_approving_a_ready_for_review_run_stores_decision_updates_status_writes_audit_event(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])  # no failing rule -> READY_FOR_REVIEW

    response = client.post(
        f"/runs/{created['id']}/review",
        json={"decision": "APPROVED", "comment": "Looks solid, clean setup."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == created["id"]
    assert body["decision"] == "APPROVED"
    assert body["comment"] == "Looks solid, clean setup."
    assert body["run_status"] == "APPROVED"

    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["status"] == "APPROVED"
    assert full_run["completed_at"] is not None
    assert full_run["human_review"]["decision"] == "APPROVED"
    assert full_run["human_review"]["comment"] == "Looks solid, clean setup."
    assert full_run["guardrail_outcome"] == "READY_FOR_REVIEW"

    audit_types = [e["event_type"] for e in full_run["audit_events"]]
    assert "human_review_recorded" in audit_types
    review_event = next(e for e in full_run["audit_events"] if e["event_type"] == "human_review_recorded")
    assert "APPROVED" in review_event["event_message"] or "approved" in review_event["event_message"]


def test_rejecting_a_ready_for_review_run_stores_decision_updates_status_writes_audit_event(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "REJECTED"})

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "REJECTED"
    assert body["run_status"] == "REJECTED"

    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["status"] == "REJECTED"
    assert full_run["completed_at"] is not None
    assert full_run["human_review"]["decision"] == "REJECTED"

    audit_types = [e["event_type"] for e in full_run["audit_events"]]
    assert "human_review_recorded" in audit_types


def test_approving_a_blocked_run_is_refused_with_a_clear_error(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"], failing_rule="CAPTURE_SUCCEEDED")

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "APPROVED"})

    assert response.status_code == 409
    assert "block" in response.json()["detail"].lower()

    # Nothing was recorded -- still no decision.
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["human_review"] is None
    assert full_run["status"] == "CREATED"
    assert full_run["guardrail_outcome"] == "BLOCKED"


def test_rejecting_a_blocked_run_is_permitted(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"], failing_rule="CAPTURE_SUCCEEDED")

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "REJECTED"})

    assert response.status_code == 200
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["human_review"]["decision"] == "REJECTED"
    assert full_run["status"] == "REJECTED"


def test_approving_a_run_with_no_guardrail_results_yet_is_refused(client):
    """No guardrail results at all is treated the same as BLOCKED for
    approval purposes -- there's no evidence this run wasn't blocked."""
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "APPROVED"})

    assert response.status_code == 409
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["guardrail_outcome"] is None
    assert full_run["human_review"] is None


def test_rejecting_a_run_with_no_guardrail_results_is_permitted(client):
    """REJECTED is permitted on any run, in any state -- including one
    that never had guardrails run against it at all."""
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "REJECTED"})

    assert response.status_code == 200


def test_a_requires_review_run_can_still_be_approved(client):
    """Only BLOCKED forbids approval -- REQUIRES_REVIEW means there IS
    something to review, so a human is allowed to accept it."""
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"], failing_rule="SCORE_THRESHOLD")

    precheck = client.get(f"/runs/{created['id']}").json()
    assert precheck["guardrail_outcome"] == "REQUIRES_REVIEW"

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "APPROVED"})

    assert response.status_code == 200
    assert response.json()["run_status"] == "APPROVED"


def test_second_decision_on_already_decided_run_is_refused_original_unchanged(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])

    first = client.post(
        f"/runs/{created['id']}/review", json={"decision": "APPROVED", "comment": "first decision"}
    )
    assert first.status_code == 200

    second = client.post(
        f"/runs/{created['id']}/review", json={"decision": "REJECTED", "comment": "trying to overwrite"}
    )

    assert second.status_code == 409
    assert "final" in second.json()["detail"].lower() or "already" in second.json()["detail"].lower()

    # The original decision is unchanged in the database.
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["human_review"]["decision"] == "APPROVED"
    assert full_run["human_review"]["comment"] == "first decision"
    assert full_run["status"] == "APPROVED"

    # Only one human_review_recorded audit event exists -- the refused
    # second attempt did not write anything.
    review_events = [e for e in full_run["audit_events"] if e["event_type"] == "human_review_recorded"]
    assert len(review_events) == 1


def test_decision_on_nonexistent_run_returns_404(client):
    response = client.post("/runs/does-not-exist/review", json={"decision": "APPROVED"})

    assert response.status_code == 404


def test_invalid_decision_value_returns_422(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "MAYBE"})

    assert response.status_code == 422


def test_decision_is_case_insensitive(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "approved"})

    assert response.status_code == 200
    assert response.json()["decision"] == "APPROVED"


def test_client_cannot_inject_a_score_or_override_guardrail_verdict(client):
    """Extra fields in the request body (a score, a guardrail outcome,
    anything else) are simply not part of the schema -- they're ignored,
    not stored, and have no effect on the outcome."""
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"], failing_rule="CAPTURE_SUCCEEDED")

    response = client.post(
        f"/runs/{created['id']}/review",
        json={
            "decision": "APPROVED",
            "comment": "trying to sneak something in",
            "total_score": 100,
            "guardrail_outcome": "READY_FOR_REVIEW",
            "risk_reward_score": 20,
        },
    )

    # The run is genuinely BLOCKED -- injected fields change nothing.
    assert response.status_code == 409
    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["human_review"] is None
    assert full_run["guardrail_outcome"] == "BLOCKED"


def test_decision_timestamps_are_timezone_aware_utc(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])

    response = client.post(f"/runs/{created['id']}/review", json={"decision": "APPROVED"})
    decided_at_raw = response.json()["decided_at"]

    parsed = datetime.fromisoformat(decided_at_raw)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0

    # completed_at on the run itself matches the same moment.
    full_run = client.get(f"/runs/{created['id']}").json()
    completed_parsed = datetime.fromisoformat(full_run["completed_at"])
    assert completed_parsed.tzinfo is not None
    assert completed_parsed.utcoffset().total_seconds() == 0


def test_review_endpoint_does_not_write_capture_market_data_or_evaluation_rows(client):
    """The endpoint records a human judgment about existing results --
    it must never re-run the pipeline or fabricate new rows for steps
    that were never actually performed."""
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_guardrail_results(client, created["id"])

    client.post(f"/runs/{created['id']}/review", json={"decision": "APPROVED"})

    full_run = client.get(f"/runs/{created['id']}").json()
    assert full_run["captures"] == []
    assert full_run["market_data"] == []
    assert full_run["analyses"] == []
    assert full_run["evaluations"] == []


# ---------------------------------------------------------------------------
# Milestone 11 prerequisite — GET /runs/{run_id}/screenshot
#
# The path served is derived entirely from the run's own stored Capture
# row, never from anything the client supplies -- these tests confirm
# every "no image right now" state returns a clear 404 (never a 500),
# and that a stored path outside screenshots/ is refused rather than
# served.
# ---------------------------------------------------------------------------


def _seed_capture(client, run_id: str, **overrides) -> None:
    from capture.base import CaptureMode, CaptureStatus

    defaults = dict(
        capture_mode=CaptureMode.DEMO.value,
        symbol="EURUSD",
        timeframe="1h",
        status=CaptureStatus.SUCCESS.value,
        screenshot_path=None,
        error_message=None,
    )
    defaults.update(overrides)
    session = client.session_factory()
    try:
        crud.add_capture(session, run_id=run_id, **defaults)
    finally:
        session.close()


def test_screenshot_endpoint_serves_the_image_with_correct_content_type(client):
    from capture.demo_provider import DemoProvider

    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    real_capture = DemoProvider().capture("EURUSD", "1h")
    assert real_capture.status.value == "SUCCESS"  # sanity check on the fixture itself
    _seed_capture(client, created["id"], screenshot_path=real_capture.screenshot_path)

    response = client.get(f"/runs/{created['id']}/screenshot")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0


def test_screenshot_endpoint_returns_404_with_clear_reason_when_capture_failed(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_capture(
        client,
        created["id"],
        status="FAILED",
        screenshot_path=None,
        error_message="No demo fixture for ZZZINVALID 1h.",
    )

    response = client.get(f"/runs/{created['id']}/screenshot")

    assert response.status_code == 404
    assert "ZZZINVALID" in response.json()["detail"]


def test_screenshot_endpoint_returns_404_not_500_when_file_missing_from_disk(client):
    from capture.base import DEMO_DIR

    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    missing_path = str(DEMO_DIR / "DOES_NOT_EXIST_1h.png")
    _seed_capture(client, created["id"], screenshot_path=missing_path)

    response = client.get(f"/runs/{created['id']}/screenshot")

    assert response.status_code == 404
    assert "missing" in response.json()["detail"].lower()


def test_screenshot_endpoint_returns_404_for_nonexistent_run(client):
    response = client.get("/runs/does-not-exist/screenshot")

    assert response.status_code == 404


def test_screenshot_endpoint_returns_404_when_run_has_no_capture_yet(client):
    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()

    response = client.get(f"/runs/{created['id']}/screenshot")

    assert response.status_code == 404


def test_screenshot_endpoint_refuses_a_path_resolving_outside_screenshots_directory(client, tmp_path):
    """A stored path pointing anywhere outside screenshots/ -- whether
    from a bug or a tampered row -- is refused, never served, and the
    refusal looks identical to any other "no image" case."""
    outside_file = tmp_path / "not_a_real_chart.png"
    outside_file.write_bytes(b"not actually a chart")

    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    _seed_capture(client, created["id"], screenshot_path=str(outside_file))

    response = client.get(f"/runs/{created['id']}/screenshot")

    assert response.status_code == 404
    assert response.content != b"not actually a chart"


def test_screenshot_endpoint_accepts_no_client_supplied_path_or_filename(client):
    """Query-string tricks aiming at a different file have zero effect --
    there is no path/filename parameter anywhere on this endpoint, only
    run_id, so the response is identical with or without them."""
    from capture.demo_provider import DemoProvider

    created = client.post("/runs", json=VALID_RUN_PAYLOAD).json()
    real_capture = DemoProvider().capture("EURUSD", "1h")
    _seed_capture(client, created["id"], screenshot_path=real_capture.screenshot_path)

    plain = client.get(f"/runs/{created['id']}/screenshot")
    with_query_tricks = client.get(
        f"/runs/{created['id']}/screenshot",
        params={"path": "/etc/passwd", "filename": "../../../secrets.txt", "file": "C:\\Windows\\win.ini"},
    )

    assert plain.status_code == with_query_tricks.status_code == 200
    assert plain.content == with_query_tricks.content
