"""Durable events must remain attached to the worker session that emitted them."""
from __future__ import annotations

import importlib
from threading import Event, RLock, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.api.database import InspectionDatabase, InspectionSessionContext

app_module = importlib.import_module("src.api.app")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    database = InspectionDatabase(tmp_path / "events.sqlite3")
    sessions = InspectionSessionContext(database)
    monkeypatch.setattr(app_module, "inspection_database", database)
    monkeypatch.setattr(app_module, "inspection_sessions", sessions)
    monkeypatch.setattr(app_module, "_session_metadata", lambda: {})
    monkeypatch.setattr(app_module, "_status_payload", lambda: {})
    monkeypatch.setattr(app_module, "_camera_settings_snapshot", lambda: {})
    return database, sessions


def event(track_id):
    return {"track_id": track_id, "timestamp": "2026-01-01T00:00:00+00:00", "quality": "Ungraded", "analysis": {}}


def test_first_event_is_recorded_in_new_session_before_worker_returns(isolated, monkeypatch):
    database, sessions = isolated
    old = sessions.start({})
    sessions.close()
    def start():
        app_module._persist_tracking_event("created", event(1))
        return True
    worker = SimpleNamespace(start=start, has_live_worker=lambda: False, prepare_models=lambda: True)
    monkeypatch.setattr(app_module, "service", worker)
    assert app_module.start_inspection()["started"] is True
    new = sessions.session_id
    assert new != old
    assert database.events(session_id=old) == []
    assert [row["track_id"] for row in database.events(session_id=new)] == [1]


def test_duplicate_start_does_not_rotate_active_worker_session(isolated, monkeypatch):
    database, sessions = isolated
    current = sessions.start({})
    start = MagicMock(return_value=False)
    monkeypatch.setattr(app_module, "service", SimpleNamespace(start=start, has_live_worker=lambda: True))
    assert app_module.start_inspection()["started"] is False
    assert sessions.active and sessions.session_id == current
    assert len(database.sessions()) == 1
    start.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_start_closes_new_session(isolated, monkeypatch, raises):
    database, sessions = isolated
    def start():
        if raises:
            raise RuntimeError("start failed")
        return False
    monkeypatch.setattr(app_module, "service", SimpleNamespace(start=start, has_live_worker=lambda: False, prepare_models=lambda: True))
    if raises:
        with pytest.raises(RuntimeError, match="start failed"):
            app_module.start_inspection()
    else:
        assert app_module.start_inspection()["started"] is False
    assert not sessions.active
    assert database.session(sessions.session_id)["ended_at"] is not None


def test_failed_session_creation_never_starts_worker(isolated, monkeypatch):
    database, sessions = isolated
    monkeypatch.setattr(database, "create_session", MagicMock(side_effect=OSError("storage failed")))
    start = MagicMock()
    monkeypatch.setattr(app_module, "service", SimpleNamespace(start=start, has_live_worker=lambda: False, prepare_models=lambda: True))
    with pytest.raises(OSError, match="storage failed"):
        app_module.start_inspection()
    assert not sessions.active
    start.assert_not_called()


def test_stop_timeout_keeps_session_open_for_final_worker_event(isolated, monkeypatch):
    database, sessions = isolated
    current = sessions.start({})
    monkeypatch.setattr(app_module, "service", SimpleNamespace(stop=lambda: True, has_live_worker=lambda: True))
    app_module.stop_inspection()
    assert sessions.active and database.session(current)["ended_at"] is None
    app_module._persist_tracking_event("created", event(2))
    assert [row["track_id"] for row in database.events(session_id=current)] == [2]


def test_closed_session_accepts_existing_updates_but_not_new_events(isolated):
    database, sessions = isolated
    current = sessions.start({})
    app_module._persist_tracking_event("created", event(1))
    sessions.close()
    app_module._persist_tracking_event("created", event(2))
    updated = {**event(1), "quality": "Class A"}
    app_module._persist_tracking_event("updated", updated)
    assert [(row["track_id"], row["quality"]) for row in database.events(session_id=current)] == [(1, "Class A")]


def test_rapid_restart_closes_exited_worker_session_before_first_event(isolated, monkeypatch):
    database, sessions = isolated
    previous = sessions.start({})
    app_module._persist_tracking_event("created", event(1))
    def start():
        app_module._persist_tracking_event("created", event(2))
        return True
    monkeypatch.setattr(app_module, "service", SimpleNamespace(start=start, has_live_worker=lambda: False, prepare_models=lambda: True))
    app_module.start_inspection()
    assert database.session(previous)["ended_at"] is not None
    assert [row["track_id"] for row in database.events(session_id=previous)] == [1]
    assert [row["track_id"] for row in database.events(session_id=sessions.session_id)] == [2]


def test_rotation_creation_failure_preserves_open_previous_session(isolated, monkeypatch):
    database, sessions = isolated
    previous = sessions.start({})
    monkeypatch.setattr(database, "create_session", MagicMock(side_effect=OSError("storage failed")))
    with pytest.raises(OSError, match="storage failed"):
        sessions.rotate({})
    assert sessions.active and sessions.session_id == previous
    assert database.session(previous)["ended_at"] is None


def test_reset_waits_for_in_flight_frame_before_rotating(isolated, monkeypatch):
    database, sessions = isolated
    previous = sessions.start({})
    processing = RLock()
    resetting = Event()
    worker = SimpleNamespace(_processing_lock=processing, reset_session=lambda: resetting.set())
    monkeypatch.setattr(app_module, "service", worker)
    with processing:
        thread = Thread(target=app_module.reset_session)
        thread.start()
        assert not resetting.wait(0.1)
        app_module._persist_tracking_event("created", event(1))
    thread.join(timeout=2)
    assert not thread.is_alive() and resetting.is_set()
    assert sessions.session_id != previous
    assert [row["track_id"] for row in database.events(session_id=previous)] == [1]
    assert database.events(session_id=sessions.session_id) == []
