"""EV changes affect presentation without changing camera ownership or grading pixels."""
from __future__ import annotations

import asyncio
import importlib
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from src.api.camera import CameraInspectionService
from src.api.camera_controls import CameraControlError
from src.api.domain import Detection, InspectionState
from src.inference.yolo_quality_model import FishQualityObservation, YoloQualityModel


class Capture:
    """Small DirectShow-like device whose manual writes disable automatic exposure."""

    def __init__(self):
        self.values = {
            cv2.CAP_PROP_FRAME_WIDTH: 64.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 48.0,
            cv2.CAP_PROP_FPS: 30.0,
            cv2.CAP_PROP_EXPOSURE: -6.0,
            cv2.CAP_PROP_AUTO_EXPOSURE: 1.0,
        }
        self.writes = []
        self.released = False

    def get(self, key):
        return self.values.get(key, float("nan"))

    def set(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value
        if key == cv2.CAP_PROP_EXPOSURE:
            self.values[cv2.CAP_PROP_AUTO_EXPOSURE] = 0.0
        return True

    def release(self):
        self.released = True


class Detector:
    model = object()

    def __init__(self):
        self.frames = []

    def predict(self, frame):
        self.frames.append(frame.copy())
        return [Detection(0, "Fish", .99, (8, 8, 56, 40), 1)]

    def reset_tracker(self):
        pass


class Quality:
    model = object()

    def __init__(self):
        self.crops = []

    def predict(self, crop, track_id):
        self.crops.append(crop.copy())
        return FishQualityObservation(track_id, None, None, (), {}, {
            "final_grade": "Ungraded", "final_score": None,
            "verdict_status": "NEEDS_REVIEW", "model2_available": True,
        })

    def reset_tracks(self):
        pass


@pytest.fixture
def connected(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    service = CameraInspectionService(
        InspectionState(), Detector(), camera_profile_path=tmp_path / "camera.yaml",
    )
    capture = Capture()
    service.camera_controls.attach(capture, cv2, "DSHOW")
    return service, capture


@pytest.mark.parametrize("locked", [False, True])
def test_live_ev_uses_preview_only_and_preserves_tracking(connected, locked):
    service, capture = connected
    service._camera_locked = locked
    before_generation = service.state.frame_generation()
    service._frame_index = 12

    result = service.update_camera_exposure({"mode": "manual", "ev": 1.5})

    assert result["success"] and not result["changed"]
    assert result["exposure"]["source"] == "software"
    assert result["exposure"]["hardware_allowed"] is False
    assert capture.writes == []
    assert service._frame_index == 12
    assert service.state.frame_generation() == before_generation
    assert service.camera_status()["exposure"]["ev"] == 1.5


def test_disconnected_camera_rejects_exposure(connected):
    service, capture = connected
    service.camera_controls.detach(capture)
    with pytest.raises(CameraControlError, match="Start"):
        service.update_camera_exposure({"mode": "manual", "ev": 1})


def test_native_ev_requires_calibration_and_restores_automatic_mode(connected):
    service, capture = connected
    service.set_calibration_mode(True)

    manual = service.update_camera_exposure({"mode": "manual", "ev": 1.0})

    assert manual["success"] and manual["changed"]
    assert manual["exposure"]["source"] == "native"
    assert capture.values[cv2.CAP_PROP_EXPOSURE] == -5.0
    assert capture.values[cv2.CAP_PROP_AUTO_EXPOSURE] == 0.0
    auto = service.update_camera_exposure({"mode": "auto"})
    assert auto["success"] and auto["changed"]
    assert capture.values[cv2.CAP_PROP_AUTO_EXPOSURE] == 1.0


@pytest.mark.parametrize("ending_ev, expected_exposure", [(1.0, -5.0), (.2, -6.0)])
def test_leaving_calibration_adopts_native_setting_without_later_restoration(connected, ending_ev, expected_exposure):
    service, capture = connected
    service.set_calibration_mode(True)
    service.update_camera_exposure({"mode": "manual", "ev": 1.0})
    service.update_camera_exposure({"mode": "manual", "ev": ending_ev})
    service.set_calibration_mode(False)
    capture.writes.clear()

    service.update_camera_exposure({"mode": "manual", "ev": -.5})
    reset = service.update_camera_exposure({"reset": True})

    assert reset["success"] and not reset["changed"]
    assert reset["exposure"]["ev"] == 0
    assert capture.writes == []
    assert capture.values[cv2.CAP_PROP_EXPOSURE] == expected_exposure


def test_locking_native_exposure_prevents_later_reset_hardware_writes(connected):
    service, capture = connected
    service.set_calibration_mode(True)
    service.update_camera_exposure({"mode": "manual", "ev": 1.0})
    service.lock_camera_settings(True)
    capture.writes.clear()

    service.update_camera_exposure({"mode": "manual", "ev": -1})
    reset = service.update_camera_exposure({"reset": True})

    assert reset["success"] and not reset["changed"]
    assert capture.writes == []
    assert capture.values[cv2.CAP_PROP_EXPOSURE] == -5.0


def test_legacy_exposure_change_discards_previous_ev_baseline(connected):
    service, capture = connected
    service.set_calibration_mode(True)
    service.update_camera_exposure({"mode": "manual", "ev": 1.0})

    changed = service.update_camera_settings({"exposure": -4.0})
    capture.writes.clear()
    service.update_camera_exposure({"reset": True})

    assert changed["success"]
    assert service.camera_status()["exposure"]["ev"] == 0
    assert capture.writes == []
    assert capture.values[cv2.CAP_PROP_EXPOSURE] == -4.0


def wait_until(predicate, timeout=4):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(.01)
    raise AssertionError("Camera worker did not reach the expected state")


def test_worker_enhances_jpeg_after_detection_and_grading_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    state, detector, quality = InspectionState(), Detector(), Quality()
    service = CameraInspectionService(
        state, detector, quality_model=quality, quality_interval=1,
        camera_profile_path=tmp_path / "camera.yaml",
    )
    frame = np.full((48, 64, 3), (28, 55, 82), dtype=np.uint8)
    first_frame = Event()

    class WorkerCapture(Capture):
        def __init__(self):
            super().__init__()
            self.first = True

        def read(self):
            if self.first:
                self.first = False
                assert first_frame.wait(4)
                return True, frame
            # Each read holds the camera control lock. Keep returning promptly
            # so calibration statistics can read settings between captures.
            service._stop_event.wait(.02)
            return True, frame.copy()

    capture = WorkerCapture()
    raw_frames, encoded_frames = [], []
    original_encode = cv2.imencode
    original_apply = service.camera_exposure.apply

    def encode(extension, image, options):
        encoded_frames.append(image.copy())
        return original_encode(extension, image, options)

    def initialize():
        # Configure before the fake read holds the shared capture lock waiting
        # for its first frame. Real drivers also serialize reads and controls.
        service.update_camera_exposure({"mode": "manual", "ev": 2.0})
        return {"success": True}

    monkeypatch.setattr(service, "_open_capture", lambda _: (capture, "DSHOW"))
    monkeypatch.setattr(service.camera_controls, "initialize_camera_settings", initialize)
    monkeypatch.setattr(service.raw_preview, "offer", lambda image, _: raw_frames.append(image.copy()))
    # Use a settled display timestamp; smoothing itself is tested by the controller suite.
    monkeypatch.setattr(service.camera_exposure, "apply", lambda image: original_apply(image, now=monotonic() + 10))
    monkeypatch.setattr(cv2, "imencode", encode)
    service._models_prepared = True
    try:
        assert service.start()
        first_frame.set()
        wait_until(lambda: state.frame()[0] is not None)
    finally:
        first_frame.set()
        service.stop(timeout=4)

    assert detector.frames and quality.crops and encoded_frames and raw_frames
    assert all(np.array_equal(image, frame) for image in detector.frames)
    assert all(np.array_equal(image, frame[8:40, 8:56]) for image in quality.crops)
    assert all(np.array_equal(image, frame) for image in raw_frames)
    assert np.all(frame == (28, 55, 82))
    assert all(image.mean() > frame.mean() for image in encoded_frames)
    assert capture.writes == []
    assert service._model2_failure_count == 0
    assert capture.released
    assert service.camera_exposure.status()["ev"] == 0
    assert not service.camera_controls.connected


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture
def api(connected, tmp_path, monkeypatch):
    # A focused invocation must neither load real weights nor initialize normal history.
    monkeypatch.setenv("FISH_INSPECTION_DB_PATH", str(tmp_path / "history.sqlite3"))
    monkeypatch.setattr(YoloQualityModel, "load", lambda _: False)
    module = importlib.import_module("src.api.app")
    service, capture = connected
    monkeypatch.setattr(module, "service", service)
    rotate_policy = Mock(return_value="new-policy-session")
    monkeypatch.setattr(module, "inspection_sessions", SimpleNamespace(active=True))
    monkeypatch.setattr(module, "_rotate_durable_session_locked", rotate_policy)
    return module, service, capture, rotate_policy


@pytest.mark.parametrize("payload", [
    {}, [], {"ev": True}, {"ev": "1"}, {"ev": float("nan")},
    {"ev": float("inf")}, {"ev": 2.1}, {"ev": -2.1}, {"mode": "unknown"},
    {"reset": False}, {"reset": True, "ev": 0}, {"brightness": 1},
])
def test_endpoint_invalid_input_cannot_write_camera(api, payload):
    module, service, capture, record_policy = api
    before = service.camera_exposure.status()

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(module.update_camera_exposure(Request(payload)))

    assert rejected.value.status_code == 422
    assert service.camera_exposure.status() == before
    assert capture.writes == []
    record_policy.assert_not_called()


def test_endpoint_software_ev_does_not_rotate_acquisition_session(api):
    module, _, capture, record_policy = api

    result = asyncio.run(module.update_camera_exposure(Request({"mode": "manual", "ev": -.5})))

    assert result["success"] and not result["changed"]
    assert result["policy_session_id"] is None
    assert result["camera"]["exposure"]["ev"] == -.5
    assert capture.writes == []
    record_policy.assert_not_called()


def test_endpoint_native_ev_rotates_acquisition_session(api):
    module, service, capture, record_policy = api
    service.set_calibration_mode(True)

    result = asyncio.run(module.update_camera_exposure(Request({"mode": "manual", "ev": 1})))

    assert result["success"] and result["changed"]
    assert result["policy_session_id"] == "new-policy-session"
    assert capture.values[cv2.CAP_PROP_EXPOSURE] == -5.0
    record_policy.assert_called_once()

