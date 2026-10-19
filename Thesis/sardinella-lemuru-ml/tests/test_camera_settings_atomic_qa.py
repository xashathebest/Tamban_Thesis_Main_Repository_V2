"""Hardware failures return readbacks and report best-effort restoration."""
from src.api.camera_controls import CameraHardwareController


class FakeCv2:
    CAP_PROP_EXPOSURE = 1
    CAP_PROP_GAIN = 2


class Capture:
    def __init__(self):
        self.values = {1: -6.0, 2: 20.0}
        self.reject_gain = False

    def get(self, key):
        return self.values.get(key, float("nan"))

    def set(self, key, value):
        if key == 2 and self.reject_gain and value != 20.0:
            return False
        self.values[key] = value
        return True


def controller(tmp_path):
    capture = Capture()
    camera = CameraHardwareController(0, tmp_path / "camera.yaml")
    camera.attach(capture, FakeCv2(), "Fake")
    return camera, capture


def test_preflight_invalid_control_does_not_write_valid_control(tmp_path):
    camera, capture = controller(tmp_path)
    result = camera.apply_settings({"exposure": -3.0, "gain": "not a number"})
    assert not result["success"] and not result["changed"]
    assert capture.values == {1: -6.0, 2: 20.0}
    assert "finite number" in result["results"]["gain"]["reason"]


def test_driver_failure_restores_previous_readback(tmp_path):
    camera, capture = controller(tmp_path)
    capture.reject_gain = True
    result = camera.apply_settings({"exposure": -3.0, "gain": 30.0})
    assert not result["success"] and not result["changed"]
    assert result["rollback"]["exposure"]["success"]
    assert capture.values == {1: -6.0, 2: 20.0}


def test_failed_restoration_reports_actual_change(tmp_path):
    camera, capture = controller(tmp_path)
    original_set = capture.set
    def rejecting_restore(key, value):
        if key == 1 and value == -6.0:
            return False
        return original_set(key, value)
    capture.set = rejecting_restore
    capture.reject_gain = True
    result = camera.apply_settings({"exposure": -3.0, "gain": 30.0})
    assert not result["success"] and result["changed"]
    assert not result["rollback"]["exposure"]["success"]
    assert result["actual"]["exposure"] == -3.0
