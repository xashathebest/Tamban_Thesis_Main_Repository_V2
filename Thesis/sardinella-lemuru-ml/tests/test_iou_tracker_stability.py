"""Fallback identity association without a camera, checkpoints, or synthetic boxes."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from src.inference.fish_detector import _ByteTrackInput
from src.inference.yolo_fish_detector import FishDetection, _IoUTracker


def update(tracker: _IoUTracker, boxes, confidences=None):
    confidence_values = confidences if confidences is not None else [0.9] * len(boxes)
    detections = _ByteTrackInput([FishDetection(tuple(box), confidence) for box, confidence in zip(boxes, confidence_values)])
    return tracker.update(detections, None)


def box(x, y=0):
    return x, y, x + 20, y + 20


def identity_by_box(rows):
    return {tuple(row[:4]): int(row[4]) for row in rows}


@pytest.mark.parametrize("initial_order, current_order", list(itertools.product([(0, 1), (1, 0)], repeat=2)))
def test_global_assignment_retains_both_tracks_when_greedy_matching_steals_a_match(initial_order, current_order):
    tracker = _IoUTracker()
    initial = [box(0), box(12)]
    first = identity_by_box(update(tracker, [initial[index] for index in initial_order]))
    # x=5 overlaps both tracks and prefers track A. x=-5 overlaps only A.
    # Taking x=5 first must not consume A and unnecessarily create a third ID.
    current = [box(5), box(-5)]
    actual = identity_by_box(update(tracker, [current[index] for index in current_order]))

    assert actual[box(-5)] == first[box(0)]
    assert actual[box(5)] == first[box(12)]
    assert tracker._next_id == 3


def test_motion_prediction_retains_identity_across_short_occlusion():
    tracker = _IoUTracker()
    identity = int(update(tracker, [box(0)])[0, 4])
    for position in (8, 16, 24):
        assert int(update(tracker, [box(position)])[0, 4]) == identity
    for _ in range(2):
        assert update(tracker, []).shape == (0, 8)

    returned = update(tracker, [box(48)])

    assert int(returned[0, 4]) == identity
    np.testing.assert_array_equal(returned[0, :4], box(48))
    assert tracker._next_id == 2


def test_abrupt_stop_does_not_fragment_a_previously_moving_fish():
    tracker = _IoUTracker()
    identities = [int(update(tracker, [box(position)])[0, 4]) for position in (0, 8, 22, 22, 22)]
    assert identities == [1, 1, 1, 1, 1]


def test_two_crossing_tracks_keep_identity_when_detection_order_alternates():
    tracker = _IoUTracker()
    expected = identity_by_box(update(tracker, [box(0), box(90)]))
    first_id, second_id = expected[box(0)], expected[box(90)]
    for frame, first_x in enumerate(range(10, 71, 10)):
        first_box, second_box = box(first_x), box(90 - first_x)
        boxes = [first_box, second_box] if frame % 2 else [second_box, first_box]
        rows = update(tracker, boxes)
        actual = identity_by_box(rows)
        assert actual[first_box] == first_id
        assert actual[second_box] == second_id
        assert len(set(rows[:, 4])) == 2
    assert tracker._next_id == 3


def test_empty_updates_allocate_no_ids_and_emit_no_predicted_fish():
    tracker = _IoUTracker()
    for _ in range(4):
        empty = update(tracker, [])
        assert empty.shape == (0, 8)
        assert empty.dtype == np.float32
    assert tracker._next_id == 1
    update(tracker, [box(0), box(60)])
    empty = update(tracker, [])
    assert empty.shape == (0, 8)
    assert tracker._next_id == 3
    # The still-missing second fish must not be included in real detections.
    returned = update(tracker, [box(0)])
    assert len(returned) == 1
    np.testing.assert_array_equal(returned[0, :4], box(0))


def test_rows_preserve_current_boxes_confidences_and_original_source_indices():
    tracker = _IoUTracker()
    boxes = [box(60), box(0)]
    rows = update(tracker, boxes, [0.84, 0.93])

    np.testing.assert_array_equal(rows[:, :4], boxes)
    np.testing.assert_allclose(rows[:, 5], [0.84, 0.93])
    np.testing.assert_array_equal(rows[:, 6], [0, 0])
    np.testing.assert_array_equal(rows[:, 7], [0, 1])
    assert identity_by_box(rows) == {box(0): 1, box(60): 2}


def test_global_assignment_does_not_force_a_match_below_iou_gate():
    tracker = _IoUTracker()
    original = int(update(tracker, [box(0)])[0, 4])
    distant = int(update(tracker, [box(100)])[0, 4])
    assert distant != original


def test_expiry_and_reset_bound_identity_lifetime():
    tracker = _IoUTracker(max_missing_frames=2)
    first = int(update(tracker, [box(0)])[0, 4])
    update(tracker, [])
    update(tracker, [])
    assert int(update(tracker, [box(0)])[0, 4]) == first
    for _ in range(3):
        update(tracker, [])
    assert not tracker._tracks
    assert int(update(tracker, [box(0)])[0, 4]) != first

    tracker.reset()

    assert tracker._next_id == 1
    assert not tracker._tracks
    assert int(update(tracker, [box(0)])[0, 4]) == 1
