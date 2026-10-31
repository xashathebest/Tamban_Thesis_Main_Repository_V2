"""Weak detections maintain association without becoming inspected fish evidence."""

from types import SimpleNamespace

import numpy as np
import pytest

from src.api.domain import TrackingConfig, TrackingManager
from src.inference.yolo_fish_detector import FishDetection, YoloFishDetector


FRAME = np.zeros((100, 160, 3), dtype=np.uint8)
BOX = (10.0, 10.0, 40.0, 30.0)


def box(score, bbox=BOX, class_id=0):
    return SimpleNamespace(cls=np.asarray(class_id), conf=np.asarray(score), xyxy=np.asarray([bbox], dtype=float))


class Model:
    def __init__(self, frames):
        self.frames = frames
        self.options = []

    def predict(self, **options):
        index = min(len(self.options), len(self.frames) - 1)
        self.options.append(options)
        return [SimpleNamespace(boxes=self.frames[index])]


class Tracker:
    def __init__(self, rows):
        self.rows = rows
        self.inputs = []
        self.args = SimpleNamespace(track_low_thresh=.1)

    def update(self, detections, _frame):
        self.inputs.append(detections)
        return self.rows


def detector(frames, tracker, *, backend="ByteTrack", confidence=.5):
    model = YoloFishDetector(None, device="cpu", confidence_threshold=confidence)
    model.model = Model(frames)
    model._tracker = tracker
    model.tracker_backend = backend
    return model


def test_tracking_collects_weak_boxes_but_still_images_keep_configured_threshold():
    tracker = Tracker([[*BOX, 7, .9, 0, 1]])
    model = detector([[box(.2), box(.9)]], tracker)

    assert model.predict(FRAME)[0].track_id is None
    confirmed = model.predict(FRAME)
    assert [(item.confidence, item.track_id) for item in confirmed] == [(.9, 1)]
    assert tracker.inputs[-1].conf.tolist() == pytest.approx([.2, .9])
    assert model.model.options[-1]["conf"] == .1

    assert [item.confidence for item in model.detect(FRAME)] == [.9]
    assert model.model.options[-1]["conf"] == .5


def test_custom_trackers_keep_the_configured_detector_threshold():
    tracker = Tracker([[*BOX, 7, .9, 0, 0]])
    model = detector([[box(.2), box(.9)]], tracker, backend="custom tracker")
    model.predict(FRAME)
    assert tracker.inputs[-1].conf.tolist() == pytest.approx([.9])
    assert model.model.options[-1]["conf"] == .5


def test_tracking_floor_never_raises_the_operators_detection_threshold():
    tracker = Tracker([])
    model = detector([[box(.07)]], tracker, confidence=.05)
    assert model.predict(FRAME)[0].track_id is None
    assert model.model.options[-1]["conf"] == .05
    assert tracker.inputs[-1].conf.tolist() == pytest.approx([.07])


def test_native_new_track_floor_follows_live_confidence_without_latching_the_highest_value():
    tracker = Tracker([[*BOX, 7, .9, 0, 0]])
    tracker.args.new_track_thresh = .4
    model = detector([[box(.9)]], tracker, confidence=.6)
    model.predict(FRAME)
    assert tracker.args.new_track_thresh == .6
    model.confidence_threshold = .8
    model.predict(FRAME)
    assert tracker.args.new_track_thresh == .8
    model.confidence_threshold = .3
    model.predict(FRAME)
    assert tracker.args.new_track_thresh == .4
    assert tracker.args.track_low_thresh == .1


def test_raw_input_rejects_invalid_confidences_classes_and_geometry():
    result = SimpleNamespace(boxes=[
        box(.9), box(1.1), box(-.1), box(float("nan")), box(float("inf")),
        box(.8, class_id=.3), box(.8, class_id=float("nan")),
        box(.8, (0, 0, float("inf"), 20)), box(.8, (20, 0, 10, 20)), box(.8, (0, 0, 20, 0)),
        SimpleNamespace(cls=None, conf=None, xyxy=None),
    ])
    assert YoloFishDetector._raw_detections(result, 160, 100, 0) == [FishDetection(BOX, .9)]


@pytest.mark.parametrize("column,value", [
    (0, float("nan")), (2, float("inf")), (2, 5),
    (4, float("nan")), (4, float("inf")), (4, 7.5), (4, -1),
    (5, -0.1), (5, 1.1), (6, 1), (7, .5), (7, -1), (7, 1),
])
def test_malformed_tracker_rows_cannot_confirm_an_identity(column, value):
    row = [*BOX, 7, .9, 0, 0]
    row[column] = value
    model = detector([[box(.9)]], Tracker([row]))
    assert model.predict(FRAME)[0].track_id is None
    assert model.predict(FRAME)[0].track_id is None


@pytest.mark.parametrize("rows", [[], [[1, 2]], [[*BOX, "invalid", .9, 0, 0]], [[1, 2], [1]]])
def test_wrong_tracker_output_shapes_leave_current_fish_untracked(rows):
    model = detector([[box(.9)]], Tracker(rows))
    assert model.predict(FRAME)[0].track_id is None
    assert model.predict(FRAME)[0].track_id is None


def test_stale_source_index_cannot_attach_a_box_elsewhere_in_the_frame():
    model = detector([[box(.9)]], Tracker([[80, 60, 110, 80, 7, .9, 0, 0]]))
    assert model.predict(FRAME)[0].track_id is None
    assert model.predict(FRAME)[0].track_id is None


@pytest.mark.parametrize("last_frame,active,state", [(1, True, 1), (2, False, 1), (2, True, 2)])
def test_predicted_lost_and_unconfirmed_native_tracks_are_not_observations(last_frame, active, state):
    tracker = Tracker([[*BOX, 7, .9, 0, 0]])
    tracker.frame_id = 2
    tracker.tracked_stracks = [SimpleNamespace(track_id=7, frame_id=last_frame, is_activated=active, state=state)]
    model = detector([[box(.9)]], tracker)
    assert model.predict(FRAME)[0].track_id is None
    assert model.predict(FRAME)[0].track_id is None


def test_identical_duplicate_rows_collapse_without_duplicate_public_ids():
    row = [*BOX, 7, .9, 0, 0]
    model = detector([[box(.9)]], Tracker([row, row]))
    assert model.predict(FRAME)[0].track_id is None
    assert [item.track_id for item in model.predict(FRAME)] == [1]


@pytest.mark.parametrize("rows", [
    [[*BOX, 7, .9, 0, 0], [*BOX, 8, .9, 0, 0]],
    [[*BOX, 7, .9, 0, 0], [*BOX, 7, .8, 0, 1]],
])
def test_conflicting_source_or_identity_mappings_remain_untracked(rows):
    model = detector([[box(.9), box(.8)]], Tracker(rows))
    assert all(item.track_id is None for item in model.predict(FRAME))
    assert all(item.track_id is None for item in model.predict(FRAME))


def test_empty_frames_advance_tracker_and_public_identity_aging():
    tracker = Tracker([])
    model = detector([[]], tracker)
    before = model._fish_identities._frame
    assert model.predict(FRAME) == []
    assert len(tracker.inputs) == 1 and len(tracker.inputs[0]) == 0
    assert model._fish_identities._frame == before + 1
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 0


def native_tracker():
    lap = pytest.importorskip("lap")
    if not callable(getattr(lap, "lapjv", None)):
        pytest.skip("Native lap solver unavailable")
    pytest.importorskip("ultralytics")
    from ultralytics.trackers.byte_tracker import BYTETracker

    return BYTETracker(SimpleNamespace(track_buffer=30, track_high_thresh=.25, track_low_thresh=.1,
                                      new_track_thresh=.25, match_thresh=.8, fuse_score=True))


def test_real_bytetrack_weak_continuity_keeps_one_confirmed_fish_without_weak_outputs():
    tracker = native_tracker()
    model = detector([[box(score)] for score in [.9, .9, .2, .2, .9]], tracker)
    outputs = [model.predict(FRAME) for _ in range(5)]
    assert outputs[0][0].track_id is None
    assert outputs[1][0].track_id == 1
    assert outputs[2] == outputs[3] == []
    assert outputs[4][0].track_id == 1
    assert tracker.tracked_stracks[0].track_id == 1
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 1


def test_real_bytetrack_empty_frames_emit_no_predicted_fish_and_reuse_identity():
    tracker = native_tracker()
    model = detector([[box(.9)], [box(.9)], [], [], [box(.9)]], tracker)
    outputs = [model.predict(FRAME) for _ in range(5)]
    assert outputs[1][0].track_id == 1
    assert outputs[2] == outputs[3] == []
    assert outputs[4][0].track_id == 1
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 1


def test_real_bytetrack_weak_only_detections_cannot_allocate_native_candidates():
    tracker = native_tracker()
    model = detector([[box(.3)]], tracker)
    for _ in range(40):
        assert model.predict(FRAME) == []
    assert tracker.args.new_track_thresh == .5
    assert tracker.args.track_high_thresh == .25
    assert tracker.args.track_low_thresh == .1
    assert not tracker.tracked_stracks and not tracker.lost_stracks and not tracker.removed_stracks
    assert tracker.track_class._count == 0
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 0


def test_real_bytetrack_long_weak_continuity_keeps_the_same_public_identity():
    tracker = native_tracker()
    frames = [[box(.9)], [box(.9)]] + [[box(.2)] for _ in range(40)] + [[box(.9)]]
    model = detector(frames, tracker)
    outputs = [model.predict(FRAME) for _ in frames]
    assert outputs[1][0].track_id == 1
    assert all(output == [] for output in outputs[2:-1])
    assert outputs[-1][0].track_id == 1
    assert tracker.tracked_stracks[0].track_id == 1
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 1


def test_real_bytetrack_later_birth_preserves_a_two_observation_line_crossing():
    tracker = native_tracker()
    first_box = (60, 10, 90, 30)  # center 75, before the x=80 inspection line
    second_box = (70, 10, 100, 30)  # center 85, beyond the inspection line
    model = detector([[], [box(.9, first_box)], [box(.9, second_box)]], tracker)
    counter = TrackingManager(TrackingConfig(line_position=.5))
    assert counter.update(model.predict(FRAME), (160, 100)) == []
    first = model.predict(FRAME)
    assert first[0].track_id is None
    assert counter.update(first, (160, 100)) == []
    second = model.predict(FRAME)
    assert second[0].track_id == 1
    assert second[0].confirmation.bbox == first_box
    assert [event.track_id for event in counter.update(second, (160, 100))] == [1]
    assert counter.counters()["total"] == 1


def test_custom_native_lost_buffer_retains_the_same_public_identity():
    tracker = native_tracker()
    tracker.max_frames_lost = 60
    frames = [[box(.9)], [box(.9)]] + [[] for _ in range(40)] + [[box(.9)]]
    model = detector(frames, tracker)
    outputs = [model.predict(FRAME) for _ in frames]
    assert outputs[1][0].track_id == 1
    assert all(output == [] for output in outputs[2:-1])
    assert outputs[-1][0].track_id == 1
    assert model._fish_identities.max_missing_frames == 60
    assert model._fish_identities.diagnostics()["confirmed_fish_ids"] == 1
