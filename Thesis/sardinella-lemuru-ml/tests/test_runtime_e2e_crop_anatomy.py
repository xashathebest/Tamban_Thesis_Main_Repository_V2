"""Legacy crop mode applies the same required-pair contradiction safeguard."""
from pathlib import Path

import numpy as np
import pytest

from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.yolo_quality_model import YoloQualityModel


def part(source, bbox, confidence=.9):
    return PartDetection.from_source_class(source, confidence, bbox)


def predict(parts):
    model = YoloQualityModel(Path("crop-anatomy-test-only.pt"), device="cpu", quality_inference_mode="crop",
                             grading_engine=WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1",
                                                                                image_diagnostics_enabled=False)))
    model.model = object()
    calls = []
    def infer(image):
        calls.append(image.shape)
        return list(parts), list(parts)
    model._infer_parts = infer
    result = model.predict(np.full((100, 100, 3), 100, np.uint8), 7, stabilize=False, frame_id="crop-geometry")
    assert calls == [(100, 100, 3)]
    return result


@pytest.mark.parametrize("tail", [False, True])
def test_concentric_required_parts_are_withheld_in_crop_mode_with_or_without_tail(tail):
    parts = [part(0, (20, 20, 60, 60)), part(1, (30, 30, 50, 50))]
    if tail:
        parts.append(part(2, (70, 30, 90, 50)))
    result = predict(parts)
    assert result.quality is None
    assert "UG_ASSOCIATION_AMBIGUOUS" in result.analysis["reason_codes"]
    check = result.analysis["quality_inference"]["required_pair_geometry"]
    assert check["required_pair_inconsistent"] is True
    assert check["reason"] == "required_anatomical_group_inconsistent"
    assert check["coordinate_space"] == "crop_local"
    assert [(item.source_class_id, item.bbox, item.confidence) for item in result.parts] == [
        (item.source_class_id, item.bbox, item.confidence) for item in parts]
    assert [item["bbox"] for item in result.analysis["model2_debug"]["raw_detections"]] == [list(item.bbox) for item in parts]


@pytest.mark.parametrize("tail", [False, True])
def test_distinct_naturally_overlapping_required_parts_keep_the_original_crop_grade(tail):
    parts = [part(0, (20, 20, 70, 60)), part(1, (10, 20, 40, 50))]
    if tail:
        parts.append(part(2, (75, 30, 95, 50)))
    result = predict(parts)
    assert result.quality == "Class A"
    assert result.analysis["quality_inference"]["required_pair_geometry"]["required_pair_inconsistent"] is False
    assert result.analysis["weighted_scores"]["Class A"] == pytest.approx(.9)


def test_crop_guard_uses_the_strongest_required_region_candidates():
    parts = [part(0, (20, 20, 60, 60)), part(1, (5, 30, 25, 50), .95),
             part(1, (30, 30, 50, 50), .4)]
    result = predict(parts)
    assert result.quality == "Class A"
    assert result.analysis["quality_inference"]["required_pair_geometry"]["head_bbox"] == [5, 30, 25, 50]
