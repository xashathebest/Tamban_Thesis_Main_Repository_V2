"""Integration coverage for the durable event-persistence hand-off."""

from __future__ import annotations

import asyncio
import importlib
from threading import Event, RLock, Thread
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import InspectionState
from src.api.event_persistence import OrderedPersistenceDispatcher


app = importlib.import_module("src.api.app")


def fish(track_id: int, grade: str = "Ungraded") -> dict[str, object]:
    return {
        "track_id": track_id,
        "timestamp": "2026-10-27T12:00:00+00:00",
        "quality": grade,
        "analysis": {"final_grade": grade},
    }


@pytest.fixture
def queued_system(tmp_path, monkeypatch):
    """Give the application a small independent dispatcher and SQLite store."""

    database = InspectionDatabase(tmp_path / "events.sqlite3")
    sessions = InspectionSessionContext(database)
    service = SimpleNamespace(
        _processing_lock=RLock(),
        record_event_persistence=lambda _seconds: None,
        runtime_diagnostics=lambda: {"enabled": True, "performance": {}},
    )
    dispatcher = OrderedPersistenceDispatcher(app._persist_queued_tracking_event, capacity=8)
    monkeypatch.setattr(app, "inspection_database", database)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(app, "state", InspectionState())
    monkeypatch.setattr(app, "_session_metadata", lambda: {})
    monkeypatch.setattr(app, "event_persistence_dispatcher", dispatcher)
    try:
        yield database, sessions, dispatcher
    finally:
        # Individual blocked-write tests release their callback before return.
        shutdown = dispatcher.shutdown(timeout=2)
        assert shutdown or dispatcher.snapshot()["failed"]


def test_rotation_drains_captured_create_and_update_in_fifo_order(queued_system, monkeypatch):
    database, sessions, dispatcher = queued_system
    previous = sessions.start({})
    write_entered, release_write, rotation_done = Event(), Event(), Event()
    original_record = sessions.record_event_for

    def delayed_record(session_id, action, event):
        if action == "created":
            write_entered.set()
            assert release_write.wait(2)
        return original_record(session_id, action, event)

    monkeypatch.setattr(sessions, "record_event_for", delayed_record)
    app._enqueue_tracking_event("created", fish(4))
    assert write_entered.wait(2)
    app._enqueue_tracking_event("updated", fish(4, "Class A"))

    result: dict[str, object] = {}

    def rotate() -> None:
        try:
            result["session_id"] = app.rotate_durable_session()
        finally:
            rotation_done.set()

    rotation = Thread(target=rotate)
    rotation.start()
    try:
        assert not rotation_done.wait(.15), "rotation bypassed an in-flight durable event"
    finally:
        release_write.set()
    rotation.join(2)

    assert not rotation.is_alive()
    assert isinstance(result.get("session_id"), str) and result["session_id"] != previous
    assert database.session(previous)["ended_at"] is not None
    assert [(item["track_id"], item["quality"]) for item in database.events(session_id=previous)] == [(4, "Class A")]
    assert database.events(session_id=result["session_id"]) == []
    assert dispatcher.snapshot()["completed"] == 2


def test_slow_target_write_does_not_block_active_target_capture_or_healthy_enqueue(queued_system, monkeypatch):
    database, sessions, dispatcher = queued_system
    session_id = sessions.start({})
    write_entered, release_write = Event(), Event()
    original_record = sessions.record_event_for

    def delayed_record(target, action, event):
        if event["track_id"] == 1:
            write_entered.set()
            assert release_write.wait(2)
        return original_record(target, action, event)

    monkeypatch.setattr(sessions, "record_event_for", delayed_record)
    app._enqueue_tracking_event("created", fish(1))
    assert write_entered.wait(2)

    started = monotonic()
    assert sessions.capture_event_target("created", fish(2)) == session_id
    capture_elapsed = monotonic() - started
    started = monotonic()
    app._enqueue_tracking_event("created", fish(2))
    enqueue_elapsed = monotonic() - started

    try:
        assert capture_elapsed < .2
        assert enqueue_elapsed < .2
    finally:
        release_write.set()
    assert dispatcher.drain(timeout=2)
    assert {item["track_id"] for item in database.events(session_id=session_id)} == {1, 2}


def test_manual_review_waits_for_queued_update_before_its_direct_write(queued_system, monkeypatch):
    database, sessions, dispatcher = queued_system
    session_id = sessions.start({})
    app._persist_tracking_event("created", fish(8))
    update_entered, release_update, review_finished = Event(), Event(), Event()
    original_record = sessions.record_event_for

    def delayed_record(target, action, event):
        if action == "updated":
            update_entered.set()
            assert release_update.wait(2)
        return original_record(target, action, event)

    monkeypatch.setattr(sessions, "record_event_for", delayed_record)
    app._enqueue_tracking_event("updated", fish(8, "Class B"))
    assert update_entered.wait(2)
    outcome: dict[str, object] = {}

    class ReviewRequest:
        async def json(self):
            return {"manual_grade": "A", "reviewer": "operator"}

    def review() -> None:
        try:
            outcome["result"] = asyncio.run(app.review_fish(8, ReviewRequest()))
        finally:
            review_finished.set()

    reviewer = Thread(target=review)
    reviewer.start()
    try:
        assert not review_finished.wait(.15), "manual review bypassed the queued update barrier"
    finally:
        release_update.set()
    reviewer.join(2)

    assert not reviewer.is_alive()
    assert outcome["result"]["updated"] is True
    assert dispatcher.drain(timeout=2)
    stored = database.events(session_id=session_id)[0]
    assert stored["quality"] == "Class B"
    assert stored["manual_override"] is True
    assert stored["manual_grade"] == "Class A"


def test_export_waits_for_queued_event_before_reading_its_snapshot(queued_system, monkeypatch):
    _, sessions, _ = queued_system
    sessions.start({})
    write_entered, release_write, export_finished = Event(), Event(), Event()
    original_record = sessions.record_event_for

    def delayed_record(target, action, event):
        if action == "created":
            write_entered.set()
            assert release_write.wait(2)
        return original_record(target, action, event)

    monkeypatch.setattr(sessions, "record_event_for", delayed_record)
    app._enqueue_tracking_event("created", fish(9, "Class A"))
    assert write_entered.wait(2)
    outcome: dict[str, object] = {}

    class ExportRequest:
        async def json(self):
            return {"format": "csv", "fields": ["fish_id", "timestamp", "grade"]}

    def export() -> None:
        try:
            outcome["response"] = asyncio.run(app.export_history(ExportRequest()))
        finally:
            export_finished.set()

    exporter = Thread(target=export)
    exporter.start()
    try:
        assert not export_finished.wait(.15), "export bypassed queued durable writes"
    finally:
        release_write.set()
    exporter.join(2)

    assert not exporter.is_alive()
    response = outcome["response"]
    assert b"Fish #9" in response.body


def test_runtime_diagnostics_include_bounded_event_queue_health(queued_system):
    _, _, dispatcher = queued_system
    diagnostics = app._runtime_diagnostics_payload()

    assert diagnostics["event_persistence_drained"] is True
    assert diagnostics["event_persistence_queue"]["capacity"] == 8
    assert diagnostics["event_persistence_queue"]["pending"] == 0
    assert diagnostics["event_persistence_queue"]["failed"] is False
    assert dispatcher.snapshot()["worker_alive"] is True


def test_enqueue_exception_marks_inspection_unhealthy(queued_system, monkeypatch):
    _, sessions, _ = queued_system
    sessions.start({})
    stopped = []
    service = SimpleNamespace(
        _processing_lock=RLock(),
        request_stop_after_current_frame=stopped.append,
    )
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(
        app,
        "_event_persistence_dispatcher_for_submit",
        lambda: (_ for _ in ()).throw(OSError("dispatcher thread unavailable")),
    )

    app._enqueue_tracking_event("created", fish(12))

    assert len(stopped) == 1
    assert "dispatcher thread unavailable" in stopped[0]


def test_retained_writer_failure_keeps_session_open_and_blocks_restart(queued_system, monkeypatch):
    _, sessions, dispatcher = queued_system
    session_id = sessions.start({})

    def failing_record(_target, _action, _event):
        raise OSError("SQLite storage unavailable")

    monkeypatch.setattr(sessions, "record_event_for", failing_record)
    app._enqueue_tracking_event("created", fish(14))
    assert dispatcher.drain(timeout=2) is False
    assert dispatcher.snapshot()["failed"] is True

    with pytest.raises(HTTPException) as rotation:
        app.rotate_durable_session()
    assert rotation.value.status_code == 503
    assert sessions.active and sessions.session_id == session_id

    monkeypatch.setattr(app, "service", SimpleNamespace(has_live_worker=lambda: False))
    with pytest.raises(HTTPException) as restart:
        app.start_inspection()
    assert restart.value.status_code == 503
    assert app.state.snapshot()["inspection_status"] == "errored"


def test_camera_policy_change_stops_if_durable_rotation_cannot_complete(queued_system, monkeypatch):
    _, sessions, _ = queued_system
    sessions.start({})
    reset, stopped = Event(), []
    service = SimpleNamespace(
        _processing_lock=RLock(),
        reset_active_policy_evidence=reset.set,
        request_stop_after_current_frame=stopped.append,
    )
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(
        app,
        "_rotate_durable_session_locked",
        lambda: (_ for _ in ()).throw(HTTPException(status_code=409, detail="queue still flushing")),
    )

    with pytest.raises(HTTPException, match="queue still flushing"):
        app._record_camera_policy_change({"changed": True})

    assert reset.is_set()
    assert len(stopped) == 1
    assert "durable session rotation did not complete" in stopped[0]


def test_camera_policy_change_stops_on_rotation_storage_error(queued_system, monkeypatch):
    _, sessions, _ = queued_system
    sessions.start({})
    stopped = []
    service = SimpleNamespace(
        _processing_lock=RLock(),
        reset_active_policy_evidence=lambda: None,
        request_stop_after_current_frame=stopped.append,
    )
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(
        app,
        "_rotate_durable_session_locked",
        lambda: (_ for _ in ()).throw(OSError("SQLite disk I/O error")),
    )

    with pytest.raises(OSError, match="disk I/O"):
        app._record_camera_policy_change({"changed": True})

    assert len(stopped) == 1
    assert "SQLite disk I/O error" in stopped[0]
