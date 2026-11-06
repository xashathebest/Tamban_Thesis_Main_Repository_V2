"""Exposure controls with a fake capture and actual preview pixel processing."""

from threading import RLock

import cv2
import numpy as np
import pytest

from src.api.camera_controls import CameraControlError
from src.api.camera_exposure import CameraExposureController


class Hardware:
    def __init__(self, backend="DSHOW", exposure=-7, automatic=True, fps=30):
        self.lock = RLock()
        self.connected = True
        self.backend = backend
        self.actual = {"exposure": exposure, "auto_exposure": automatic}
        self.fps = fps
        self.writes = []
        self.reject = set()
        self.fail_restore = False

    def settings(self):
        return {"actual": dict(self.actual), "requested_automatic": {},
                "camera": {"backend": self.backend, "fps": self.fps}}

    def capabilities(self):
        return {"properties": {"exposure": {"supported": True}, "auto_exposure": {"supported": True}}}

    def set_auto_exposure(self, value):
        self.writes.append(("auto_exposure", value))
        accepted = "auto_exposure" not in self.reject
        if accepted:
            self.actual["auto_exposure"] = value
        return {"success": accepted}

    def set_camera_property(self, key, value):
        self.writes.append((key, value))
        self.actual["auto_exposure"] = False
        if self.fail_restore:
            self.actual[key] = value + 1  # Driver clamps even while returning false.
            return {"success": False}
        accepted = key not in self.reject
        if accepted:
            self.actual[key] = value
        return {"success": accepted}


def settle(controller, frame):
    now = controller._last_time or 0
    output = frame
    for i in range(12):
        output = controller.apply(frame, now=now + (i + 1) * .2)
    return output


def test_default_and_status_are_identity_without_camera_writes():
    hardware = Hardware()
    controller = CameraExposureController(hardware)
    original = np.full((32, 32, 3), 90, np.uint8)
    assert controller.apply(original) is original
    assert controller.status()["ev"] == 0
    assert not hardware.writes


@pytest.mark.parametrize("ev", [-2, -1, 1, 2])
def test_software_changes_brightness_preserves_color_and_original(ev):
    hardware = Hardware()
    controller = CameraExposureController(hardware)
    original = np.array([[[30, 60, 90], [60, 30, 90], [90, 60, 30], [100, 100, 100],
                          [0, 0, 0], [255, 255, 255], [210, 225, 245]]], np.uint8)
    before = original.copy()
    controller.configure(mode="manual", ev=ev, allow_native=False)
    adjusted = settle(controller, original)
    np.testing.assert_array_equal(original, before)
    assert adjusted.dtype == original.dtype and adjusted.shape == original.shape
    assert np.all(adjusted[0, :4].mean(1) > original[0, :4].mean(1)) if ev > 0 else np.all(adjusted[0, :4].mean(1) < original[0, :4].mean(1))
    np.testing.assert_array_equal(adjusted[0, 4:6], original[0, 4:6])
    hsv_before = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
    hsv_after = cv2.cvtColor(adjusted, cv2.COLOR_BGR2HSV)
    assert np.max(np.abs(hsv_after[0, :3, :2].astype(int) - hsv_before[0, :3, :2].astype(int))) <= 5
    assert adjusted[0, 6].max() < 255
    assert not hardware.writes


def test_ev_changes_ramp_with_elapsed_time_and_reset_is_identity():
    controller = CameraExposureController(Hardware())
    original = np.full((16, 16, 3), 80, np.uint8)
    controller.configure(ev=2, allow_native=False)
    first = controller.apply(original, now=controller._last_time + .01)
    assert 80 < first.mean() < 90
    final = settle(controller, original)
    assert final.mean() > first.mean()
    controller.reset(allow_native=False)
    assert controller.apply(original) is original


@pytest.mark.parametrize("value", [True, -2.01, 2.01, float("nan"), float("inf"), "1"])
def test_invalid_ev_never_writes_hardware(value):
    hardware = Hardware()
    controller = CameraExposureController(hardware)
    with pytest.raises(CameraControlError):
        controller.configure(ev=value)
    assert not hardware.writes


def test_native_ev_is_relative_to_one_baseline_not_cumulative():
    hardware = Hardware()
    controller = CameraExposureController(hardware)
    first = controller.configure(ev=1.2)
    assert first["source"] == "native" and first["native_ev"] == 1
    assert first["hardware_changed"]
    assert hardware.actual["exposure"] == -6
    controller.configure(ev=2)
    assert hardware.actual["exposure"] == -5
    controller.configure(ev=-1)
    assert hardware.actual["exposure"] == -8
    result = controller.reset()
    assert result["success"] and result["hardware_changed"]
    assert hardware.actual == {"exposure": -7, "auto_exposure": True}


def test_native_shutter_does_not_exceed_frame_interval():
    hardware = Hardware(exposure=-6, fps=60)
    controller = CameraExposureController(hardware)
    result = controller.configure(ev=2)
    assert result["source"] == "software"
    assert not hardware.writes


def test_unreadable_fps_uses_software_for_positive_ev_but_can_shorten_shutter():
    hardware = Hardware(fps=None)
    controller = CameraExposureController(hardware)
    assert controller.configure(ev=2)["source"] == "software"
    assert not hardware.writes
    assert controller.configure(ev=-1)["source"] == "native"
    assert hardware.actual["exposure"] == -8


@pytest.mark.parametrize("backend", ["MSMF", "V4L2", "OpenCV"])
def test_unknown_native_units_use_software_without_probing_writes(backend):
    hardware = Hardware(backend=backend)
    result = CameraExposureController(hardware).configure(ev=1)
    assert result["source"] == "software"
    assert not hardware.writes


def test_unknown_automatic_state_is_not_changed_by_native_probe():
    hardware = Hardware(automatic=None)
    assert CameraExposureController(hardware).configure(ev=1)["source"] == "software"
    assert not hardware.writes


def test_native_rejection_restores_automatic_mode_then_falls_back():
    hardware = Hardware()
    hardware.reject.add("exposure")
    controller = CameraExposureController(hardware)
    result = controller.configure(ev=1)
    assert result["success"] and result["source"] == "software"
    assert not result["native_active"] and result["hardware_changed"]
    assert hardware.actual == {"exposure": -7, "auto_exposure": True}


def test_partial_native_change_with_failed_restore_is_reported_as_failure():
    hardware = Hardware()
    hardware.fail_restore = True
    result = CameraExposureController(hardware).configure(ev=1)
    assert not result["success"]
    assert result["hardware_changed"] and result["native_active"]
    assert "could not restore" in result["reason"]


def test_allow_native_false_prohibits_restoration_and_auto_writes():
    hardware = Hardware()
    controller = CameraExposureController(hardware)
    controller.configure(ev=1)
    hardware.writes.clear()
    controller.configure(mode="auto", allow_native=False)
    controller.reset(allow_native=False)
    controller.clear()
    assert hardware.writes == []
    assert hardware.actual == {"exposure": -6, "auto_exposure": False}


def test_auto_rejection_is_reported():
    hardware = Hardware()
    hardware.reject.add("auto_exposure")
    result = CameraExposureController(hardware).configure(mode="auto")
    assert not result["success"]
    assert "rejected Auto Exposure" in result["reason"]
