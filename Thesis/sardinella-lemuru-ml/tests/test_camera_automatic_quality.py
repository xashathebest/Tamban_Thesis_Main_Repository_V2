"""Acquisition regressions for Windows drivers with stateful manual controls.

The fake models the important DirectShow behavior: an exposure/gain write can
disable AE, white-balance writes disable AWB, and AE's getter returns -1 even
when its setter works. No webcam, image enhancement, or model is involved.
"""

from __future__ import annotations

import pytest

from src.api.camera_controls import CameraHardwareController


class WindowsCv2:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_FOURCC = 6
    CAP_PROP_BRIGHTNESS = 10
    CAP_PROP_CONTRAST = 11
    CAP_PROP_SATURATION = 12
    CAP_PROP_GAIN = 14
    CAP_PROP_EXPOSURE = 15
    CAP_PROP_CONVERT_RGB = 16
    CAP_PROP_WHITE_BALANCE_BLUE_U = 17
    CAP_PROP_SHARPNESS = 20
    CAP_PROP_AUTO_EXPOSURE = 21
    CAP_PROP_GAMMA = 22
    CAP_PROP_FOCUS = 28
    CAP_PROP_AUTOFOCUS = 39
    CAP_PROP_AUTO_WB = 44
    CAP_PROP_WB_TEMPERATURE = 45


class StatefulWindowsCapture:
    def __init__(self, *, ae_readable: bool = False) -> None:
        self.values = {
            3: 640.0, 4: 480.0, 5: 30.0, 6: float(int.from_bytes(b"MJPG", "little")),
            10: 0.0, 11: 32.0, 12: 64.0, 14: 20.0, 15: -5.0, 16: 1.0,
            17: -1.0, 20: 2.0, 22: 100.0, 28: 80.0, 45: 4500.0,
        }
        self.ae_readable = ae_readable
        self.ae_enabled = True
        self.awb_enabled = True
        self.autofocus_enabled = False
        self.writes: list[tuple[int, float]] = []
        self.reject: set[int] = set()
        self.read_count = 0
        self.released = False

    def get(self, key: int) -> float:
        if key == WindowsCv2.CAP_PROP_AUTO_EXPOSURE:
            return float(self.ae_enabled) if self.ae_readable else -1.0
        if key == WindowsCv2.CAP_PROP_AUTO_WB:
            return float(self.awb_enabled)
        if key == WindowsCv2.CAP_PROP_AUTOFOCUS:
            # DirectShow exposes native CameraControlFlags here, unlike AWB.
            return 1.0 if self.autofocus_enabled else 2.0
        return self.values.get(key, float("nan"))

    def set(self, key: int, value: float) -> bool:
        self.writes.append((key, value))
        if key in self.reject:
            return False
        if key == WindowsCv2.CAP_PROP_AUTO_EXPOSURE:
            self.ae_enabled = round(value) == 1
        elif key == WindowsCv2.CAP_PROP_AUTO_WB:
            self.awb_enabled = value == 1.0
        elif key == WindowsCv2.CAP_PROP_AUTOFOCUS:
            self.autofocus_enabled = value == 1.0
        else:
            self.values[key] = value
            if key in {WindowsCv2.CAP_PROP_EXPOSURE, WindowsCv2.CAP_PROP_GAIN}:
                self.ae_enabled = False
            if key in {WindowsCv2.CAP_PROP_WB_TEMPERATURE, WindowsCv2.CAP_PROP_WHITE_BALANCE_BLUE_U}:
                self.awb_enabled = False
            if key == WindowsCv2.CAP_PROP_FOCUS:
                self.autofocus_enabled = False
        return True

    def read(self):
        self.read_count += 1
        raise AssertionError("Hardware control queries must not capture frames")

    def release(self) -> None:
        self.released = True


@pytest.fixture
def camera(tmp_path):
    capture = StatefulWindowsCapture()
    controller = CameraHardwareController(0, tmp_path / "camera.yaml")
    controller.attach(capture, WindowsCv2(), "DSHOW")
    return controller, capture


def test_attach_and_status_queries_do_not_write_controls_or_reopen_capture(camera):
    controller, capture = camera
    before = dict(capture.values)

    controller.capabilities()
    controller.settings()
    controller.camera_details()
    controller.profile_drift()

    assert capture.writes == []
    assert capture.values == before
    assert capture.ae_enabled and capture.awb_enabled
    assert not capture.autofocus_enabled
    assert capture.read_count == 0
    controller.detach(capture)
    assert not capture.released


@pytest.mark.parametrize("enabled, expected_raw", [(True, 1.0), (False, 0.0)])
def test_dshow_auto_exposure_setter_works_without_fabricating_readback(camera, enabled, expected_raw):
    controller, capture = camera
    assert controller.settings()["actual"]["auto_exposure"] is None

    result = controller.set_auto_exposure(enabled)

    assert result["success"]
    assert result["actual"] is None
    assert result["verified"] is False
    assert capture.ae_enabled is enabled
    assert capture.writes == [(WindowsCv2.CAP_PROP_AUTO_EXPOSURE, expected_raw)]


def test_dshow_native_manual_autofocus_flag_is_false(camera):
    controller, capture = camera
    assert controller.settings()["actual"]["autofocus"] is False
    result = controller.set_autofocus(True)
    assert result["success"]
    assert capture.autofocus_enabled
    assert controller.settings()["actual"]["autofocus"] is True


def test_temperature_alias_and_gamma_are_read_without_probing_writes(camera):
    controller, capture = camera
    settings = controller.settings()["actual"]
    assert settings["white_balance"] == 4500
    assert settings["gamma"] == 100
    assert capture.writes == []

    result = controller.set_camera_property("white_balance", 4800)
    assert result["success"]
    assert capture.writes == [(WindowsCv2.CAP_PROP_WB_TEMPERATURE, 4800.0)]


def test_older_dshow_white_balance_alias_remains_available(tmp_path):
    capture = StatefulWindowsCapture()
    capture.values[WindowsCv2.CAP_PROP_WHITE_BALANCE_BLUE_U] = 4500.0
    capture.values[WindowsCv2.CAP_PROP_WB_TEMPERATURE] = -1.0
    controller = CameraHardwareController(0, tmp_path / "camera.yaml")
    controller.attach(capture, WindowsCv2(), "DSHOW")

    assert controller.settings()["actual"]["white_balance"] == 4500
    result = controller.set_camera_property("white_balance", 4800)
    assert result["success"]
    assert capture.writes == [(WindowsCv2.CAP_PROP_WHITE_BALANCE_BLUE_U, 4800.0)]


def test_automatic_profile_avoids_manual_exposure_gain_and_white_balance(camera):
    controller, capture = camera
    result = controller.apply_settings({
        "auto_exposure": True,
        "auto_white_balance": True,
        "exposure": -8,
        "gain": 0,
        "white_balance": 2800,
        "brightness": 20,
    })

    assert result["success"]
    assert capture.ae_enabled and capture.awb_enabled
    written = [key for key, _value in capture.writes]
    assert WindowsCv2.CAP_PROP_EXPOSURE not in written
    assert WindowsCv2.CAP_PROP_GAIN not in written
    assert WindowsCv2.CAP_PROP_WB_TEMPERATURE not in written
    assert written.index(WindowsCv2.CAP_PROP_BRIGHTNESS) < written.index(WindowsCv2.CAP_PROP_AUTO_EXPOSURE)
    assert written.index(WindowsCv2.CAP_PROP_BRIGHTNESS) < written.index(WindowsCv2.CAP_PROP_AUTO_WB)


def test_failed_manual_transaction_restores_previous_automatic_modes(tmp_path):
    capture = StatefulWindowsCapture(ae_readable=True)
    controller = CameraHardwareController(0, tmp_path / "camera.yaml")
    controller.attach(capture, WindowsCv2(), "DSHOW")
    capture.reject.add(WindowsCv2.CAP_PROP_BRIGHTNESS)

    result = controller.apply_settings({"exposure": -8, "white_balance": 2800, "brightness": 20})

    assert not result["success"]
    assert capture.values[WindowsCv2.CAP_PROP_EXPOSURE] == -5.0
    assert capture.values[WindowsCv2.CAP_PROP_WB_TEMPERATURE] == 4500.0
    assert capture.ae_enabled and capture.awb_enabled
    assert result["actual"]["auto_exposure"] is True
    assert result["actual"]["auto_white_balance"] is True


def test_new_installation_requests_ae_awb_without_writing_image_controls(camera):
    controller, capture = camera
    capture.ae_enabled = False
    capture.awb_enabled = False

    result = controller.initialize_camera_settings()

    assert result["success"]
    assert capture.ae_enabled and capture.awb_enabled
    assert set(capture.writes) == {
        (WindowsCv2.CAP_PROP_AUTO_EXPOSURE, 1.0),
        (WindowsCv2.CAP_PROP_AUTO_WB, 1.0),
    }


def test_legacy_unconfirmed_profile_cannot_restore_dark_manual_capture(tmp_path):
    profile_path = tmp_path / "camera.yaml"
    profile_path.write_text(
        "camera:\n"
        "  locked: false\n"
        "  operator_confirmation: {confirmed: false}\n"
        "  settings:\n"
        "    fps: 120.0005\n"
        "    brightness: 0\n"
        "    exposure: -8\n"
        "    gain: 0\n"
        "    auto_exposure: false\n"
        "    auto_white_balance: false\n",
        encoding="utf-8",
    )
    capture = StatefulWindowsCapture()
    controller = CameraHardwareController(0, profile_path)
    controller.attach(capture, WindowsCv2(), "DSHOW")

    result = controller.initialize_camera_settings()

    assert result["success"]
    assert capture.ae_enabled and capture.awb_enabled
    assert capture.values[WindowsCv2.CAP_PROP_FPS] == 30.0
    assert capture.values[WindowsCv2.CAP_PROP_EXPOSURE] == -5.0
    assert all(key in {WindowsCv2.CAP_PROP_AUTO_EXPOSURE, WindowsCv2.CAP_PROP_AUTO_WB} for key, _ in capture.writes)


@pytest.mark.parametrize("policy", [
    "  control_schema_version: 2\n",
    "  locked: true\n",
    "  operator_confirmation: {confirmed: true}\n",
])
def test_explicit_manual_profile_remains_reproducible(tmp_path, policy):
    profile_path = tmp_path / "camera.yaml"
    profile_path.write_text(
        "camera:\n" + policy +
        "  settings:\n"
        "    exposure: -8\n"
        "    gain: 0\n"
        "    white_balance: 2800\n"
        "    auto_exposure: false\n"
        "    auto_white_balance: false\n",
        encoding="utf-8",
    )
    capture = StatefulWindowsCapture()
    controller = CameraHardwareController(0, profile_path)
    controller.attach(capture, WindowsCv2(), "DSHOW")

    result = controller.initialize_camera_settings()

    assert result["success"]
    assert not capture.ae_enabled and not capture.awb_enabled
    assert capture.values[WindowsCv2.CAP_PROP_EXPOSURE] == -8
    assert capture.values[WindowsCv2.CAP_PROP_GAIN] == 0
    assert capture.values[WindowsCv2.CAP_PROP_WB_TEMPERATURE] == 2800


def test_saved_unknown_ae_state_records_accepted_intent_without_faking_measurement(camera):
    controller, capture = camera
    controller.set_auto_exposure(True)

    saved = controller.save_camera_profile()

    assert saved["profile"]["control_schema_version"] >= 2
    assert saved["profile"]["settings"]["auto_exposure"] is True
    assert saved["actual"]["auto_exposure"] is None
    assert saved["profile"]["setting_sources"]["auto_exposure"] == "driver_accepted_request"
    assert capture.ae_enabled


def test_reset_does_not_disable_auto_exposure_when_original_mode_was_unreadable(camera):
    controller, capture = camera
    controller.initialize_camera_settings()
    # The driver's automatic algorithm has changed its live observations.
    capture.values[WindowsCv2.CAP_PROP_EXPOSURE] = -4.0
    capture.values[WindowsCv2.CAP_PROP_GAIN] = 25.0
    capture.writes.clear()

    result = controller.reset_camera_settings()

    assert result["success"]
    assert capture.ae_enabled
    assert controller.settings()["requested_automatic"]["auto_exposure"] is True
