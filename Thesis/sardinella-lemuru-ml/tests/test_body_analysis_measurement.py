"""Measurement availability is independent of geometry/calibration eligibility."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from src.inference.body_width import BodyWidthConfig, analyze_body_width, supplement_body_scores
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, crop_fish
from src.inference.yolo_quality_model import YoloQualityModel


WHOLE = (100, 100, 772, 1611)
PARTS = (
    PartDetection.from_source_class(1, .9, (240, 150, 600, 420)),
    PartDetection.from_source_class(0, .9, (145, 500, 728, 1178)),
    PartDetection.from_source_class(2, .9, (300, 1370, 580, 1560)),
)


def calibrated(**changes):
    return BodyWidthConfig(calibration_validated=True, calibration_id="synthetic-measurement-tests",
                           validation_sample_count=20, normal_reference_min=.1,
                           normal_reference_max=.2, extreme_reference=.4, **changes)


def quality_model(parts, padding=0):
    quality = YoloQualityModel(
        Path("measurement-test-only.pt"), model_id="measurement-test-only", device="cpu",
        roi_padding=padding,
        grading_engine=WeightedGradingEngine(GradingConfig(), body_width_config=BodyWidthConfig()),
    )
    quality.model = object()
    quality._infer_parts = lambda _: (list(parts), list(parts))
    return quality


def test_reported_672_by_1511_fish_and_583_by_678_body_are_measured_without_calibration():
    result = analyze_body_width(WHOLE, PARTS, frame_shape=(1800, 2000, 3))
    assert (result["whole_fish_width_px"], result["whole_fish_height_px"]) == (672, 1511)
    assert (result["body_width_px"], result["body_height_px"]) == (583, 678)
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Measured"
    assert result["measurement_available"]
    assert result["reliable_for_scoring"]
    assert result["calibration_status"] == "Not Calibrated"
    assert result["class_c_supporting_points"] is None


def test_body_without_head_tail_keeps_dimensions_and_ratio_with_explicit_uncertainty():
    result = analyze_body_width(WHOLE, [PARTS[1]])
    assert result["body_bbox"] == list(PARTS[1].bbox)
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Unreliable"
    assert result["calibration_status"] == "Not Calibrated"
    assert not result["reliable_for_scoring"]
    assert "orientation_unconfirmed" in result["reliability_reasons"]


def test_missing_body_keeps_whole_dimensions_without_inventing_width():
    result = analyze_body_width(WHOLE, [PARTS[0], PARTS[2]])
    assert result["whole_fish_height_px"] == 1511
    assert result["body_width_px"] is None
    assert result["relative_width_proxy"] is None
    assert result["measurement_status"] == "Missing Detection"
    assert not result["measurement_available"]
    assert not result["reliable_for_scoring"]


@pytest.mark.parametrize("options", [{"overlapping": True}, {"clipped": True}, {"association_reliable": False}])
def test_existing_diagnostic_measurements_survive_reliability_rejections_without_points(options):
    cfg = calibrated(scoring_enabled=True)
    result = analyze_body_width(WHOLE, PARTS, config=cfg, **options)
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Unreliable"
    assert result["calibration_status"] == "Calibrated"
    assert result["class_c_supporting_points"] is None
    assert not result["reliable_for_scoring"]
    # Even a stale external points field cannot activate unreliable evidence.
    stale = {**result, "class_c_supporting_points": 10, "score_status": "Calibrated"}
    raw = {"Body": {"Class B": .55, "Class C": .45}}
    adjusted, analysis = supplement_body_scores(raw, stale, cfg)
    assert adjusted == raw
    assert not analysis["score_contributed"]


def test_diagonal_ratio_is_visible_without_fabricating_rotated_anatomical_width():
    parts = [PartDetection.from_source_class(1, .9, (20, 20, 40, 40)),
             PartDetection.from_source_class(0, .9, (45, 45, 80, 80)),
             PartDetection.from_source_class(2, .9, (90, 90, 110, 110))]
    result = analyze_body_width((10, 10, 120, 120), parts, config=calibrated(scoring_enabled=True))
    assert result["relative_width_proxy"] == pytest.approx(35 / 110)
    assert result["orientation"] == "diagonal"
    assert result["measurement_status"] == "Unreliable"
    assert not result["reliable_for_scoring"]
    assert result["class_c_supporting_points"] is None


def test_predict_translates_explicit_crop_bounds_and_keeps_original_pixel_sizes():
    bounds = CropBounds(100, 100, 772, 1611)
    local = [replace(part, bbox=tuple(value - 100 for value in part.bbox)) for part in PARTS]
    quality = quality_model(local)
    observation = quality.predict(np.zeros((1511, 672, 3), dtype=np.uint8), 1, stabilize=False,
                                  detection_confidence=.99, parent_bbox=WHOLE,
                                  frame_shape=(1800, 2000, 3), crop_bounds=bounds)
    result = observation.analysis["body_width"]
    assert result["body_bbox"] == list(PARTS[1].bbox)
    assert result["whole_fish_bbox"] == list(WHOLE)
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Measured"
    assert result["coordinate_space"] == "original_frame"
    assert result["coordinate_origin_source"] == "explicit_crop_bounds"
    json.dumps(observation.analysis)  # CropBounds objects must not leak to history.


def test_predict_verifies_existing_floor_ceil_padding_geometry_when_bounds_omitted():
    frame = np.zeros((1800, 2000, 3), dtype=np.uint8)
    whole = (100.25, 100.5, 772.25, 1611.5)
    crop, bounds = crop_fish(frame, whole, padding=11)
    local = [replace(part, bbox=(part.bbox[0] - bounds.x1, part.bbox[1] - bounds.y1,
                                part.bbox[2] - bounds.x1, part.bbox[3] - bounds.y1)) for part in PARTS]
    quality = quality_model(local, padding=11)
    observation = quality.predict(crop, 1, stabilize=False, detection_confidence=.99,
                                  parent_bbox=whole, frame_shape=frame.shape)
    result = observation.analysis["body_width"]
    assert result["body_bbox"] == list(PARTS[1].bbox)
    assert result["whole_fish_width_px"] == 672
    assert result["whole_fish_height_px"] == 1511
    assert result["coordinate_origin_source"] == "verified_parent_crop_geometry"
    assert result["measurement_status"] == "Measured"


def test_unverified_crop_origin_does_not_discard_dimensions_or_grant_scoring_reliability():
    local = [replace(part, bbox=tuple(value - 100 for value in part.bbox)) for part in PARTS]
    quality = quality_model(local)
    observation = quality.predict(np.zeros((1600, 700, 3), dtype=np.uint8), 1, stabilize=False,
                                  parent_bbox=WHOLE, frame_shape=(1800, 2000, 3))
    result = observation.analysis["body_width"]
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Unreliable"
    assert result["coordinate_space"] == "unverified"
    assert not result["reliable_for_scoring"]
    assert not result["score_contributed"]


def test_inconsistent_explicit_bounds_are_not_silently_replaced_with_another_origin():
    local = [replace(part, bbox=tuple(value - 100 for value in part.bbox)) for part in PARTS]
    quality = quality_model(local)
    observation = quality.predict(np.zeros((1511, 672, 3), dtype=np.uint8), 1, stabilize=False,
                                  parent_bbox=WHOLE, frame_shape=(1800, 2000, 3),
                                  crop_bounds=(0, 0, 672, 1510))
    result = observation.analysis["body_width"]
    assert result["measurement_status"] == "Unreliable"
    assert result["coordinate_origin_source"] == "unverified"
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)


def test_width_reliability_respects_explicit_parent_usable_flag():
    local = [replace(part, bbox=tuple(value - 100 for value in part.bbox)) for part in PARTS]
    quality = quality_model(local)
    observation = quality.predict(np.zeros((1511, 672, 3), dtype=np.uint8), 1, stabilize=False,
                                  parent_bbox=WHOLE, frame_shape=(1800, 2000, 3),
                                  frame_quality={"usable": True, "parent_usable": False})
    result = observation.analysis["body_width"]
    assert result["relative_width_proxy"] == pytest.approx(583 / 1511)
    assert result["measurement_status"] == "Unreliable"
    assert "parent_evidence_unreliable" in result["reliability_reasons"]
    assert not result["reliable_for_scoring"]
    assert observation.quality is None
