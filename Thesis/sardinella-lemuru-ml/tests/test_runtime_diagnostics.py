"""Regression tests for bounded runtime diagnosis; no camera hardware needed."""

from __future__ import annotations

import tempfile
import unittest
import io
import json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from time import monotonic

import cv2
import numpy as np

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig
from src.api.runtime_diagnostics import LatestFrameQueue, RuntimeDiagnostics
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.association import ParentAnchor
from src.inference.yolo_fish_detector import FishDetection, YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel
from src.evaluation.model2_schedule_benchmark import replay
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


class _Scalar:
    def __init__(self, value: float) -> None:
        self.value = value

    def item(self) -> float:
        return self.value


class _Box:
    def __init__(self, class_id: int, confidence: float, bbox: tuple[float, float, float, float]) -> None:
        self.cls, self.conf = _Scalar(class_id), _Scalar(confidence)
        self.xyxy = [np.asarray(bbox, dtype=np.float32)]


class _QualityModel:
    task = "detect"
    names = dict(SOURCE_CLASSES)

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, **_kwargs):
        self.calls += 1
        return [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .90, (3, 3, 25, 20)), _Box(1, .31, (26, 3, 38, 20))])]


class _FishModel:
    model = object()
    last_inference_seconds = .001
    last_tracking_seconds = .001
    weights_path = None
    checkpoint_sha256 = None
    tracker_backend = "test"

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, _frame):
        self.calls += 1
        return [Detection(0, "Fish", .85, (10.0, 10.0, 50.0, 35.0), 7)]

    def reset_tracker(self) -> None:
        pass


class LatestFrameQueueTests(unittest.TestCase):
    def test_replaces_stale_frame_and_remains_bounded(self) -> None:
        queue = LatestFrameQueue()
        queue.offer("old", captured_at=1.0)
        queue.offer("latest", captured_at=2.0)
        self.assertEqual(queue.take(timeout=0).frame, "latest")
        snapshot = queue.snapshot()
        self.assertEqual(snapshot["capacity"], 1)
        self.assertEqual(snapshot["depth"], 0)
        self.assertEqual(snapshot["dropped_frames"], 1)
        self.assertEqual(snapshot["processed_frames"], 1)


class RuntimeMetricsTests(unittest.TestCase):
    def test_recording_can_be_disabled_without_changing_queue(self) -> None:
        metrics = RuntimeDiagnostics(enabled=False)
        metrics.record_latency("model1", .1)
        metrics.record_call("model1")
        metrics.increment("other")
        metrics.record_confidence("body", .9)
        snapshot = metrics.snapshot()
        self.assertFalse(snapshot["recording_enabled"])
        self.assertEqual(snapshot["timings"], {})
        self.assertEqual(snapshot["counters"], {})
        queue = LatestFrameQueue()
        queue.offer("frame")
        self.assertEqual(queue.take(timeout=0).frame, "frame")

    def test_empty_nonfinite_and_bounded_samples(self) -> None:
        metrics = RuntimeDiagnostics(sample_limit=10)
        self.assertEqual(metrics.snapshot()["timings"], {})
        self.assertIsNone(metrics._summary([])["p95"])
        for value in (None, -1.0, float("nan"), float("inf")):
            metrics.record_latency("bad", value)
        metrics.record_latency("single", .001)
        for value in range(15):
            metrics.record_latency("bounded", value / 1000)
        snapshot = metrics.snapshot()
        self.assertNotIn("bad", snapshot["timings"])
        self.assertEqual(snapshot["timings"]["single"]["p95"], 1.0)
        self.assertEqual(snapshot["timings"]["bounded"]["count"], 10)

    def test_rates_use_monotonic_window_without_future_events(self) -> None:
        metrics = RuntimeDiagnostics()
        metrics.record_call("model2", when=8.0)
        metrics.record_call("model2", when=9.5)
        metrics.record_call("model2", when=10.5)
        with patch("src.api.runtime_diagnostics.monotonic", return_value=10.0):
            snapshot = metrics.snapshot()
        self.assertEqual(snapshot["counters"]["model2"], 3)
        self.assertEqual(snapshot["calls_per_second"]["model2"], 1)

    def test_service_records_observational_persistence_and_stream_metrics(self) -> None:
        service = CameraInspectionService(InspectionState(), _FishModel())

        service.record_event_persistence(.012)
        service.record_stream_dispatch(.034)

        diagnostics = service.runtime_diagnostics()
        performance = diagnostics["performance"]
        self.assertEqual(performance["timings"]["event_persistence"]["count"], 1)
        self.assertEqual(performance["timings"]["mjpeg_dispatch"]["count"], 1)
        self.assertEqual(performance["counters"]["mjpeg_dispatch"], 1)
        self.assertIn("capture_to_publish", diagnostics["timing_provenance"])
        self.assertIn("first_detection_to_decision", diagnostics["timing_provenance"])

    def test_crossing_records_first_detection_to_decision_metric(self) -> None:
        class CrossingFish(_FishModel):
            def __init__(self) -> None:
                super().__init__()
                self._detections = iter((
                    [Detection(0, "Fish", .9, (20, 5, 40, 25), 7)],
                    [Detection(0, "Fish", .9, (60, 5, 80, 25), 7)],
                ))

            def predict(self, _frame):
                return next(self._detections)

        state = InspectionState(TrackingConfig(line_position=.5))
        service = CameraInspectionService(state, CrossingFish())
        frame = np.zeros((40, 100, 3), dtype=np.uint8)

        service.process_frame(frame, cv2)
        service.process_frame(frame, cv2)

        timing = service.runtime_diagnostics()["performance"]["timings"]["first_detection_to_decision"]
        self.assertEqual(timing["count"], 1)
        self.assertGreaterEqual(timing["p50"], 0.0)
        event = state.tracking.archive_history()[0]
        self.assertIn("conveyor_timing", event["analysis"])


class Model2RuntimeTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "last.pt"
        self.path.touch()
        self.backend = _QualityModel()
        self.quality = YoloQualityModel(
            self.path,
            confidence_threshold=.5,
            device="cpu",
            model_factory=lambda _path: self.backend,
            grading_engine=WeightedGradingEngine(GradingConfig(minimum_track_observations=1)),
        )
        self.assertTrue(self.quality.load(), self.quality.error)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_short_detector_dropouts_preserve_track_evidence_until_timeout(self) -> None:
        fish = _FishModel()
        detection = Detection(0, "Fish", .9, (10, 10, 50, 35), 7)
        service = CameraInspectionService(InspectionState(TrackingConfig(track_timeout=1.5)), fish, quality_model=self.quality, quality_interval=3)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=[[detection], [], [], [detection]]):
            for when in (10.0, 10.5, 11.0, 11.4):
                with patch("src.api.camera.monotonic", return_value=when):
                    service.process_frame(frame, cv2)
                self.assertIn(7, service._track_grades)
                self.assertIn(7, self.quality._grading_engine._tracks)
                if when in (10.5, 11.0):
                    self.assertEqual(self.quality._grading_engine._tracks[7].candidate_frame_count, 1)
        self.assertEqual(self.backend.calls, 2)
        self.assertEqual(self.quality._grading_engine._tracks[7].candidate_frame_count, 2)

    def test_expired_reused_id_starts_with_fresh_evidence(self) -> None:
        fish = _FishModel()
        detection = Detection(0, "Fish", .9, (10, 10, 50, 35), 7)
        service = CameraInspectionService(InspectionState(TrackingConfig(track_timeout=1.5)), fish, quality_model=self.quality, quality_interval=5)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=[[detection], [detection]]):
            for when in (10.0, 11.6):
                with patch("src.api.camera.monotonic", return_value=when):
                    service.process_frame(frame, cv2)
        self.assertEqual(self.backend.calls, 2)
        self.assertEqual(self.quality._grading_engine._tracks[7].candidate_frame_count, 1)

    def test_expired_missing_track_is_removed_without_disturbing_visible_neighbor(self) -> None:
        fish = _FishModel()
        first = Detection(0, "Fish", .9, (10, 10, 50, 35), 7)
        neighbor = Detection(0, "Fish", .9, (15, 10, 55, 35), 8)
        service = CameraInspectionService(InspectionState(TrackingConfig(track_timeout=1.5)), fish, quality_model=self.quality)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=[[first, neighbor], [neighbor], [neighbor]]):
            for when in (10.0, 11.0, 11.6):
                with patch("src.api.camera.monotonic", return_value=when):
                    service.process_frame(frame, cv2)
        self.assertNotIn(7, service._track_grades)
        self.assertNotIn(7, self.quality._grading_engine._tracks)
        self.assertIn(8, self.quality._grading_engine._tracks)

    def test_reset_clears_evidence_before_tracker_id_reuse(self) -> None:
        fish = _FishModel()
        service = CameraInspectionService(InspectionState(), fish, quality_model=self.quality)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        service.process_frame(frame, cv2)
        self.assertIn(7, self.quality._grading_engine._tracks)
        service.reset_session()
        self.assertFalse(self.quality._grading_engine._tracks)
        service.process_frame(frame, cv2)
        new_tracks = self.quality._grading_engine._tracks
        self.assertEqual(len(new_tracks), 1)
        new_id = next(iter(new_tracks))
        self.assertEqual(new_id, 7)  # Session reset permits the first ID again.
        self.assertEqual(new_tracks[new_id].candidate_frame_count, 1)

    def test_model2_failure_at_count_line_abstains_instead_of_reusing_grade(self) -> None:
        fish = _FishModel()
        before = Detection(0, "Fish", .9, (10, 10, 50, 35), 7)
        after = Detection(0, "Fish", .9, (30, 10, 70, 35), 7)
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (3, 3, 25, 20)), _Box(1, .9, (26, 3, 38, 20))])]
        service = CameraInspectionService(InspectionState(TrackingConfig(line_position=.5)), fish, quality_model=self.quality, quality_interval=1)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=[[before], [after]]):
            service.process_frame(frame, cv2)
            self.assertEqual(service._track_grades[7].quality, "Class A")
            with patch.object(self.backend, "predict", side_effect=RuntimeError("synthetic inference failure")):
                service.process_frame(frame, cv2)
        event = service.state.tracking.archive_history()[0]
        self.assertIsNone(event["quality"])
        self.assertIn("UG_MODEL2_UNAVAILABLE", event["analysis"]["reason_codes"])
        self.assertFalse(service._latest_part_overlays.get(7))

    def test_partial_crop_failure_backoff_and_recovery(self) -> None:
        class FishPair(_FishModel):
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (10, 10, 50, 35), 7), Detection(0, "Fish", .9, (50, 10, 90, 35), 8)]

        result = [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (3, 3, 25, 20)), _Box(1, .9, (26, 3, 38, 20))])]
        service = CameraInspectionService(InspectionState(), FishPair(), quality_model=self.quality, quality_interval=1)
        frame = np.zeros((60, 100, 3), dtype=np.uint8)
        with patch.object(self.backend, "predict", side_effect=[result, RuntimeError("adapter failed"), result, result]) as predict:
            with patch("src.api.camera.monotonic", return_value=10.0):
                service.process_frame(frame, cv2)
            self.assertEqual(service._track_grades[7].quality, "Class A")
            self.assertIn("UG_MODEL2_UNAVAILABLE", service._track_grades[8].analysis["reason_codes"])
            self.assertEqual(predict.call_count, 2)
            with patch("src.api.camera.monotonic", return_value=10.1):
                service.process_frame(frame, cv2)
            self.assertEqual(predict.call_count, 2)
            self.assertTrue(all(service._track_grades[id].quality is None for id in (7, 8)))
            with patch("src.api.camera.monotonic", return_value=10.3):
                service.process_frame(frame, cv2)
            self.assertEqual(predict.call_count, 4)
            self.assertEqual(service._track_grades[8].quality, "Class A")
            self.assertEqual(service._model2_failure_count, 0)
            self.assertEqual(service.state.segmenter_status, "ready")

    def test_repeated_failures_use_a_capped_retry_delay(self) -> None:
        service = CameraInspectionService(InspectionState(), _FishModel(), quality_model=self.quality, quality_interval=1)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        when = 10.0
        with patch.object(self.backend, "predict", side_effect=RuntimeError("failed")):
            for expected in (.25, .5, 1.0, 2.0, 4.0, 5.0, 5.0):
                with patch("src.api.camera.monotonic", return_value=when):
                    service.process_frame(frame, cv2)
                self.assertAlmostEqual(service._model2_retry_after - when, expected)
                when = service._model2_retry_after

    def test_abstention_adapter_failure_still_counts_fish_with_reason(self) -> None:
        fish = _FishModel()
        before = Detection(0, "Fish", .9, (10, 10, 50, 35), 7)
        after = Detection(0, "Fish", .9, (30, 10, 70, 35), 7)
        service = CameraInspectionService(InspectionState(TrackingConfig(line_position=.5)), fish, quality_model=self.quality, quality_interval=1)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=[[before], [after]]), patch.object(self.backend, "predict", side_effect=RuntimeError("inference failed")), patch.object(self.quality, "unavailable_observation", side_effect=RuntimeError("abstention failed")):
            service.process_frame(frame, cv2)
            service.process_frame(frame, cv2)
        event = service.state.tracking.archive_history()[0]
        self.assertIsNone(event["quality"])
        self.assertEqual(event["analysis"]["verdict_reason_code"], "UG_MODEL2_UNAVAILABLE")
        self.assertFalse(event["parts"])

    def test_partial_full_frame_failure_clears_all_affected_temporal_evidence(self) -> None:
        class FishPair(_FishModel):
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (0, 0, 50, 40), 7), Detection(0, "Fish", .9, (50, 0, 100, 40), 8)]

        service = CameraInspectionService(InspectionState(), FishPair(), quality_model=self.quality, quality_interval=1, quality_inference_mode="full_frame")
        frame = np.zeros((60, 100, 3), dtype=np.uint8)
        def partial_failure(*_args, **_kwargs):
            self.quality.predict(frame[:, :50], 7, frame_id=service._frame_index)
            raise RuntimeError("second fish failed")
        with patch.object(self.quality, "predict_full_frame", side_effect=partial_failure):
            service.process_frame(frame, cv2)
        for track_id in (7, 8):
            self.assertIsNone(service._track_grades[track_id].quality)
            self.assertIn("UG_MODEL2_UNAVAILABLE", service._track_grades[track_id].analysis["reason_codes"])
            self.assertEqual(self.quality._grading_engine._tracks[track_id].candidate_frame_count, 1)
            self.assertFalse(self.quality._grading_engine._tracks[track_id].model2_available)

    def test_model2_failure_does_not_rewrite_finalized_fish(self) -> None:
        fish = _FishModel()
        frames = [
            [Detection(0, "Fish", .9, (10, 10, 50, 35), 7)],
            [Detection(0, "Fish", .9, (30, 10, 70, 35), 7)],
            [Detection(0, "Fish", .9, (30, 10, 70, 35), 7), Detection(0, "Fish", .9, (5, 10, 35, 35), 8)],
        ]
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (3, 3, 25, 20)), _Box(1, .9, (26, 3, 38, 20))])]
        service = CameraInspectionService(InspectionState(TrackingConfig(line_position=.5)), fish, quality_model=self.quality, quality_interval=1)
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        with patch.object(fish, "predict", side_effect=frames):
            service.process_frame(frame, cv2)
            service.process_frame(frame, cv2)
            prior = service.state.tracking.archive_history()[0]
            with patch.object(self.backend, "predict", side_effect=RuntimeError("failed")):
                service.process_frame(frame, cv2)
        self.assertEqual(service.state.tracking.archive_history()[0], prior)
        self.assertIn("UG_MODEL2_UNAVAILABLE", service._track_grades[8].analysis["reason_codes"])

    def test_full_frame_inference_is_recorded_once_and_each_fish_has_own_grading_time(self) -> None:
        class FishPair(_FishModel):
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (0, 0, 100, 100), 7),
                        Detection(0, "Fish", .9, (120, 0, 220, 100), 8)]

        service = CameraInspectionService(InspectionState(), FishPair(), quality_model=self.quality, quality_inference_mode="full_frame")
        grade_parts = self.quality._grade_parts
        def timed_grade(*args, **kwargs):
            observation = grade_parts(*args, **kwargs)
            observation.analysis["performance"]["grading_engine_ms"] = float(observation.track_id)
            return observation
        with patch.object(self.quality, "_grade_parts", side_effect=timed_grade):
            service.process_frame(np.zeros((120, 240, 3), dtype=np.uint8), cv2)
        metrics = service.runtime_diagnostics()["performance"]
        self.assertEqual(metrics["counters"]["model2"], 1)
        self.assertEqual(metrics["counters"]["model2_roi"], 2)
        self.assertEqual(metrics["timings"]["model2_inference"]["count"], 1)
        self.assertEqual(metrics["timings"]["grading_engine"]["count"], 2)
        self.assertEqual(metrics["timings"]["grading_engine"]["min"], 7.0)
        self.assertEqual(metrics["timings"]["grading_engine"]["max"], 8.0)
        self.assertEqual(metrics["timings"]["part_assignment"]["count"], 1)

    def test_crop_mode_records_multiple_model_calls_in_one_frame(self) -> None:
        class FishPair(_FishModel):
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (0, 0, 100, 100), 7),
                        Detection(0, "Fish", .9, (120, 0, 220, 100), 8)]
        service = CameraInspectionService(InspectionState(), FishPair(), quality_model=self.quality, quality_inference_mode="crop")
        service.process_frame(np.zeros((120, 240, 3), dtype=np.uint8), cv2)
        metrics = service.runtime_diagnostics()["performance"]
        self.assertEqual(metrics["counters"]["model2"], 2)
        self.assertEqual(metrics["timings"]["model2_inference"]["count"], 2)

    def test_schedule_calls_for_each_mode_interval_and_occupancy(self) -> None:
        # Deterministic plumbing test, not a model-speed or accuracy benchmark.
        class StationaryFish(_FishModel):
            def __init__(self, count: int) -> None:
                super().__init__()
                self.count = count

            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (index * 40, 0, index * 40 + 35, 40), index + 1)
                        for index in range(self.count)]

        frame = np.zeros((60, 250, 3), dtype=np.uint8)
        for occupancy in (0, 1, 3, 6):
            for interval in (1, 2, 3, 4):
                for mode in ("full_frame", "crop"):
                    with self.subTest(occupancy=occupancy, interval=interval, mode=mode):
                        self.quality.reset_tracks()
                        self.backend.calls = 0
                        service = CameraInspectionService(InspectionState(), StationaryFish(occupancy),
                                                          quality_model=self.quality, quality_interval=interval,
                                                          quality_inference_mode=mode)
                        for _ in range(8):
                            service.process_frame(frame, cv2)
                        due_frames = (7 // interval) + 1
                        expected_calls = (0 if not occupancy else due_frames * (occupancy if mode == "crop" else 1))
                        self.assertEqual(self.backend.calls, expected_calls)
                        self.assertEqual(service.runtime_diagnostics()["performance"]["counters"].get("model2", 0), expected_calls)
                        self.assertEqual(len(service.state.tracking.archive_history()), 0)

    def test_video_replay_collects_actual_calls_and_trace_without_claiming_truth(self) -> None:
        class FakeCapture:
            def __init__(self, _path):
                self.frames = 0
            def isOpened(self):
                return True
            def read(self):
                self.frames += 1
                return (True, np.zeros((60, 80, 3), dtype=np.uint8)) if self.frames <= 4 else (False, None)
            def release(self):
                pass
        fish = _FishModel()
        for mode in ("full_frame", "crop"):
            with self.subTest(mode=mode), patch("src.evaluation.model2_schedule_benchmark.cv2.VideoCapture", FakeCapture):
                trace = io.StringIO()
                result = replay(Path("fixture.mp4"), (80, 60), fish, self.quality, mode, 2, trace)
                rows = [json.loads(line) for line in trace.getvalue().splitlines()]
                self.assertEqual(result["frames"], 4)
                self.assertEqual(result["model2_invocations"], 2)
                self.assertEqual(len(rows), 4)
                self.assertEqual(rows[0]["detections"][0]["track_id"], 7)
                self.assertEqual(rows[0]["observations"][0]["track_id"], 7)
                self.assertEqual(rows[1]["observations"], [])

    def test_raw_model2_serialization_keeps_rejected_candidate_out_of_grading(self) -> None:
        self.quality.set_debug_raw_output(True)
        observation = self.quality.predict(np.zeros((40, 50, 3), dtype=np.uint8), 7, stabilize=False)
        trace = observation.analysis["model2_debug"]
        self.assertEqual(len(trace["raw_detections"]), 2)
        self.assertEqual(len(trace["selected_detections"]), 1)
        self.assertEqual(len(trace["rejected_detections"]), 1)
        self.assertEqual(observation.parts[0].confidence, .90)
        self.assertEqual(self.backend.calls, 1)

    def test_overlapping_unscheduled_fish_remains_an_ownership_competitor(self) -> None:
        class OverlappingFish(_FishModel):
            def predict(self, _frame):
                return [
                    Detection(0, "Fish", .9, (0, 0, 120, 100), 7),
                    Detection(0, "Fish", .9, (5, 0, 125, 100), 8),
                ]

        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (50, 20, 75, 55))])]
        state = InspectionState()
        state.tracking.update([Detection(0, "Fish", .9, (5, 0, 125, 100), 8)], (140, 120))
        service = CameraInspectionService(state, OverlappingFish(), quality_model=self.quality, quality_interval=3, quality_inference_mode="full_frame")  # type: ignore[arg-type]
        service._frame_index = 1
        service._last_segmented_frame[8] = 1
        service.process_frame(np.zeros((120, 140, 3), dtype=np.uint8), cv2)
        self.assertIn(7, service._track_grades)
        self.assertNotIn(8, service._track_grades)
        analysis = service._track_grades[7].analysis
        association = analysis["quality_inference"]["association"]
        self.assertTrue(association["ambiguous"])
        self.assertEqual(association["assigned_part_count"], 0)
        self.assertEqual(association["parts"][0]["status"], "AMBIGUOUS")
        self.assertIsNone(service._track_grades[7].quality)
        self.assertNotIn(8, self.quality._grading_engine._tracks)

    def test_finalized_or_untracked_neighbor_remains_an_ownership_competitor(self) -> None:
        class FishPair(_FishModel):
            neighbor_id = 8
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (0, 0, 120, 100), 7), Detection(0, "Fish", .9, (5, 0, 125, 100), self.neighbor_id)]

        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (50, 20, 75, 55))])]
        for neighbor_id in (8, None):
            with self.subTest(neighbor_id=neighbor_id):
                self.quality.reset_tracks()
                detector = FishPair()
                detector.neighbor_id = neighbor_id
                state = InspectionState()
                service = CameraInspectionService(state, detector, quality_model=self.quality, quality_inference_mode="full_frame")  # type: ignore[arg-type]
                counted = [{"track_id": 8, "counted": True}] if neighbor_id == 8 else []
                with patch.object(state.tracking, "active_tracks", return_value=counted):
                    service.process_frame(np.zeros((120, 140, 3), dtype=np.uint8), cv2)
                summary = service._track_grades[7].analysis["quality_inference"]["association"]
                self.assertTrue(summary["ambiguous"])
                self.assertEqual(summary["assigned_part_count"], 0)
                self.assertEqual(set(self.quality._grading_engine._tracks), {7})

    def test_unconfirmed_model1_detection_competes_in_real_full_frame_path(self) -> None:
        class PartialTracker:
            def update(self, detections, _frame):
                return np.asarray([[*detections.xyxy[0], 7, detections.conf[0], 0, 0]])

        detector = YoloFishDetector(None, device="cpu")
        detector._tracker = PartialTracker()
        detector.detect = lambda _frame: [
            FishDetection((0, 0, 120, 100), .9), FishDetection((5, 0, 125, 100), .9),
        ]
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (50, 20, 75, 55))])]
        state = InspectionState()
        service = CameraInspectionService(state, detector, quality_model=self.quality, quality_inference_mode="full_frame")
        service.process_frame(np.zeros((120, 140, 3), dtype=np.uint8), cv2)
        self.assertEqual(service._track_grades, {})
        service.process_frame(np.zeros((120, 140, 3), dtype=np.uint8), cv2)
        association = service._track_grades[1].analysis["quality_inference"]["association"]
        self.assertTrue(association["ambiguous"])
        self.assertEqual(association["assigned_part_count"], 0)
        self.assertIsNone(service._track_grades[1].quality)
        self.assertEqual([item.track_id for item in state.detections], [1, None])
        self.assertEqual({item["track_id"] for item in state.tracking.active_tracks()}, {1})
        self.assertEqual(state.snapshot()["counters"]["total"], 0)

    def test_duplicate_tracker_id_detection_still_competes_for_ownership(self) -> None:
        class DuplicateTrackFish(_FishModel):
            def predict(self, _frame):
                return [Detection(0, "Fish", .9, (0, 0, 120, 100), 7), Detection(0, "Fish", .9, (5, 0, 125, 100), 7)]

        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (50, 20, 75, 55))])]
        service = CameraInspectionService(InspectionState(), DuplicateTrackFish(), quality_model=self.quality, quality_inference_mode="full_frame")  # type: ignore[arg-type]
        service.process_frame(np.zeros((120, 140, 3), dtype=np.uint8), cv2)
        association = service._track_grades[7].analysis["quality_inference"]["association"]
        self.assertEqual(association["parts"][0]["status"], "AMBIGUOUS")
        self.assertEqual(association["assigned_part_count"], 0)
        self.assertIsNone(service._track_grades[7].quality)
        self.assertEqual(set(self.quality._grading_engine._tracks), {7})

    def test_full_frame_subset_keeps_ownership_and_crop_coordinates(self) -> None:
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (30, 20, 60, 55)), _Box(0, .9, (150, 20, 180, 55))])]
        parents = [ParentAnchor(7, (0, 0, 100, 100)), ParentAnchor(8, (120, 0, 220, 100))]
        frame = np.zeros((120, 240, 3), dtype=np.uint8)
        all_results = self.quality.predict_full_frame(frame, parents, stabilize=False)
        subset = self.quality.predict_full_frame(frame, parents, stabilize=False, grade_track_ids={8})
        self.assertEqual(set(subset), {8})
        all_fish, all_bounds = all_results[8]
        selected, bounds = subset[8]
        self.assertEqual(selected.analysis["quality_inference"]["association"], all_fish.analysis["quality_inference"]["association"])
        self.assertEqual(bounds, all_bounds)
        self.assertEqual(selected.parts[0].bbox, (30, 20, 60, 55))
        self.assertEqual(all_results[7][0].parts[0].bbox, (30, 20, 60, 55))
        assigned = [item for item in selected.analysis["quality_inference"]["association"]["parts"] if item["track_id"] == 8]
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]["part"]["bbox"], [150.0, 20.0, 180.0, 55.0])

    def test_full_frame_tail_optional_weights_remain_per_fish(self) -> None:
        self.quality._grading_engine = WeightedGradingEngine(
            GradingConfig(grading_mode="tail_optional_v1", minimum_track_observations=1, image_diagnostics_enabled=False)
        )
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[
            _Box(0, .9, (25, 20, 55, 55)), _Box(1, .9, (5, 20, 20, 55)),
            _Box(3, .8, (145, 20, 175, 55)), _Box(4, .8, (125, 20, 140, 55)),
            _Box(5, .8, (180, 20, 195, 55)),
        ])]
        parents = [ParentAnchor(7, (0, 0, 100, 100)), ParentAnchor(8, (120, 0, 220, 100))]
        results = self.quality.predict_full_frame(np.zeros((120, 240, 3), dtype=np.uint8), parents, stabilize=False)
        first, second = results[7][0], results[8][0]
        self.assertEqual((first.quality, second.quality), ("Class A", "Class B"))
        self.assertEqual(first.analysis["weighting_method"], "head_body_only")
        self.assertEqual(second.analysis["weighting_method"], "three_part")
        self.assertEqual(first.analysis["tail_status"], "not_detected")
        self.assertEqual(second.analysis["tail_status"], "evaluated")
        self.assertAlmostEqual(first.analysis["weights_used"]["Body"], .625)
        self.assertAlmostEqual(second.analysis["weights_used"]["Tail"], .2)

    def test_ineligible_owner_does_not_supply_eligible_fish(self) -> None:
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[_Box(0, .9, (80, 20, 105, 55))])]
        parents = [ParentAnchor(7, (0, 0, 100, 100)), ParentAnchor(8, (40, 0, 140, 100))]
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        all_results = self.quality.predict_full_frame(frame, parents, stabilize=False)
        subset = self.quality.predict_full_frame(frame, parents, stabilize=False, grade_track_ids={7})
        self.assertEqual(set(subset), {7})
        association = subset[7][0].analysis["quality_inference"]["association"]
        self.assertEqual(association, all_results[7][0].analysis["quality_inference"]["association"])
        self.assertEqual(association["parts"][0]["track_id"], 8)
        self.assertEqual(association["parts"][0]["status"], "ASSIGNED")
        self.assertEqual(association["assigned_part_count"], 0)
        self.assertEqual(len(subset[7][0].parts), 0)
        self.assertEqual(len(all_results[8][0].parts), 1)

    def test_one_model2_call_per_scheduled_track_frame_and_finalized_track_is_skipped(self) -> None:
        fish = _FishModel()
        state = InspectionState(TrackingConfig(line_position=.5))
        service = CameraInspectionService(state, fish, quality_model=self.quality, quality_interval=3)  # type: ignore[arg-type]
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        service.process_frame(frame, cv2)
        service.process_frame(frame, cv2)
        self.assertEqual(self.backend.calls, 1)  # interval has not elapsed
        service.process_frame(frame, cv2)
        service.process_frame(frame, cv2)
        self.assertEqual(self.backend.calls, 2)

        # A counted/finalized track is retained by the tracker but must no
        # longer consume Model 2 calls on subsequent scheduled frames.
        now = monotonic()
        state.tracking.update([Detection(0, "Fish", .9, (10, 10, 50, 35), 7)], (80, 60), timestamp=now)
        state.tracking.update([Detection(0, "Fish", .9, (50, 10, 70, 35), 7)], (80, 60), timestamp=now + .1)
        calls_before = self.backend.calls
        service.process_frame(frame, cv2)
        service.process_frame(frame, cv2)
        service.process_frame(frame, cv2)
        self.assertEqual(self.backend.calls, calls_before)
        self.assertGreater(service.runtime_diagnostics()["skipped_model2_reasons"].get("finalized_track", 0), 0)

    def _reset_identity_fixture(self):
        class ReusingDetector(_FishModel):
            def __init__(self):
                super().__init__()
                self.detections = []

            def predict(self, _frame):
                return self.detections

        class FakeWorker:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

            def join(self, timeout=None):
                pass

        detector = ReusingDetector()
        state = InspectionState(TrackingConfig(line_position=.5))
        self.quality._grading_engine = WeightedGradingEngine(
            GradingConfig(grading_mode="tail_optional_v1", minimum_track_observations=1, image_diagnostics_enabled=False)
        )
        selected_class = [0]
        self.backend.predict = lambda **_kwargs: [SimpleNamespace(names=dict(SOURCE_CLASSES), boxes=[
            _Box(selected_class[0], .9, (4, 3, 15, 18)), _Box(selected_class[0] + 1, .9, (1, 3, 4, 18)),
        ])]
        service = CameraInspectionService(state, detector, quality_model=self.quality, quality_interval=1)
        frame = np.full((40, 100, 3), 100, dtype=np.uint8)

        def passage():
            for bbox in ((20, 5, 40, 25), (55, 5, 75, 25)):
                detector.detections = [Detection(0, "Fish", .9, bbox, 7)]
                service.process_frame(frame, cv2)

        return service, state, selected_class, FakeWorker, passage

    def test_stop_restart_preserves_distinct_fish_ids_and_model2_results(self) -> None:
        service, state, selected_class, FakeWorker, passage = self._reset_identity_fixture()
        with patch("src.api.camera.Thread", FakeWorker):
            self.assertTrue(service.start())
            passage()
            first = state.tracking.archive_history()[0]
            self.assertEqual((first["track_id"], first["quality"]), (7, "Class A"))
            self.assertTrue(service.stop())
            self.assertTrue(service.start())
            selected_class[0] = 3
            passage()
            second, original = state.tracking.archive_history()
            self.assertNotEqual(second["track_id"], first["track_id"])
            self.assertEqual((original["quality"], second["quality"]), ("Class A", "Class B"))
            self.assertEqual(second["analysis"]["inference_debug"]["model1_detection"]["fish_id"], second["track_id"])
            self.assertEqual(state.snapshot()["counters"]["total"], 2)
            state.tracking.apply_manual_review(second["track_id"], "Class C")
            reviewed, original = state.tracking.archive_history()
            self.assertEqual(reviewed["manual_grade"], "Class C")
            self.assertIsNone(original["manual_grade"])
            self.assertTrue(service.stop())

    def test_reset_while_inspecting_clears_history_and_scopes_new_model2_evidence(self) -> None:
        service, state, selected_class, FakeWorker, passage = self._reset_identity_fixture()
        with patch("src.api.camera.Thread", FakeWorker):
            self.assertTrue(service.start())
            passage()
            first_id = state.tracking.archive_history()[0]["track_id"]
            service.reset_session()
            self.assertEqual(state.snapshot()["counters"]["total"], 0)
            self.assertEqual(state.tracking.archive_history(), [])
            selected_class[0] = 3
            passage()
            new_event = state.tracking.archive_history()[0]
            self.assertEqual(new_event["track_id"], first_id)
            self.assertEqual(new_event["quality"], "Class B")
            self.assertEqual(new_event["analysis"]["inference_debug"]["model1_detection"]["fish_id"], new_event["track_id"])
            self.assertEqual(state.snapshot()["counters"]["total"], 1)
            self.assertTrue(service.stop())

    def test_not_fish_debug_capture_is_research_only_and_does_not_change_prediction(self) -> None:
        fish = _FishModel()
        service = CameraInspectionService(InspectionState(), fish, quality_model=self.quality)  # type: ignore[arg-type]
        service.debug_enabled = True
        service.debug_capture_limit = 3
        service._hard_negative_root = Path(self.tempdir.name) / "hard_negatives"
        detection = Detection(0, "Fish", .85, (10.0, 10.0, 50.0, 35.0), 7)
        service._frame_index = 12
        service._save_hard_negative_candidate(np.zeros((60, 80, 3), dtype=np.uint8), detection, model2_compatible=False)
        self.assertEqual(fish.calls, 0)
        record = next(iter(service._hard_negative_records.values()))
        marked = service.mark_hard_negative(str(record["capture_id"]))
        self.assertEqual(marked["operator_label"], "NOT_FISH")
        self.assertEqual(detection.confidence, .85)
        self.assertEqual(self.backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
