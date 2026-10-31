"""Regression checks for exclusive Session Totals cards."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _kpi_renderer() -> str:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    start = script.index("function renderKpis(data)")
    end = script.index("\nfunction renderFeatureCounters", start)
    return script[start:end]


def test_session_totals_show_one_exclusive_bucket_per_counted_fish() -> None:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    renderer = _kpi_renderer()

    assert 'const sessionGradeBuckets = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"]' in script
    assert '["Fish detected", total, "Since reset", true]' in renderer
    assert "...sessionGradeBuckets.map" in renderer
    assert "Object.entries(grades).forEach" not in renderer
    assert "Graded fish" not in renderer

