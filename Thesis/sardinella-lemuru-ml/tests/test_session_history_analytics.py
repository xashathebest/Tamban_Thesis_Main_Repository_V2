"""Session auto-save milestones and historical drill-down use durable evidence."""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from types import SimpleNamespace
from threading import Event, Thread

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api.database import InspectionDatabase, InspectionSessionContext

app_module = importlib.import_module("src.api.app")


def fish(track_id, grade="Ungraded", *, reason="UG_MISSING_HEAD", verdict="NEEDS_REVIEW"):
    return {"track_id": track_id, "timestamp": "2026-11-03T10:00:00-05:00", "quality": grade,
            "final_confidence": .9, "processing_time_ms": 12,
            "analysis": {"final_grade": grade, "final_score": .8 if grade != "Ungraded" else None,
                         "verdict_status": verdict, "reason_codes": [reason],
                         "part_results": {"Body": {"present": True}, "Head": {"present": grade != "Ungraded"}},
                         "observed_regions": ["Body"], "original_weight_coverage": .5}}


@pytest.fixture
def durable(tmp_path, monkeypatch):
    database = InspectionDatabase(tmp_path / "history.sqlite3")
    sessions = InspectionSessionContext(database)
    monkeypatch.setattr(app_module, "inspection_database", database)
    monkeypatch.setattr(app_module, "inspection_sessions", sessions)
    monkeypatch.setattr(app_module, "_require_drained_event_persistence", lambda *_: None)
    monkeypatch.setattr(app_module, "service", SimpleNamespace())
    app_module._analytics_cache.clear()
    return database, sessions


def test_zero_fish_autosave_after_accumulated_active_minute(durable):
    database, sessions = durable
    identifier = sessions.start({})
    assert sessions.start({}) == identifier
    for tick in range(31):
        sessions.observe_activity(True, now=tick)
    for tick in range(31, 91):
        sessions.observe_activity(False, now=tick)
    for tick in range(91, 122):
        sessions.observe_activity(True, now=tick)
    saved = database.session(identifier)
    assert saved["active_seconds"] == 60
    assert saved["auto_save_eligible"] and saved["autosaved_at"]
    assert saved["fish_count"] == 0 and saved["records_durable"]
    assert len(database.sessions()) == 1
    sessions.close()
    assert database.session(identifier)["status"] == "completed"


def test_short_sessions_and_duplicates_are_retained_without_overwrite(durable):
    database, sessions = durable
    first = sessions.start({})
    sessions.record_event("created", fish(1))
    sessions.record_event("updated", fish(1, "Class B"))
    sessions.close()
    second = sessions.start({})
    sessions.record_event("created", fish(1, "Class A"))
    assert second != first
    assert database.session(first)["grade_distribution"]["Class B"] == 1
    assert database.session(second)["grade_distribution"]["Class A"] == 1
    assert database.session(first)["fish_count"] == 1
    assert not database.session(first)["auto_save_eligible"]


def test_restart_recovers_last_checkpoint_and_never_counts_offline_wall_time(durable):
    database, sessions = durable
    original = sessions.start({})
    for tick in range(61):
        sessions.observe_activity(True, now=tick)
    checkpoint = database.session(original)
    reopened = InspectionDatabase(database.path)
    assert reopened.recover_interrupted_sessions() == 1
    restored = reopened.session(original)
    assert restored["status"] == "interrupted"
    assert restored["ended_at"] == checkpoint["heartbeat_at"]
    assert restored["active_seconds"] == 60 and restored["autosaved_at"]
    resumed = InspectionSessionContext(reopened)
    new = resumed.start({})
    assert new != original
    resumed.observe_activity(True, now=0)
    resumed.observe_activity(True, now=900, force=True)
    assert reopened.session(new)["active_seconds"] == 0
    assert reopened.accumulated_active_seconds() == 60


def test_background_heartbeat_does_not_block_live_event_identity_capture(durable, monkeypatch):
    database, sessions = durable
    identifier = sessions.start({})
    entered, release, captured = Event(), Event(), Event()
    original = database.checkpoint_session_activity
    def slow_checkpoint(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        original(*args, **kwargs)
    monkeypatch.setattr(database, "checkpoint_session_activity", slow_checkpoint)
    heartbeat = Thread(target=lambda: sessions.observe_activity(True, now=1, force=True))
    targets = []
    def capture():
        targets.append(sessions.capture_event_target("created", fish(1)))
        captured.set()
    heartbeat.start()
    target_thread = Thread(target=capture)
    try:
        assert entered.wait(1)
        target_thread.start()
        assert captured.wait(.5), "Slow metadata storage must not block the frame-path identity lock"
    finally:
        release.set()
        heartbeat.join(2)
        if target_thread.ident:
            target_thread.join(2)
    assert targets == [identifier]


def test_additive_schema_migration_preserves_unmeasured_legacy_session(durable):
    database, _ = durable
    original = database.create_session({"started_at": "2026-10-01T10:00:00-04:00"})
    database.upsert_event(original, fish(7, "Class C"))
    with sqlite3.connect(database.path) as connection:
        for name in ("active_seconds", "activity_status", "heartbeat_at", "autosaved_at"):
            connection.execute(f"ALTER TABLE inspection_sessions DROP COLUMN {name}")
    reopened = InspectionDatabase(database.path)
    summary = reopened.session(original)
    assert summary["active_seconds"] is None and not summary["active_time_measured"]
    assert summary["fish_count"] == 1 and summary["grade_distribution"]["Class C"] == 1
    assert reopened.events(session_id=original)[0]["track_id"] == 7


def test_session_cards_filter_and_paginate_durable_summaries(durable):
    database, _ = durable
    for day in range(1, 4):
        identifier = database.create_session({"started_at": f"2026-11-0{day}T10:00:00-05:00"}, session_id=f"run-{day}")
        database.upsert_event(identifier, fish(day, "Class A"))
    result = app_module.get_sessions(page=2, page_size=1, start_date="2026-11-02", end_date="2026-11-03")
    assert result["total"] == 2 and result["total_pages"] == 2
    assert result["items"][0]["session_id"] == "run-2"
    assert result["items"][0]["grade_distribution"]["Class A"] == 1
    assert app_module.get_sessions(search="run-1")["total"] == 1
    with pytest.raises(HTTPException) as exc:
        app_module.get_sessions(start_date="bad-date")
    assert exc.value.status_code == 422


def test_history_verdict_reason_and_exact_fish_filters(durable):
    database, sessions = durable
    identifier = sessions.start({})
    database.upsert_event(identifier, fish(1))
    database.upsert_event(identifier, fish(10, "Class A", reason="GR_CONFIDENT", verdict="AUTO_GRADED"))
    database.upsert_event(identifier, fish(11, reason="UG_LOW_SUPPORT"))
    result = app_module.get_history(range_name="all", session_id=identifier, verdict="NEEDS_REVIEW", reason_code="UG_MISSING_HEAD")
    assert [event["track_id"] for event in result["items"]] == [1]
    exact = app_module.get_history(range_name="all", session_id=identifier, track_id=10)
    assert [event["track_id"] for event in exact["items"]] == [10]
    evidence = app_module.get_history(range_name="all", session_id=identifier, evidence_region="Head")
    assert [event["track_id"] for event in evidence["items"]] == [10]
    graded = app_module.get_history(range_name="all", session_id=identifier, grade="graded")
    assert [event["track_id"] for event in graded["items"]] == [10]


def test_analytics_uses_original_grades_and_real_anatomical_evidence(durable):
    database, sessions = durable
    identifier = sessions.start({"started_at": "2026-11-03T09:00:00-05:00"})
    event = fish(1)
    event.update(manual_override=True, manual_grade="Class A")
    database.upsert_event(identifier, event)
    database.upsert_event(identifier, fish(2, "Class B", reason="GR_CONFIDENT", verdict="AUTO_GRADED"))
    result = app_module.get_analytics(range_name="all", session_id=identifier)
    assert result["total_inspected"] == 2
    assert result["grade_distribution"]["Ungraded"] == 1
    assert result["grade_distribution"]["Class A"] == 0
    assert result["graded_rate_percent"] == 50
    assert result["anatomical_evidence"]["Body"]["count"] == 2
    assert result["anatomical_evidence"]["Head"]["rate_percent"] == 50
    assert result["ungraded_reasons"] == {"UG_MISSING_HEAD": 1}
    assert result["average_processing_time_ms"] == 12
    assert result["model_support"]["model1_detection_percent"] == 90
    assert result["session_activity"][0]["fish_count"] == 2


def test_activity_monitor_excludes_no_capture_calibration_pause_and_disconnect(monkeypatch):
    camera = SimpleNamespace(count=0, calibrating=False, debug_paused=False)
    camera._latest_frames = SimpleNamespace(snapshot=lambda: {"captured_frames": camera.count})
    camera.calibration_mode = lambda: camera.calibrating
    camera.has_live_worker = lambda: True
    status = SimpleNamespace(inspection_status="running", camera_status="connected")
    steps = [(0, False, False, "connected"), (1, False, False, "connected"),
             (2, True, False, "connected"), (3, False, True, "connected"),
             (4, False, False, "disconnected"), (5, False, False, "connected")]
    observed = []
    class Stop:
        def wait(self, _):
            if not steps:
                return True
            camera.count, camera.calibrating, camera.debug_paused, status.camera_status = steps.pop(0)
            return False
    clock = iter(range(6))
    monkeypatch.setattr(app_module, "service", camera)
    monkeypatch.setattr(app_module, "state", status)
    monkeypatch.setattr(app_module, "inspection_sessions", SimpleNamespace(observe_activity=lambda running, **_: observed.append(running)))
    monkeypatch.setattr(app_module, "monotonic", lambda: next(clock))
    app_module._session_activity_monitor(Stop())
    assert observed == [False, True, False, False, False, True]


def request(payload):
    body = json.dumps(payload).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/api/export", "headers": []}, receive)


def test_per_fish_export_requires_session_and_selects_exact_identity(durable):
    database, sessions = durable
    identifier = sessions.start({})
    database.upsert_event(identifier, fish(1, "Class B"))
    database.upsert_event(identifier, fish(10, "Class A"))
    payload = {"format": "csv", "fields": ["fish_id", "grade"], "range": "all", "session_id": identifier, "track_ids": [1]}
    response = asyncio.run(app_module.export_history(request(payload)))
    text = response.body.decode("utf-8-sig")
    assert "Class B" in text and "Class A" not in text
    payload["track_ids"] = [99]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.export_history(request(payload)))
    assert exc.value.status_code == 404
    payload.pop("session_id")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.export_history(request(payload)))
    assert exc.value.status_code == 422
