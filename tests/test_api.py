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
from database import models  # noqa: F401 -- registers tables on Base.metadata
from database.database import Base, get_session


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
        yield test_client
    app.dependency_overrides.clear()


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
