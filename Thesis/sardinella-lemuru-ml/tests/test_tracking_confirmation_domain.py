"""Domain regressions for confirmed identities and one count per session ID."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from src.api.domain import (
    Detection,
    DetectionConfirmation,
    QualitySummary,
    TrackingConfig,
    TrackingManager,
)


FRAME_SIZE = (100, 100)


def fish(track_id=1, center_x=40, *, center_y=40, confidence=0.9, confirmation=None):
    return Detection(
        0, "Fish", confidence,
        (center_x - 5, center_y - 5, center_x + 5, center_y + 5),
        track_id, confirmation=confirmation,
    )


def confirmed_fish(track_id=1, *, first_x=40, current_x=60, first_at=0.0):
    first = fish(track_id, first_x, confidence=0.7)
    return fish(
        track_id, current_x, confidence=0.9,
        confirmation=DetectionConfirmation(first.bbox, first.confidence, first_at),
    )


class TrackingConfirmationDomainTests(unittest.TestCase):
    def tracker(self):
        return TrackingManager(TrackingConfig(line_position=0.5, track_timeout=1.0))

    def test_confirmation_is_internal_optional_metadata(self):
        plain = fish()
        confirmed = replace(
            plain, confirmation=DetectionConfirmation(plain.bbox, 0.8, 0.0),
        )
        self.assertEqual(plain, confirmed)
        self.assertNotIn("confirmation", repr(confirmed))
        self.assertNotIn("confirmation", plain.to_dict())
        self.assertEqual(confirmed.to_dict()["confirmation"]["timestamp"], 0.0)

    def test_confirmation_preserves_two_frame_crossing_and_counts_once(self):
        tracker = self.tracker()
        events = tracker.update([confirmed_fish()], FRAME_SIZE, timestamp=0.2)

        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].final_confidence, 0.8)
        self.assertEqual(events[0].analysis["track_stability"]["number_of_frames"], 2)
        self.assertEqual(events[0].analysis["conveyor_timing"]["first_detection_to_decision_ms"], 200.0)
        active = tracker.active_tracks()[0]
        self.assertEqual(active["first_seen_monotonic"], 0.0)
        self.assertEqual(active["last_seen_monotonic"], 0.2)
        self.assertEqual(active["observation_count"], 2)
        self.assertEqual(active["track_lifetime_detection_frames"], 2)
        self.assertTrue(active["counted"])

        self.assertEqual(tracker.update([fish(1, 70)], FRAME_SIZE, timestamp=0.3), [])
        self.assertEqual(tracker.active_tracks()[0]["track_lifetime_detection_frames"], 3)
        self.assertEqual(tracker.counters()["total"], 1)

    def test_confirmation_preserves_crossing_for_all_conveyor_directions(self):
        for direction, orientation, first_center, current_center in (
            ("left_to_right", "vertical", (40, 40), (60, 40)),
            ("right_to_left", "vertical", (60, 40), (40, 40)),
            ("top_to_bottom", "horizontal", (40, 40), (40, 60)),
            ("bottom_to_top", "horizontal", (40, 60), (40, 40)),
        ):
            with self.subTest(direction=direction):
                tracker = TrackingManager(TrackingConfig(
                    line_position=0.5, conveyor_direction=direction, line_orientation=orientation,
                ))
                first = fish(center_x=first_center[0], center_y=first_center[1])
                current = fish(
                    center_x=current_center[0], center_y=current_center[1],
                    confirmation=DetectionConfirmation(first.bbox, first.confidence, 1.0),
                )
                self.assertEqual(len(tracker.update([current], FRAME_SIZE, timestamp=1.1)), 1)

    def test_confirmation_before_line_does_not_count_prematurely(self):
        tracker = self.tracker()
        current = confirmed_fish(first_x=20, current_x=40)
        self.assertEqual(tracker.update([current], FRAME_SIZE, timestamp=0.1), [])
        self.assertEqual(tracker.active_tracks()[0]["track_lifetime_detection_frames"], 2)
        self.assertEqual(len(tracker.update([fish(1, 60)], FRAME_SIZE, timestamp=0.2)), 1)
        self.assertEqual(tracker.active_tracks()[0]["track_lifetime_detection_frames"], 3)

    def test_counted_id_does_not_count_after_timeout_and_reentry(self):
        tracker = self.tracker()
        notifications = []
        tracker.add_event_listener(lambda action, event: notifications.append((action, event["track_id"])))
        tracker.update(
            [confirmed_fish()], FRAME_SIZE, timestamp=0.1,
            grades={1: QualitySummary(1, "Class A", 0.9)},
        )
        tracker.update([], FRAME_SIZE, timestamp=2.0)
        self.assertEqual(tracker.active_tracks(), [])

        self.assertEqual(tracker.update([fish(1, 40)], FRAME_SIZE, timestamp=2.1), [])
        returning = tracker.active_tracks()[0]
        self.assertTrue(returning["counted"])
        self.assertEqual(returning["finalized_state"], "counted")
        self.assertEqual(returning["final_class"], "Fish")
        self.assertEqual(returning["quality"], "Class A")
        self.assertEqual(tracker.update([fish(1, 60)], FRAME_SIZE, timestamp=2.2), [])
        self.assertEqual(tracker.counters()["total"], 1)
        self.assertEqual(tracker.quality_counters()["Class A"], 1)
        self.assertEqual(len(tracker.archive_history()), 1)
        self.assertEqual(notifications, [("created", 1)])

    def test_clearing_active_tracks_preserves_completed_id_guard(self):
        tracker = self.tracker()
        tracker.update([confirmed_fish()], FRAME_SIZE, timestamp=0.1)
        tracker.reset_active_tracks()
        self.assertEqual(tracker.update([confirmed_fish()], FRAME_SIZE, timestamp=0.2), [])
        self.assertTrue(tracker.active_tracks()[0]["counted"])
        self.assertEqual(tracker.counters()["total"], 1)

    def test_session_reset_allows_id_reuse(self):
        tracker = self.tracker()
        tracker.update([confirmed_fish()], FRAME_SIZE, timestamp=0.1)
        tracker.reset_session()
        self.assertEqual(tracker.counters()["total"], 0)
        self.assertEqual(len(tracker.update([confirmed_fish()], FRAME_SIZE, timestamp=0.2)), 1)
        self.assertEqual(tracker.counters()["total"], 1)
        self.assertEqual([event["track_id"] for event in tracker.archive_history()], [1])

    def test_completed_id_guard_outlives_archive_and_safe_quality_refresh(self):
        with patch("src.api.domain.SESSION_ARCHIVE_LIMIT", 2):
            tracker = self.tracker()
        for track_id in (1, 2, 3):
            tracker.update(
                [confirmed_fish(track_id)], FRAME_SIZE, timestamp=track_id / 10,
                grades={track_id: QualitySummary(track_id, "Class A", 0.9)},
            )
        self.assertEqual([event["track_id"] for event in tracker.archive_history()], [3, 2])
        tracker.update([], FRAME_SIZE, timestamp=2.0)
        self.assertEqual(tracker.update([fish(1, 40)], FRAME_SIZE, timestamp=2.1), [])
        self.assertEqual(tracker.update(
            [fish(1, 60)], FRAME_SIZE, timestamp=2.2,
            grades={1: QualitySummary(1, "Rejected", 0.8)},
        ), [])
        self.assertTrue(tracker.active_tracks()[0]["counted"])
        self.assertEqual(tracker.counters()["total"], 3)
        self.assertEqual(tracker.quality_counters()["Class A"], 3)

    def test_malformed_noise_never_creates_tracks_or_events(self):
        valid = fish()
        invalid = [
            replace(valid, confidence=value)
            for value in (math.nan, math.inf, -math.inf, -0.1, 1.1, True, "0.9")
        ] + [
            replace(valid, track_id=value)
            for value in (None, 0, -1, 1.5, True, "1", math.nan)
        ] + [
            replace(valid, class_id=1), replace(valid, class_id=False),
            replace(valid, class_name="Class A"),
        ] + [
            replace(valid, bbox=value)
            for value in (
                (0, 0, math.nan, 10), (0, 0, math.inf, 10),
                (10, 0, 0, 10), (0, 10, 10, 0), (0, 0, 0, 10),
                (0, 0, 10, 0), (0, 0, 10), (0, 0, "10", 10), (False, 0, 10, 10),
            )
        ]
        for detection in invalid:
            with self.subTest(detection=detection):
                tracker = self.tracker()
                self.assertEqual(tracker.update([detection], FRAME_SIZE, timestamp=0.0), [])
                self.assertEqual(tracker.active_tracks(), [])
                self.assertEqual(tracker.counters()["total"], 0)

    def test_invalid_confirmation_cannot_seed_a_crossing(self):
        for confirmation in (
            DetectionConfirmation((0, 0, 0, 10), 0.9, 0.0),
            DetectionConfirmation((0, 0, 10, 10), math.nan, 0.0),
            DetectionConfirmation((0, 0, 10, 10), 1.1, 0.0),
            DetectionConfirmation((0, 0, 10, 10), 0.9, math.nan),
            DetectionConfirmation((0, 0, 10, 10), 0.9, 2.0),
        ):
            with self.subTest(confirmation=confirmation):
                tracker = self.tracker()
                current = fish(1, 60, confirmation=confirmation)
                self.assertEqual(tracker.update([current], FRAME_SIZE, timestamp=1.0), [])
                self.assertEqual(tracker.active_tracks(), [])

    def test_domain_does_not_add_a_confidence_threshold_or_crop_image_edges(self):
        tracker = self.tracker()
        first = fish(1, 0, confidence=0.0)
        self.assertEqual(tracker.update([first], FRAME_SIZE, timestamp=0.0), [])
        self.assertEqual(len(tracker.active_tracks()), 1)
        self.assertEqual(len(tracker.update([fish(1, 60, confidence=0.0)], FRAME_SIZE, timestamp=0.1)), 1)


if __name__ == "__main__":
    unittest.main()
