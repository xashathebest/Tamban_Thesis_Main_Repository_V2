"""Regression checks for acquisition truthfulness and stale feed cleanup."""

from threading import Event
from time import monotonic, sleep
import cv2
import numpy as np
import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import InspectionState


class FakeModel:
    model = object()

    def reset_tracker(self):
        pass


def test_loaded_tracker_reports_ready_while_camera_is_stopped():
    state = InspectionState()
    assert state.snapshot()["tracker_status"] == "checking"

    state.mark_tracker_ready()
    snapshot = state.snapshot()

    assert snapshot["inspection_status"] == "stopped"
    assert snapshot["camera_status"] == "disconnected"
    assert snapshot["tracker_status"] == "ready"


def wait_until(predicate, timeout=3):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("Condition was not reached before the timeout")


def test_running_and_feed_wait_for_first_frame_and_restart_discards_old_frame(monkeypatch):
    state = InspectionState()
    service = CameraInspectionService(state, FakeModel())
    opened = []

    class Capture:
        def __init__(self):
            self.first_read_started = Event()
            self.deliver_first_frame = Event()
            self.read_count = 0
            self.released = False

        def read(self):
            self.read_count += 1
            if self.read_count == 1:
                self.first_read_started.set()
                assert self.deliver_first_frame.wait(3)
                return True, np.zeros((8, 8, 3), dtype=np.uint8)
            service._stop_event.wait(3)
            return False, None

        def release(self):
            self.released = True

    def open_capture(_cv2):
        capture = Capture()
        opened.append(capture)
        return capture, "test camera"

    monkeypatch.setattr(service, "_open_capture", open_capture)
    monkeypatch.setattr(service.camera_controls, "attach", lambda *args: None)
    monkeypatch.setattr(service.camera_controls, "detach", lambda *args: None)
    monkeypatch.setattr(service.camera_controls, "load_camera_profile", lambda: {"success": True})
    monkeypatch.setattr(service, "process_frame", lambda frame, _cv2: frame)
    try:
        assert service.start()
        wait_until(lambda: bool(opened) and opened[0].first_read_started.is_set())
        assert state.snapshot()["inspection_status"] == "starting"
        assert state.snapshot()["camera_status"] == "connecting"
        assert state.frame()[0] is None
        opened[0].deliver_first_frame.set()
        wait_until(lambda: state.frame()[0] is not None)
        assert state.snapshot()["inspection_status"] == "running"
        assert service.stop(timeout=2)
        assert opened[0].released
        assert state.frame()[0] is None

        assert service.start()
        wait_until(lambda: len(opened) == 2 and opened[1].first_read_started.is_set())
        assert state.snapshot()["inspection_status"] == "starting"
        assert state.frame()[0] is None
    finally:
        for capture in opened:
            capture.deliver_first_frame.set()
        service.stop(timeout=3)
    assert all(capture.released for capture in opened)


@pytest.mark.parametrize("result", [(False, None), (True, None), RuntimeError("driver failed")])
def test_failed_read_sets_error_and_stops_worker(result):
    state = InspectionState()
    assert state.begin_start()
    service = CameraInspectionService(state, FakeModel(), camera_index=4)

    class Capture:
        def read(self):
            if isinstance(result, Exception):
                raise result
            return result

    service._capture_frames(Capture())
    snapshot = state.snapshot()
    assert snapshot["inspection_status"] == "errored"
    assert "Camera 4" in snapshot["message"]
    if isinstance(result, Exception):
        assert "driver failed" in snapshot["message"]
    assert service._stop_event.is_set()


def test_failed_read_after_stop_does_not_overwrite_stopping_status():
    state = InspectionState()
    assert state.begin_start()
    service = CameraInspectionService(state, FakeModel())

    class Capture:
        def read(self):
            service._stop_event.set()
            state.mark_stopping()
            raise RuntimeError("capture interrupted during stop")

    service._capture_frames(Capture())
    assert state.snapshot()["inspection_status"] == "stopping"


def test_reset_rejects_frame_encoded_from_previous_session(monkeypatch):
    state = InspectionState()
    service = CameraInspectionService(state, FakeModel())
    encoder_started, release_encoder, publication_attempted = Event(), Event(), Event()
    original_encode, original_publish = cv2.imencode, state.publish_frame

    class Capture:
        def __init__(self):
            self.first = True

        def read(self):
            if self.first:
                self.first = False
                return True, np.zeros((8, 8, 3), dtype=np.uint8)
            service._stop_event.wait(3)
            return False, None

        def release(self):
            pass

    def slow_encode(*args):
        encoder_started.set()
        assert release_encoder.wait(3)
        return original_encode(*args)

    def publish(*args, **kwargs):
        original_publish(*args, **kwargs)
        publication_attempted.set()

    monkeypatch.setattr(service, "_open_capture", lambda _cv2: (Capture(), "test camera"))
    monkeypatch.setattr(service.camera_controls, "attach", lambda *args: None)
    monkeypatch.setattr(service.camera_controls, "detach", lambda *args: None)
    monkeypatch.setattr(service.camera_controls, "load_camera_profile", lambda: {"success": True})
    monkeypatch.setattr(service, "process_frame", lambda frame, _cv2: frame)
    monkeypatch.setattr(cv2, "imencode", slow_encode)
    monkeypatch.setattr(state, "publish_frame", publish)
    try:
        assert service.start() and encoder_started.wait(3)
        service.reset_session()
        release_encoder.set()
        assert publication_attempted.wait(3)
        assert state.frame()[0] is None
        assert state.snapshot()["inspection_status"] == "running"
    finally:
        release_encoder.set()
        service.stop(timeout=3)


@pytest.mark.parametrize("transition", ["mark_stopping", "mark_stopped", "mark_error"])
def test_stop_or_error_discards_frame_and_rejects_late_publication(transition):
    state = InspectionState()
    assert state.begin_start()
    state.mark_running()
    state.publish_frame(b"old", 7)
    assert state.frame()[0] == b"old"
    getattr(state, transition)("camera failed") if transition == "mark_error" else getattr(state, transition)()
    state.publish_frame(b"late", 9)
    assert state.frame()[0] is None
    assert state.snapshot()["fps"] != 9
