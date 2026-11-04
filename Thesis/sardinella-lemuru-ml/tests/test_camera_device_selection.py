"""Runtime camera device listing and selection regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api import camera as camera_module
from src.api.camera import CameraInspectionService
from src.api.camera_controls import CameraControlError
from src.api.domain import InspectionState


class _Capture:
    def __init__(self, *, opened: bool) -> None:
        self.opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def release(self) -> None:
        self.released = True


class _CV2:
    CAP_DSHOW = 700
    CAP_MSMF = 1400

    def __init__(self, available: set[int]) -> None:
        self.available = available
        self.calls: list[tuple[int, int | None]] = []
        self.captures: list[_Capture] = []

    def VideoCapture(self, index: int, backend: int | None = None) -> _Capture:
        self.calls.append((index, backend))
        capture = _Capture(opened=index in self.available)
        self.captures.append(capture)
        return capture


def _service(tmp_path, camera_index: int = 0) -> CameraInspectionService:
    return CameraInspectionService(
        InspectionState(),
        SimpleNamespace(),
        camera_index=camera_index,
        camera_profile_path=tmp_path / "camera_settings.yaml",
    )


def test_camera_devices_reports_available_indexes_and_releases_probes(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_module.os, "name", "nt")
    monkeypatch.delenv("LEMURU_CAMERA_SCAN_LIMIT", raising=False)
    service = _service(tmp_path)
    cv2 = _CV2({0, 2})

    result = service.camera_devices(cv2)

    assert result["configured_camera_index"] == 0
    assert result["scan_limit"] == 6
    assert [(device["index"], device["available"]) for device in result["devices"]] == [
        (0, True), (1, False), (2, True), (3, False), (4, False), (5, False),
    ]
    assert cv2.calls == [(index, cv2.CAP_DSHOW) for index in range(6)]
    assert all(capture.released for capture in cv2.captures)


def test_camera_devices_reports_active_index_without_reopening_it(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_module.os, "name", "nt")
    service = _service(tmp_path, camera_index=1)
    monkeypatch.setattr(service, "has_live_worker", lambda: True)
    cv2 = _CV2({0})

    result = service.camera_devices(cv2)

    assert result["devices"][1] == {"index": 1, "name": "Camera #1", "available": True, "active": True}
    assert (1, cv2.CAP_DSHOW) not in cv2.calls


@pytest.mark.parametrize("value", ["1", None, 1.5, True, -1, 99])
def test_validate_camera_index_rejects_unsupported_values(tmp_path, value):
    service = _service(tmp_path)

    with pytest.raises(CameraControlError):
        service.validate_camera_index(value)


def test_set_camera_index_updates_service_controller_and_status(tmp_path):
    service = _service(tmp_path)

    service.set_camera_index(2)

    assert service.camera_index == 2
    assert service.camera_controls.camera_index == 2
    assert service.camera_status()["configured_camera_index"] == 2
