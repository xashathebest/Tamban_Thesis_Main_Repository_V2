"""The operator launcher must use the project environment without requiring ByteTrack."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operator_launcher_uses_project_venv_and_permits_fallback_tracking() -> None:
    launcher = (ROOT / "run_dashboard.ps1").read_text(encoding="utf-8")

    assert ".venv\\Scripts\\python.exe" in launcher
    assert "import lap" not in launcher
    assert "FISH_REQUIRE_BYTETRACK" not in launcher
    assert "-m src.api" in launcher


def test_bytetrack_dependency_is_optional() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    bytetrack_requirements = (ROOT / "requirements-bytetrack.txt").read_text(encoding="utf-8")

    assert "lap==0.5.13" not in requirements
    assert "lap==0.5.13" in bytetrack_requirements


def test_api_allows_iou_fallback_by_default() -> None:
    app_source = (ROOT / "src" / "api" / "app.py").read_text(encoding="utf-8")

    assert 'os.getenv("FISH_REQUIRE_BYTETRACK", "0")' in app_source

