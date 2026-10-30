"""Tracker choice and its session provenance must be explicit."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from src.api import app
from src.api.camera import CameraInspectionService
from src.api.database import InspectionDatabase, InspectionSessionContext
from src.api.domain import InspectionState
from src.inference.fish_detector import _ByteTrackInput
from src.inference.yolo_fish_detector import FishDetection, YoloFishDetector, _IoUTracker


def detector(tmp_path, **options):
    weights = tmp_path / "detector.pt"
    weights.write_bytes(b"stub")
    return YoloFishDetector(weights, device="cpu", model_factory=lambda _: SimpleNamespace(task="detect", names={0: "item"}), **options)


def test_missing_lap_uses_visible_warning(tmp_path, monkeypatch):
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: None)
    model = detector(tmp_path)
    assert model.load()
    assert isinstance(model._tracker, _IoUTracker)
    assert "fallback" in model.tracker_backend.lower()
    assert "ByteTrack" in model.tracker_warning


def test_strict_bytetrack_fails_without_lap(tmp_path, monkeypatch):
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: None)
    model = detector(tmp_path, require_bytetrack=True)
    assert not model.load() and model.model is None
    assert "lap" in model.error and "ByteTrack" in model.error


def test_available_bytetrack_is_reported(tmp_path, monkeypatch):
    tracker = MagicMock()
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: object())
    monkeypatch.setattr("src.inference.yolo_fish_detector.import_module", lambda _: SimpleNamespace(lapjv=lambda *args, **kwargs: None))
    monkeypatch.setattr("src.inference.yolo_fish_detector._default_tracker_factory", lambda _: tracker)
    model = detector(tmp_path)
    assert model.load() and model._tracker is tracker
    assert model.tracker_backend == "ByteTrack" and model.tracker_warning is None


def test_unloadable_lap_uses_visible_fallback_without_initializing_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: object())
    def unavailable(_name):
        raise ImportError("incompatible native wheel")
    monkeypatch.setattr("src.inference.yolo_fish_detector.import_module", unavailable)
    tracker_factory = MagicMock()
    monkeypatch.setattr("src.inference.yolo_fish_detector._default_tracker_factory", tracker_factory)
    model = detector(tmp_path)
    assert model.load()
    assert isinstance(model._tracker, _IoUTracker)
    assert "failed to load" in model.tracker_backend
    assert "incompatible native wheel" in model.tracker_warning
    tracker_factory.assert_not_called()


def test_strict_bytetrack_fails_when_lap_cannot_load(tmp_path, monkeypatch):
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: object())
    def unavailable(_name):
        raise ImportError("incompatible native wheel")
    monkeypatch.setattr("src.inference.yolo_fish_detector.import_module", unavailable)
    model = detector(tmp_path, require_bytetrack=True)
    assert not model.load() and model.model is None
    assert "lap" in model.error and "incompatible native wheel" in model.error


def test_fallback_does_not_assign_one_id_twice_on_overlapping_boxes():
    tracker = _IoUTracker()
    frames = [
        [FishDetection((0, 0, 20, 20), .9), FishDetection((30, 0, 50, 20), .9)],
        [FishDetection((4, 0, 24, 20), .9), FishDetection((26, 0, 46, 20), .9)],
        [FishDetection((10, 0, 30, 20), .9), FishDetection((20, 0, 40, 20), .9)],
    ]
    for frame in frames:
        ids = tracker.update(_ByteTrackInput(frame), np.zeros((32, 64, 3), dtype=np.uint8))[:, 4].tolist()
        assert len(ids) == len(set(ids)) == 2


def test_tracker_returns_each_raw_detection_once_including_unconfirmed_fish(tmp_path):
    model = detector(tmp_path)
    raw = [FishDetection((0, 0, 20, 20), .9), FishDetection((5, 0, 25, 20), .8)]
    model.detect = lambda _frame: raw
    model._tracker = SimpleNamespace(update=lambda _detections, _frame: np.asarray([
        [*raw[0].bbox, 7, .9, 0, 0], [*raw[0].bbox, 7, .9, 0, 0],
    ]))
    detections = model.predict(np.zeros((32, 32, 3), dtype=np.uint8))
    assert [(item.bbox, item.track_id) for item in detections] == [(raw[0].bbox, 7), (raw[1].bbox, None)]


def test_conflicting_tracker_assignments_are_left_untracked(tmp_path):
    model = detector(tmp_path)
    raw = [FishDetection((0, 0, 20, 20), .9), FishDetection((5, 0, 25, 20), .8)]
    model.detect = lambda _frame: raw
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    for rows in (
        [[*raw[0].bbox, 7, .9, 0, 0], [*raw[0].bbox, 8, .9, 0, 0]],
        [[*raw[0].bbox, 7, .9, 0, 0], [*raw[1].bbox, 7, .8, 0, 1]],
    ):
        model._tracker = SimpleNamespace(update=lambda _detections, _frame: np.asarray(rows))
        assert all(item.track_id is None for item in model.predict(frame))


def test_live_status_contains_tracker_backend_and_warning(monkeypatch):
    monkeypatch.setattr(app.model, "tracker_backend", "IoU fallback")
    monkeypatch.setattr(app.model, "tracker_warning", "ByteTrack is unavailable")
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(session_id=None, active=False))
    monkeypatch.setattr(app, "inspection_database", SimpleNamespace(event_revision=lambda _: None))
    status = app.get_live_status()
    assert status["tracker_backend"] == "IoU fallback"
    assert status["tracker_warning"] == "ByteTrack is unavailable"


def test_model_preparation_precedes_session_snapshot(tmp_path, monkeypatch):
    database = InspectionDatabase(tmp_path / "history.sqlite3")
    sessions = InspectionSessionContext(database)
    model = SimpleNamespace(tracker_backend="unresolved")
    def prepare():
        model.tracker_backend = "IoU fallback"
        return True
    service = SimpleNamespace(has_live_worker=lambda: False, prepare_models=prepare, start=lambda: True)
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "_session_metadata", lambda: {"tracker_backend": model.tracker_backend})
    monkeypatch.setattr(app, "_status_payload", lambda: {})
    assert app.start_inspection()["started"]
    assert database.session(sessions.session_id)["tracker_backend"] == "IoU fallback"


def test_strict_tracker_failure_does_not_open_session(tmp_path, monkeypatch):
    monkeypatch.setattr("src.inference.yolo_fish_detector.find_spec", lambda _: None)
    model = detector(tmp_path, require_bytetrack=True)
    service = CameraInspectionService(InspectionState(), model)
    database = InspectionDatabase(tmp_path / "history.sqlite3")
    sessions = InspectionSessionContext(database)
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "_status_payload", lambda: {})
    assert app.start_inspection()["started"] is False
    assert not service.has_live_worker() and sessions.session_id is None
    assert database.sessions() == []


def test_thread_start_exception_leaves_no_worker_or_open_session(tmp_path, monkeypatch):
    import pytest
    database = InspectionDatabase(tmp_path / "history.sqlite3")
    sessions = InspectionSessionContext(database)
    model = SimpleNamespace(model=object(), reset_tracker=lambda: None)
    service = CameraInspectionService(InspectionState(), model)
    class FailedThread:
        def __init__(self, **_kwargs):
            pass
        def start(self):
            raise RuntimeError("thread unavailable")
    monkeypatch.setattr("src.api.camera.Thread", FailedThread)
    monkeypatch.setattr(app, "service", service)
    monkeypatch.setattr(app, "inspection_sessions", sessions)
    monkeypatch.setattr(app, "_session_metadata", lambda: {})
    monkeypatch.setattr(app, "_status_payload", lambda: {})
    with pytest.raises(RuntimeError, match="thread unavailable"):
        app.start_inspection()
    assert not service.has_live_worker() and not sessions.active
    assert database.session(sessions.session_id)["ended_at"] is not None
