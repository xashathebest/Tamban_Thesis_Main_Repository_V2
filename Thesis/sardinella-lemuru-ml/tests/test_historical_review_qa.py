"""Reviews are scoped by session and never overwrite AI evidence."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import Detection, InspectionState, TrackingConfig


@pytest.fixture
def setup_system(tmp_path, monkeypatch):
    app = importlib.import_module("src.api.app")
    database = InspectionDatabase(tmp_path / "review.sqlite")
    sessions = InspectionSessionContext(database)
    old = sessions.start({})
    database.upsert_event(old, fish("Class A"))
    current = sessions.rotate({})
    database.upsert_event(current, fish("Class B"))
    monkeypatch.setattr(app, "inspection_database", database)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "state", InspectionState())
    return TestClient(app.app), database, old, current


def fish(grade):
    return {"track_id": 7, "timestamp": "2026-10-01T00:00:00-04:00", "quality": grade,
            "quality_confidence": .7, "analysis": {"final_grade": grade, "verdict_status": "NEEDS_REVIEW", "reason_codes": ["original"]}}


def test_historical_review_targets_correct_reused_id_and_keeps_ai(setup_system):
    client, database, old, current = setup_system
    before = database.events(session_id=old)[0]
    response = client.post("/api/reviews/7", json={"session_id": old, "manual_grade": "C", "reviewer": "Expert One"})
    assert response.status_code == 200
    historical = database.events(session_id=old)[0]
    active = database.events(session_id=current)[0]
    assert historical["quality"] == before["quality"] == "Class A"
    assert historical["analysis"] == before["analysis"]
    assert historical["manual_grade"] == "Class C" and historical["reviewer"] == "Expert One"
    assert not active.get("manual_override") and active["quality"] == "Class B"
    audit = client.get(f"/api/sessions/{old}/reviews/7/audit").json()["items"]
    assert len(audit) == 1 and audit[0]["manual_grade"] == "Class C" and audit[0]["source"] == "operator"
    assert client.get("/api/reviews", params={"session_id": old}).json()["total"] == 0


def test_current_default_repeat_and_clear_leave_audit(setup_system):
    client, database, old, current = setup_system
    for grade in ("A", "Rejected", None):
        result = client.post("/api/reviews/7", json={"manual_grade": grade, "reviewer": "Operator"})
        assert result.status_code == 200
    event = database.events(session_id=current)[0]
    assert event["quality"] == "Class B" and event["analysis"]["reason_codes"] == ["original"]
    assert event["manual_grade"] is None and not event["manual_override"]
    audit = database.review_audit(current, 7)
    assert [row["manual_grade"] for row in audit] == ["Class A", "Rejected", None]
    assert [row["previous_grade"] for row in audit] == [None, "Class A", "Rejected"]
    assert database.review_audit(old, 7) == []
    analytics = client.get("/api/analytics").json()
    assert analytics["grade_distribution_basis"] == "original_ai_verdict"
    assert analytics["accuracy_available"] is False and analytics["manual_reviewed"] == 0


def test_unknown_session_fish_and_invalid_payload_are_rejected(setup_system):
    client, database, old, current = setup_system
    assert client.post("/api/reviews/7", json={"session_id": "missing", "manual_grade": "A"}).status_code == 404
    assert client.post("/api/reviews/99", json={"session_id": old, "manual_grade": "A"}).status_code == 404
    assert client.post("/api/reviews/7", json={"session_id": "", "manual_grade": "A"}).status_code == 422
    assert client.post("/api/reviews/7", json={}).status_code == 422
    assert client.post("/api/reviews/7", json={"manual_grade": "A", "reviewer": 123}).status_code == 422
    assert client.get("/api/reviews", params={"session_id": "missing"}).status_code == 404
    assert database.review_audit(old, 7) == database.review_audit(current, 7) == []


def test_failed_audit_insert_rolls_back_review(setup_system):
    client, database, _, current = setup_system
    with database._connection() as connection:
        connection.execute("CREATE TRIGGER reject_test_audit BEFORE INSERT ON inspection_review_audit BEGIN SELECT RAISE(ABORT, 'audit failure'); END")
    with pytest.raises(Exception, match="audit failure"):
        client.post("/api/reviews/7", json={"manual_grade": "A"})
    assert not database.events(session_id=current)[0].get("manual_override")
    assert database.review_audit(current, 7) == []


def test_current_review_survives_later_in_memory_event_updates(setup_system, monkeypatch):
    client, database, _, current = setup_system
    app = importlib.import_module("src.api.app")
    state = InspectionState(TrackingConfig(line_orientation="vertical", line_position=.5, conveyor_direction="left_to_right"))
    state.tracking.add_event_listener(lambda _action, payload: database.upsert_event(current, payload))
    monkeypatch.setattr(app, "state", state)
    state.tracking.update([Detection(0, "Fish", .9, (5, 10, 25, 35), track_id=8)], (100, 60), timestamp=0)
    state.tracking.update([Detection(0, "Fish", .9, (65, 10, 85, 35), track_id=8)], (100, 60), timestamp=1)
    assert client.post("/api/reviews/8", json={"manual_grade": "B", "reviewer": "Operator"}).status_code == 200
    assert state.tracking.archive_history()[0]["manual_grade"] == "Class B"
    state.tracking.update_event_analysis(8, {"later_note": "retained"})
    item = next(event for event in database.events(session_id=current) if event["track_id"] == 8)
    assert item["manual_grade"] == "Class B" and item["reviewer"] == "Operator"
    assert item["analysis"]["later_note"] == "retained"


def test_export_labels_ai_and_manual_values_separately(setup_system):
    client, _, old, _ = setup_system
    client.post("/api/reviews/7", json={"session_id": old, "manual_grade": "C", "reviewer": "Expert"})
    response = client.post("/api/export", json={"format": "csv", "range": "current_session", "session_id": old,
                                                  "fields": ["grade", "manual_grade", "reviewer", "review_source"]})
    assert response.status_code == 200
    assert "AI Final Grade,Manual Grade,Reviewer,Review Source" in response.text
    assert "Class A,Class C,Expert,operator" in response.text
