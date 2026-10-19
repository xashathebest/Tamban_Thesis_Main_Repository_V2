"""History pagination and analytics preserve durable session semantics."""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import InspectionState


@pytest.fixture
def system(tmp_path, monkeypatch):
    app = importlib.import_module("src.api.app")
    database = InspectionDatabase(tmp_path / "history.sqlite")
    sessions = InspectionSessionContext(database)
    current = sessions.start({})
    monkeypatch.setattr(app, "inspection_database", database)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "state", InspectionState())
    return app, database, sessions, current


def event(track_id, timestamp, grade="Class A", score=.8, region="Body"):
    return {"track_id": track_id, "timestamp": timestamp, "quality": grade, "quality_confidence": .2,
            "parts": [{"region": region}], "analysis": {"final_grade": grade, "final_score": score,
            "verdict_status": "NEEDS_REVIEW", "part_results": {region: {"present": True}}}}


def test_pages_filters_and_session_boundaries_without_full_history(system, monkeypatch):
    app, database, sessions, current = system
    for number in range(1, 7):
        database.upsert_event(current, event(number, f"2026-10-{number:02d}T23:00:00-05:00", "Class A" if number % 2 else "Class B", number / 10))
    other = database.create_session({})
    database.upsert_event(other, event(999, "2026-10-03T00:00:00+14:00"))
    monkeypatch.setattr(database, "events", lambda **kwargs: pytest.fail("paged history must not load all events"))
    page = app.get_history(page=2, page_size=2, grade="class a", min_confidence=10, feature="body")
    assert page["total"] == 3
    assert [item["track_id"] for item in page["items"]] == [1]
    assert app.get_history(search="Fish #5")["items"][0]["track_id"] == 5
    assert app.get_history(page=99, page_size=2)["items"] == []
    assert app.get_history(range_name="all")["total"] == 7
    assert app.get_history(range_name="current_session", session_id=other)["total"] == 1
    with pytest.raises(HTTPException):
        app.get_history(min_confidence=101)


def test_date_filter_uses_recorded_local_date_and_excludes_invalid(system):
    app, database, _, current = system
    database.upsert_event(current, event(1, "2026-10-03T23:30:00-05:00"))
    database.upsert_event(current, event(2, "2026-10-04T00:30:00+14:00"))
    database.upsert_event(current, event(3, "invalid"))
    result = app.get_history(range_name="custom", start_date="2026-10-03", end_date="2026-10-03")
    assert [item["track_id"] for item in result["items"]] == [1]
    assert [item["track_id"] for item in database.events(range_name="custom", start_date="2026-10-03", end_date="2026-10-03")] == [1]
    with pytest.raises(HTTPException):
        app.get_history(range_name="custom", start_date="2026-10-04", end_date="2026-10-03")


def test_cached_analytics_append_review_and_rotation(system, monkeypatch):
    app, database, sessions, current = system
    database.upsert_event(current, event(1, "2026-10-01T00:00:00+00:00"))
    original_iterator = database.iter_events_chronological
    calls = []
    def counted(**kwargs):
        calls.append(True)
        return original_iterator(**kwargs)
    monkeypatch.setattr(database, "iter_events_chronological", counted)
    assert app.get_analytics()["grade_distribution"]["Class A"] == 1
    assert app.get_analytics()["grade_distribution"]["Class A"] == 1
    database.upsert_event(current, event(2, "2026-10-02T00:00:00+00:00", "Class B"))
    appended = app.get_analytics()
    assert len(calls) == 1
    assert appended["grade_distribution"]["Class B"] == 1
    assert appended["throughput"][-1]["total"] == 2
    database.apply_manual_review(current, 2, "Class A")
    reviewed = app.get_analytics()
    assert reviewed["manual_reviewed"] == 1
    assert len(calls) == 1
    database.apply_manual_review(current, 2, None)
    assert app.get_analytics()["manual_reviewed"] == 0
    assert len(calls) == 1
    database.apply_manual_review(current, 2, "Class A")
    database.apply_manual_review(current, 2, None)
    assert app.get_analytics()["manual_reviewed"] == 0
    assert len(calls) == 2
    database.upsert_event(current, event(3, "2026-09-30T00:00:00+00:00"))
    assert app.get_analytics()["throughput"][0]["timestamp"].startswith("2026-09-30")
    assert len(calls) == 3
    sessions.rotate({})
    assert app.get_analytics()["trend_events_total"] == 0


def test_trends_are_bounded_but_summaries_cover_all_events():
    app = importlib.import_module("src.api.app")
    events = [event(number, f"2026-10-01T00:00:{number:02d}+00:00") for number in range(600)]
    result = app._analytics(iter(events), {}, chronological_input=True)
    assert result["trend_events_total"] == 600
    assert len(result["throughput"]) == len(result["confidence_over_time"]) == 500
    assert result["throughput"][0]["total"] == 101
    assert result["grade_distribution"]["Class A"] == 600


def test_older_grade_edit_and_deletion_rebuild_the_cache(system):
    app, database, _, current = system
    database.upsert_event(current, event(1, "2026-10-01T00:00:00+00:00"))
    database.upsert_event(current, event(2, "2026-10-02T00:00:00+00:00"))
    assert app.get_analytics()["grade_distribution"]["Class A"] == 2
    database.upsert_event(current, event(1, "2026-10-01T00:00:00+00:00", "Class C"))
    assert app.get_analytics()["grade_distribution"]["Class C"] == 1
    with database._connection() as connection:
        connection.execute("DELETE FROM fish_inspections WHERE session_id = ? AND track_id = ?", (current, 2))
    summary = app.get_analytics()
    assert summary["trend_events_total"] == 1
    assert summary["grade_distribution"]["Class A"] == 0


def test_same_second_fish_append_in_deterministic_track_order(system, monkeypatch):
    app, database, _, current = system
    database_module = importlib.import_module("src.api.database")
    monkeypatch.setattr(database_module, "_now", lambda: "2026-10-01T00:00:00+00:00")
    timestamp = "2026-10-01T00:00:00+00:00"
    database.upsert_event(current, event(1, timestamp))
    app.get_analytics()
    monkeypatch.setattr(database, "iter_events_chronological", lambda **kwargs: pytest.fail("append should not rescan"))
    database.upsert_event(current, event(2, timestamp))
    summary = app.get_analytics()
    assert summary["trend_events_total"] == 2
    assert [item["track_id"] for item in app.get_history()["items"]] == [2, 1]
