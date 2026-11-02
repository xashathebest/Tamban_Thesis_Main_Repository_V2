"""Live diagnostics honor Model 2 cadence and report honest frame stage scopes."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.api import camera
from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig
from src.evaluation.fixbody_benchmark import PARENT, quality, scene
from src.inference.preprocessing import CropBounds, RuntimeMaskContext
from src.inference.yolo_quality_model import FishQualityObservation


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    monkeypatch.setenv("FISH_RUNTIME_TELEMETRY", "1")
    def create(model2=True, interval=3):
        detector = SimpleNamespace(
            model=object(), weights_path=None, confidence_threshold=.5,
            last_inference_seconds=.001,
            predict=lambda _: [Detection(0, "Fish", .98, PARENT, 7)],
        )
        state = InspectionState(TrackingConfig(line_position=.9))
        return CameraInspectionService(
            state, detector, quality_model=quality("full_frame") if model2 else None,
            quality_inference_mode="full_frame", quality_interval=interval,
            camera_profile_path=tmp_path / "profile.yaml",
        )
    return create


def test_model2_gap_frames_do_not_launch_damage_or_segmentation_or_reuse_overlay(build, monkeypatch):
    service = build()
    calls = []
    original = camera.parent_damage
    def count(*args, **kwargs):
        calls.append(kwargs["frame_id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(camera, "parent_damage", count)
    service.process_frame(scene("dark_line"), cv2)
    assert calls == [1]
    previous = dict(service._track_grades[7].analysis["performance"])
    for frame_id in (2, 3):
        service.process_frame(scene("dark_line"), cv2)
        assert calls == [1]
        assert service._frame_damage_results == {}
        assert service._frame_mask_context.diagnostics()["segmentation_calls"] == 0
        assert service._track_grades[7].analysis["performance"] == previous
        frame = service.runtime_diagnostics()["frame_performance"]
        assert frame["frame_id"] == frame_id
        assert frame["quality_observations"] == 0
        assert frame["color_processing_ms"] == frame["texture_processing_ms"] == 0
    service.process_frame(scene("dark_line"), cv2)
    assert calls == [1, 4]


def test_complete_frame_wall_is_separate_from_history_prefix_and_includes_annotation(build):
    service = build()
    service.process_frame(scene("clean"), cv2)
    saved = service._track_grades[7].analysis
    prefix = saved["frame_performance"]
    final = service.runtime_diagnostics()["frame_performance"]
    assert prefix["timing_scope"] == "frame_before_event_tracking_and_annotation"
    assert "excludes capture_wait_jpeg" in final["timing_scope"]
    assert final["total_processing_ms"] >= prefix["total_processing_ms"]
    assert final["annotation_wall_ms"] >= final["annotation_rendering_ms"] > 0
    assert final["color_processing_ms"] > 0 and final["texture_processing_ms"] > 0
    assert final["segmentation_backend"] == "opencv_cpu"
    assert final["mask_context"]["segmentation_calls"] >= 1
    assert saved["performance"]["observation_frame_id"] == final["frame_id"] == 1
    assert "cumulative" in saved["performance"]["mask_context_scope"]
    assert final["gpu_memory"]["scope"] == "this_process_allocator"


def test_frame_aggregation_uses_each_observation_and_counts_shared_model2_once(build):
    service = build()
    service._frame_index = 8
    frame = np.zeros((100, 200, 3), np.uint8)
    service._frame_mask_context = RuntimeMaskContext(frame, frame_id=8)
    service.quality_model.last_grading_seconds = 999
    for track_id, color_ms, texture_ms in ((1, 10., 2.), (2, 20., 3.)):
        observation = FishQualityObservation(track_id, "Class B", .8, (), {"Class B": .8}, {
            "final_grade": "Class B", "final_score": .8, "weighted_scores": {"Class B": .8},
            "performance": {"color_processing_ms": color_ms, "hsv_processing_ms": color_ms,
                            "texture_processing_ms": texture_ms, "model2_inference_ms": 12.},
        })
        detection = Detection(0, "Fish", .9, (10, 10, 90, 60), track_id)
        service._record_quality_observation(detection, observation, CropBounds(10, 10, 90, 60), (50, 80, 3), [])
    result = service._frame_timing_snapshot(90.)
    assert result["quality_observations"] == 2
    assert result["color_processing_ms"] == 30.
    assert result["texture_processing_ms"] == 5.
    assert result["model2_inference_ms"] == 12.
    assert result["model2_inference_scope"] == "shared_frame_once"
    assert result["grading_engine_ms"] is None  # Unknown is not the last fish's 999 seconds.


def test_standalone_diagnostics_preserve_existing_per_frame_cadence(build, monkeypatch):
    service = build(model2=False)
    calls = []
    original = camera.parent_damage
    def count(*args, **kwargs):
        calls.append(kwargs["frame_id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(camera, "parent_damage", count)
    for _ in range(2): service.process_frame(scene("clean"), cv2)
    assert calls == [1, 2]
    final = service.runtime_diagnostics()["frame_performance"]
    assert final["damage_cadence"] == "standalone_each_display_frame"
    assert final["mask_context"]["segmentation_calls"] == 1
    assert final["structural_damage_ms"] > 0
    assert final["annotation_wall_ms"] >= final["annotation_rendering_ms"]
