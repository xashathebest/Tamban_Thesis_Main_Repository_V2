"""Fast polling must preserve durable history, updates and legacy status."""
from __future__ import annotations

import importlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import InspectionState


@pytest.fixture
def system(tmp_path, monkeypatch):
    app_module = importlib.import_module("src.api.app")
    db = InspectionDatabase(tmp_path / "status.sqlite3")
    sessions = InspectionSessionContext(db)
    session_id = sessions.start({})
    monkeypatch.setattr(app_module, "inspection_database", db)
    monkeypatch.setattr(app_module, "inspection_sessions", sessions)
    monkeypatch.setattr(app_module, "state", InspectionState())
    return app_module, db, sessions, session_id


def fish(track_id, grade="Ungraded"):
    return {
        "track_id": track_id, "timestamp": datetime.now().astimezone().isoformat(),
        "quality": grade, "quality_confidence": 0.7, "final_confidence": 0.9,
        "parts": [], "manual_override": False,
        "analysis": {"final_grade": grade, "verdict_status": "NEEDS_REVIEW",
                     "part_results": {"Body": {"present": True}}},
    }


def test_live_omits_heavy_history_but_legacy_and_analytics_agree(system):
    app_module, db, _, session_id = system
    db.upsert_event(session_id, fish(1, "Class A"))
    db.upsert_event(session_id, fish(2, "Rejected"))
    client = TestClient(app_module.app)
    legacy = client.get("/api/status").json()
    live = client.get("/api/status/live").json()
    analytics = client.get("/api/analytics").json()
    assert "analytics" not in live and "feature_counters" not in live and "available_models" not in live
    assert live["event_revision"] == analytics["event_revision"] == 2
    assert analytics["grade_distribution"] == legacy["analytics"]["grade_distribution"]
    assert analytics["feature_counts"] == legacy["feature_counters"]
    assert legacy["analytics"]["grade_distribution"]["Rejected"] == 1


def test_revision_changes_for_late_grade_review_and_session_rotation(system):
    app_module, db, sessions, session_id = system
    db.upsert_event(session_id, fish(1))
    original = app_module.get_live_status()["event_revision"]
    db.upsert_event(session_id, fish(1, "Class B"))
    assert app_module.get_live_status()["event_revision"] > original
    revised = db.event_revision(session_id)
    db.apply_manual_review(session_id, 1, "Class A")
    assert db.event_revision(session_id) > revised
    assert app_module.get_analytics()["manual_reviewed"] == 1
    assert app_module.get_analytics()["grade_distribution"]["Class B"] == 1
    new_session = sessions.rotate({})
    live = app_module.get_live_status()
    assert live["durable_session"]["session_id"] == new_session
    assert live["event_revision"] == 0
    assert app_module.get_analytics()["grade_distribution"]["Class B"] == 0


def test_history_filter_and_export_unchanged_by_live_polling(system):
    app_module, db, _, session_id = system
    db.upsert_event(session_id, fish(1, "Class A"))
    db.upsert_event(session_id, fish(2, "Ungraded"))
    client = TestClient(app_module.app)
    before = client.post("/api/export", json={"format": "csv", "fields": ["fish_id", "timestamp", "grade"]})
    assert before.status_code == 200
    assert client.get("/api/status/live").status_code == 200
    history = client.get("/api/history", params={"grade": "Class A"}).json()
    after = client.post("/api/export", json={"format": "csv", "fields": ["fish_id", "timestamp", "grade"]})
    assert [item["track_id"] for item in history["items"]] == [1]
    assert after.content == before.content


def test_existing_database_and_external_updates_invalidate_revision(system):
    _, db, _, session_id = system
    db.upsert_event(session_id, fish(4))
    reopened = InspectionDatabase(db.path)
    before = reopened.event_revision(session_id)
    db.upsert_event(session_id, fish(4, "Class C"))
    assert reopened.event_revision(session_id) == before + 1
