"""Stop requests must report a worker that is still finishing truthfully."""
from threading import Event
from time import monotonic
from types import SimpleNamespace

from src.api.camera import CameraInspectionService
from src.api.domain import InspectionState


class FakeModel:
    model = object()

    def reset_tracker(self):
        pass


def test_timeout_reports_stopping_and_finalizes_after_worker_exits(monkeypatch):
    state = InspectionState()
    service = CameraInspectionService(state, FakeModel())
    entered, release, finalized = Event(), Event(), Event()
    def run():
        state.mark_running()
        entered.set()
        release.wait(5)
    monkeypatch.setattr(service, "_run", run)
    service.on_worker_exit = finalized.set
    try:
        assert service.start() and entered.wait(2)
        assert service.stop(timeout=0.01) is False
        assert state.snapshot()["inspection_status"] == "stopping"
        assert service.has_live_worker()
        assert service.start() is False
        assert service.stop(timeout=0.01) is False
        assert not finalized.is_set()
    finally:
        release.set()
    assert finalized.wait(2) and service._finalized.wait(2)
    assert not service.has_live_worker()
    assert state.snapshot()["inspection_status"] == "stopped"


def test_stop_endpoint_does_not_claim_success_for_live_worker(monkeypatch):
    import importlib
    app = importlib.import_module("src.api.app")
    worker = SimpleNamespace(stop=lambda: True, has_live_worker=lambda: True)
    monkeypatch.setattr(app, "service", worker)
    monkeypatch.setattr(app, "_status_payload", lambda: {"inspection_status": "stopping"})
    assert app.stop_inspection()["stopped"] is False


def test_blocked_cleanup_does_not_block_stop_or_allow_restart(monkeypatch):
    state = InspectionState()
    service = CameraInspectionService(state, FakeModel())
    cleanup_entered, release_cleanup = Event(), Event()
    monkeypatch.setattr(service, "_run", lambda: None)
    def cleanup():
        cleanup_entered.set()
        release_cleanup.wait(5)
    service.on_worker_exit = cleanup
    try:
        assert service.start()
        started = monotonic()
        assert service.stop(timeout=0.05) is False
        assert monotonic() - started < 1
        assert cleanup_entered.wait(1)
        assert service.has_live_worker() and not service.start()
    finally:
        release_cleanup.set()
    assert service._finalized.wait(2)


def test_timeout_closes_durable_session_only_after_worker_exit(tmp_path, monkeypatch):
    import importlib
    from src.api.database import InspectionDatabase, InspectionSessionContext
    app = importlib.import_module("src.api.app")
    database = InspectionDatabase(tmp_path / "history.sqlite3")
    sessions = InspectionSessionContext(database)
    service = CameraInspectionService(InspectionState(), FakeModel())
    entered, release = Event(), Event()
    def run():
        service.state.mark_running()
        entered.set()
        release.wait(5)
    monkeypatch.setattr(service, "_run", run)
    service.on_worker_exit = app._close_worker_session
    stop = service.stop
    monkeypatch.setattr(service, "stop", lambda: stop(timeout=0.01))
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(app, "inspection_database", database)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "_session_metadata", lambda: {})
    monkeypatch.setattr(app, "_camera_settings_snapshot", lambda: {})
    monkeypatch.setattr(app, "_status_payload", lambda: service.state.snapshot())
    try:
        assert app.start_inspection()["started"] and entered.wait(2)
        session_id = sessions.session_id
        response = app.stop_inspection()
        assert not response["stopped"] and response["inspection_status"] == "stopping"
        assert sessions.active and database.session(session_id)["ended_at"] is None
        assert not app.start_inspection()["started"]
    finally:
        release.set()
    assert service._finalized.wait(2)
    assert not sessions.active and database.session(session_id)["ended_at"] is not None
    assert service.state.snapshot()["inspection_status"] == "stopped"


def test_worker_camera_error_closes_session_without_stop_request(monkeypatch):
    state = InspectionState()
    service = CameraInspectionService(state, FakeModel())
    finalized = Event()
    service.on_worker_exit = finalized.set
    monkeypatch.setattr(service, "_open_capture", lambda cv2: (None, "Unavailable"))
    assert service.start()
    assert finalized.wait(3) and service._finalized.wait(3)
    assert not service.has_live_worker()
    assert state.snapshot()["inspection_status"] == "errored"
