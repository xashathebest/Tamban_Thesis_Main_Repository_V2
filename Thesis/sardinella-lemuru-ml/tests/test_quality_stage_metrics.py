"""Stage scopes remain truthful without initializing or synchronizing CUDA."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from src.inference.stage_metrics import gpu_memory_snapshot, mask_stage_metrics


def test_memory_telemetry_does_not_initialize_cuda(monkeypatch):
    cuda = SimpleNamespace(is_initialized=lambda: False, current_device=Mock(side_effect=AssertionError("No CUDA access")))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    report = gpu_memory_snapshot()
    assert report["status"] == "unavailable"
    assert "no initialization" in report["reason"]
    cuda.current_device.assert_not_called()


def test_memory_report_is_existing_process_allocator_not_training_device_usage(monkeypatch):
    cuda = SimpleNamespace(is_initialized=lambda: True, current_device=lambda: 2,
                           memory_allocated=lambda device: 100, memory_reserved=lambda device: 200,
                           max_memory_allocated=lambda device: 150)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    report = gpu_memory_snapshot()
    assert report["scope"] == "this_process_allocator"
    assert report["device"] == "cuda:2" and report["allocated_bytes"] == 100
    assert report["reserved_bytes"] == 200 and report["peak_allocated_bytes"] == 150
    assert "process_lifetime" in report["peak_scope"]
    assert "Excludes other processes" in report["note"]


def test_mask_child_operations_are_separate_from_inclusive_wall_time():
    stages = {"source_resize": 1, "grabcut": 20, "raw_components": 2,
              "morphology": 3, "final_components": 4, "native_lift": 5}
    report = mask_stage_metrics({"segmentation_ms": 36, "lookup_ms": 2, "segmentation_stage_ms": stages})
    assert report["foreground_grabcut_ms"] == 20
    assert report["mask_preprocessing_ms"] == 15
    assert report["segmentation_processing_ms"] == 36
    assert report["mask_cache_lookup_ms"] == 2
    assert report["segmentation_backend"] == "opencv_cpu"
    assert mask_stage_metrics({})["mask_preprocessing_ms"] is None
    failed = mask_stage_metrics({"segmentation_ms": 36, "generation_failures": 1, "segmentation_stage_ms": stages})
    assert failed["segmentation_processing_ms"] == 36
    assert failed["foreground_grabcut_ms"] is failed["mask_preprocessing_ms"] is None
    assert failed["segmentation_child_timings_complete"] is False


def test_photo_records_fish_and_shared_frame_scopes_without_duplicate_totals():
    from src.api.image_analysis import StillImageAnalyzer
    from src.evaluation.fixbody_benchmark import PARENT, quality, scene
    from src.inference.yolo_fish_detector import FishDetection
    detector = SimpleNamespace(model=object(), detect=lambda _: [FishDetection(PARENT, .98)])
    result = StillImageAnalyzer(detector, quality("full_frame")).analyze(scene("clean"))
    frame = result["performance"]
    fish = result["fish"][0]["analysis"]
    assert fish["frame_performance"] == frame
    assert fish["mask_context"] == frame["mask_context"]
    assert fish["performance"]["scope"] == "current_fish_observation"
    assert fish["performance"]["total_processing_scope"] == "whole_original_frame_legacy_alias"
    assert frame["total_processing_ms"] >= frame["annotation_rendering_ms"] + frame["jpeg_encoding_ms"] - .1
    assert fish["performance"]["grading_engine_ms"] >= fish["performance"]["color_processing_ms"] + fish["performance"]["texture_processing_ms"] - .1
    assert "must not be added" in frame["timing_relationships"]["total_processing_ms"]
    assert fish["performance"]["model2_inference_ms"] is None  # Recorded outputs: no model was timed.
    assert frame["gpu_memory"]["scope"] == "this_process_allocator"
