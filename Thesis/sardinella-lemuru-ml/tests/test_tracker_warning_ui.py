"""Tracker implementation details stay out of the operator dashboard."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tracker_warnings_and_details_are_not_rendered_in_the_ui() -> None:
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const visible = modelIssue || segmenterIssue || inspectionIssue;' in script
    for token in (
        "Tracker warning",
        "tracker_warning",
        "tracker_backend",
        "Active tracker",
        "Tracker fallback reason",
        "Tracker p50 / p95",
        "detectorTracker",
    ):
        assert token not in script
    assert 'id="detector-tracker"' not in markup
    assert "<dt>Tracker</dt>" not in markup
