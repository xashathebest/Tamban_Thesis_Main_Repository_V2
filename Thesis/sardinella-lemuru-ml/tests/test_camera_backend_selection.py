"""Camera backend preference and failure diagnostics regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api import camera as camera_module
from src.api.camera import CameraInspectionService
from src.api.domain import InspectionState


class _Capture:
    def __init__(self, *, opened: bool, backend_name: str) -> None:
        self.opened = opened
        self.backend_name = backend_name
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def getBackendName(self) -> str:
        return self.backend_name

    def release(self) -> None:
        self.released = True


class _CV2:
    CAP_DSHOW = 700
    CAP_MSMF = 1400

    def __init__(self, captures: dict[int | None, _Capture]) -> None:
        self.captures = captures
        self.calls: list[tuple[int, int | None]] = []

    def VideoCapture(self, index: int, backend: int | None = None) -> _Capture:
        self.calls.append((index, backend))
        return self.captures[backend]


def _service(tmp_path, profile: str) -> CameraInspectionService:
    profile_path = tmp_path / "camera_settings.yaml"
    profile_path.write_text(profile, encoding="utf-8")
    return CameraInspectionService(
        InspectionState(),
        SimpleNamespace(),  # The opening path does not use the inference model.
        camera_index=4,
        camera_profile_path=profile_path,
    )


def test_saved_msmf_backend_is_attempted_before_default_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_module.os, "name", "nt")
    service = _service(tmp_path, "camera:\n  preferred_backend: MSMF\n")
    msmf = _Capture(opened=True, backend_name="MSMF")
    cv2 = _CV2({700: _Capture(opened=False, backend_name="DSHOW"), 1400: msmf, None: _Capture(opened=False, backend_name="default")})

    capture, backend = service._open_capture(cv2)

    assert capture is msmf
    assert backend == "MSMF"
    assert cv2.calls == [(4, cv2.CAP_MSMF)]
    attempts = service.camera_status()["open_attempts"]
    assert attempts == [{"backend": "MSMF", "status": "opened", "reported_backend": "MSMF"}]
    assert service.camera_status()["configured_camera_index"] == 4
    assert service.runtime_diagnostics()["camera_open_attempts"] == attempts


def test_unknown_saved_backend_never_executes_and_reports_all_safe_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_module.os, "name", "nt")
    service = _service(tmp_path, "camera:\n  preferred_backend: untrusted-custom-backend\n")
    dshow = _Capture(opened=False, backend_name="DSHOW")
    msmf = _Capture(opened=False, backend_name="MSMF")
    fallback = _Capture(opened=False, backend_name="default")
    cv2 = _CV2({700: dshow, 1400: msmf, None: fallback})

    capture, backend = service._open_capture(cv2)

    assert capture is None
    assert backend == "Unavailable"
    assert cv2.calls == [(4, cv2.CAP_DSHOW), (4, cv2.CAP_MSMF), (4, None)]
    assert dshow.released and msmf.released and fallback.released
    attempts = service.camera_status()["open_attempts"]
    assert [(item["backend"], item["status"]) for item in attempts] == [
        ("DSHOW", "not_opened"),
        ("MSMF", "not_opened"),
        ("OpenCV default", "not_opened"),
    ]
    assert all("untrusted" not in str(item) for item in attempts)
    message = service._camera_open_failure_message()
    assert "DSHOW (not_opened)" in message
    assert "configured camera index" in message


@pytest.mark.parametrize("stored, expected", [
    ("DirectShow", "dshow"),
    ("Media Foundation", "msmf"),
    ("OpenCV default", "default"),
    ("FFMPEG", None),
])
def test_saved_backend_is_sanitized_to_known_candidates(tmp_path, stored, expected):
    service = _service(tmp_path, f"camera:\n  preferred_backend: {stored}\n")

    assert service._saved_preferred_backend() == expected
