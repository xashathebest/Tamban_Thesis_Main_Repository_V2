"""Acceptance checks for bounded, non-claiming conveyor decision timing."""
from __future__ import annotations

import math

import pytest

from src.api.domain import Detection, QualitySummary, TrackingConfig, TrackingManager


FRAME_SIZE = (100, 60)


def fish(track_id: int, center_x: float) -> Detection:
    return Detection(
        class_id=0,
        class_name="Fish",
        confidence=0.9,
        bbox=(center_x - 10, 10, center_x + 10, 35),
        track_id=track_id,
    )


def count_at(*, deadline: float | None, decision_at: float):
    tracker = TrackingManager(TrackingConfig(line_position=0.5, decision_deadline_seconds=deadline))
    tracker.update([fish(7, 40)], FRAME_SIZE, timestamp=10.0)
    events = tracker.update([fish(7, 60)], FRAME_SIZE, timestamp=decision_at)
    assert len(events) == 1
    return tracker, events[0]


def test_counted_event_records_unconfigured_elapsed_decision_time() -> None:
    _, event = count_at(deadline=None, decision_at=10.245)

    timing = event.analysis["conveyor_timing"]
    assert timing == {
        "first_detection_to_decision_ms": 245.0,
        "decision_deadline_seconds": None,
        "deadline_status": "not_configured",
        "measurement_scope": (
            "Elapsed monotonic time from the first persistent Model 1 detection "
            "to the virtual count-line decision; not physical entry or actuator confirmation."
        ),
    }
    assert event.decision == "COUNTED"


@pytest.mark.parametrize(
    ("decision_at", "expected_status"),
    [(10.2, "met"), (10.3, "missed")],
)
def test_optional_deadline_is_telemetry_only(decision_at: float, expected_status: str) -> None:
    tracker, event = count_at(deadline=0.25, decision_at=decision_at)

    timing = event.analysis["conveyor_timing"]
    assert timing["decision_deadline_seconds"] == 0.25
    assert timing["deadline_status"] == expected_status
    assert tracker.counters()["total"] == 1
    assert event.final_class == "Fish"


@pytest.mark.parametrize("deadline", [0, -0.01, math.inf, -math.inf, math.nan, True, "0.2"])
def test_invalid_deadline_is_rejected(deadline: object) -> None:
    with pytest.raises(ValueError, match="Decision deadline"):
        TrackingConfig(decision_deadline_seconds=deadline)  # type: ignore[arg-type]


def test_late_quality_refresh_preserves_finalized_decision_timing() -> None:
    tracker, event = count_at(deadline=0.2, decision_at=10.25)
    original_timing = dict(event.analysis["conveyor_timing"])

    tracker.update(
        [fish(7, 80)],
        FRAME_SIZE,
        timestamp=10.8,
        grades={7: QualitySummary(track_id=7, quality="Class A", quality_confidence=0.8)},
    )

    stored = tracker.archive_history()[0]
    assert stored["quality"] == "Class A"
    assert stored["analysis"]["conveyor_timing"] == original_timing

