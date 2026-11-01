"""Silhouette geometry follows each parent while preserving weighted grades."""

from copy import deepcopy
import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.body_width import BodyWidthConfig
from src.inference.fish_geometry import PhysicalCalibration
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.inspection_results import normalize_inspection_results
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds
from src.inference.yolo_quality_model import YoloQualityModel


FIXTURE = Path(__file__).parent / "fixtures" / "fish-inspection-upload-all.csv"


def _model(parts, *, mode="crop", grading_config=None):
    model = YoloQualityModel(
        Path("synthetic-geometry-test-only.pt"),
        model_id="synthetic-geometry-test-only",
        device="cpu",
        quality_inference_mode=mode,
        grading_engine=WeightedGradingEngine(
            grading_config or GradingConfig(), body_width_config=BodyWidthConfig(scoring_enabled=False),
        ),
    )
    model.model = object()
    model._infer_parts = lambda _: (list(parts), list(parts))
    return model


def _part(class_id, bbox, confidence=.9):
    return PartDetection.from_source_class(class_id, confidence, bbox)


def _ellipse():
    mask = np.zeros((140, 260), dtype=np.uint8)
    cv2.ellipse(mask, (130, 70), (100, 25), 0, 0, 360, 1, -1)
    crop = np.full((140, 260, 3), 30, dtype=np.uint8)
    crop[mask.astype(bool)] = (130, 170, 200)
    return crop, mask.astype(bool)


def _predict(model, crop, **extras):
    frame_quality = extras.pop("frame_quality", {"usable": True})
    detection_confidence = extras.pop("detection_confidence", .99)
    return model.predict(
        crop, 9, stabilize=False, frame_id="synthetic-pixel-integration",
        detection_confidence=detection_confidence, parent_bbox=(65, 85, 275, 155),
        crop_bounds=CropBounds(40, 50, 300, 190), frame_shape=(320, 400, 3),
        frame_quality=frame_quality, **extras,
    )


def test_new_pixel_measurements_leave_grade_support_and_part_weights_unchanged():
    crop, mask = _ellipse()
    parts = [
        _part(0, (90, 44, 170, 96), .9),
        _part(1, (30, 48, 70, 92), .8),
        _part(2, (190, 48, 230, 92), .7),
    ]
    baseline = _predict(_model(parts), crop)
    measured = _predict(
        _model(parts), crop, fish_mask=mask,
        fish_mask_metadata={"source": "reviewed_instance_mask", "instance_id": 9},
    )
    geometry = measured.analysis["fish_geometry"]
    assert geometry["fish_length_px"] == pytest.approx(201, abs=3)
    assert geometry["max_body_width_px"] == pytest.approx(51, abs=3)
    assert geometry["relative_width_ratio"] == pytest.approx(51 / 201, abs=.02)
    assert geometry["measurement_validated"] is False
    assert geometry["used_for_grading"] is False
    assert measured.quality == baseline.quality == "Class A"
    assert measured.quality_confidence == baseline.quality_confidence
    for key in (
        "final_grade", "final_score", "weighted_scores", "effective_weights",
        "original_weight_coverage", "part_results", "adjustments",
    ):
        assert measured.analysis[key] == baseline.analysis[key]
    assert measured.analysis["weighted_scores"]["Class A"] == pytest.approx(.83)
    assert not measured.analysis["body_width"]["score_contributed"]
    json.dumps(measured.analysis, allow_nan=False)


def test_dedicated_original_frame_mask_does_not_replace_existing_grading_diagnostics():
    crop, _ = _ellipse()
    frame = np.full((320, 400, 3), 30, dtype=np.uint8)
    frame[50:190, 40:300] = crop
    parts = [
        _part(0, (90, 44, 170, 96), .9),
        _part(1, (30, 48, 70, 92), .8),
        _part(2, (190, 48, 230, 92), .7),
    ]
    baseline = _predict(_model(parts), crop)
    measured = _predict(_model(parts), crop, measurement_frame=frame)
    geometry = measured.analysis["fish_geometry"]
    assert geometry["mask_metadata"]["dedicated_measurement_crop"] is True
    assert geometry["fish_length_px"] == pytest.approx(201, abs=4)
    assert geometry["max_body_width_px"] == pytest.approx(51, abs=3)
    assert measured.analysis["supporting_image_measurements"] == baseline.analysis["supporting_image_measurements"]
    assert measured.analysis["weighted_scores"] == baseline.analysis["weighted_scores"]
    assert measured.analysis["final_grade"] == baseline.analysis["final_grade"]


def test_segmentation_failure_retains_the_original_weighted_verdict(monkeypatch):
    crop, _ = _ellipse()
    parts = [_part(0, (90, 44, 170, 96)), _part(1, (30, 48, 70, 92)), _part(2, (190, 48, 230, 92))]
    baseline = _predict(_model(parts), crop)

    def fail_segmentation(*args, **kwargs):
        raise cv2.error("Synthetic segmentation failure")

    monkeypatch.setattr("src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", fail_segmentation)
    result = _predict(_model(parts), crop)
    assert result.quality == baseline.quality
    assert result.quality_confidence == baseline.quality_confidence
    assert result.analysis["weighted_scores"] == baseline.analysis["weighted_scores"]
    geometry = result.analysis["fish_geometry"]
    assert geometry["fish_length_px"] is None
    assert geometry["max_body_width_px"] is None
    assert "measurement_processing_failed" in geometry["reasons"]
    assert geometry["used_for_grading"] is False


def test_explicit_mask_owned_by_another_fish_is_withheld_without_discarding_raw_pixels():
    crop, mask = _ellipse()
    original_mask = mask.copy()
    parts = [_part(0, (90, 44, 170, 96))]
    observation = _predict(
        _model(parts), crop, fish_mask=mask,
        fish_mask_metadata={"source": "reviewed_instance_mask", "instance_id": 10},
    )
    geometry = observation.analysis["fish_geometry"]
    assert geometry["status"] == "unreliable"
    assert "mask_parent_mismatch" in geometry["reasons"]
    assert geometry["fish_length_px"] is None
    assert geometry["max_body_width_px"] is None
    assert geometry["candidate_measurements"]["fish_length_px"] == pytest.approx(201, abs=3)
    assert geometry["used_for_grading"] is False
    np.testing.assert_array_equal(mask, original_mask)


@pytest.mark.parametrize("quality,reason", [
    ({"usable": False}, "source_frame_unusable"),
    ({"usable": True, "parent_usable": False}, "parent_detection_unreliable"),
    ({"usable": True, "parent_uncertain": True}, "parent_detection_unreliable"),
    ({"usable": True, "parent_crop_clipped": True}, "segmentation_reported_clipped"),
])
def test_explicit_frame_and_parent_uncertainty_reaches_pixel_reliability(quality, reason):
    crop, mask = _ellipse()
    observation = _predict(
        _model([_part(0, (90, 44, 170, 96))]), crop,
        frame_quality=quality, fish_mask=mask,
        fish_mask_metadata={"source": "reviewed_instance_mask", "instance_id": 9},
    )
    geometry = observation.analysis["fish_geometry"]
    assert geometry["status"] == "unreliable"
    assert reason in geometry["reasons"]
    assert geometry["fish_length_px"] is None
    assert geometry["max_body_width_px"] is None
    assert geometry["candidate_measurements"]["fish_length_px"] == pytest.approx(201, abs=3)
    assert geometry["used_for_grading"] is False


def test_configured_low_parent_confidence_rejects_public_geometry():
    crop, mask = _ellipse()
    model = _model(
        [_part(0, (90, 44, 170, 96))],
        grading_config=GradingConfig(minimum_detection_confidence=.5),
    )
    observation = _predict(
        model, crop, detection_confidence=.1, fish_mask=mask,
        fish_mask_metadata={"source": "reviewed_instance_mask", "instance_id": 9},
    )
    geometry = observation.analysis["fish_geometry"]
    assert "parent_detection_below_threshold" in geometry["reasons"]
    assert geometry["fish_length_px"] is None
    assert geometry["max_body_width_px"] is None


@pytest.mark.parametrize("matched_context", [False, True])
def test_centimeters_require_reviewed_scale_and_matching_capture_context(matched_context):
    crop, mask = _ellipse()
    model = _model([_part(0, (90, 44, 170, 96))])
    # A synthetic scale fixture verifies arithmetic and context matching only.
    # It is never persisted or offered as a calibration for real fish/images.
    model._physical_calibration = PhysicalCalibration(
        validated=True, calibration_id="synthetic-plane-test-only", pixels_per_cm=10,
        reference_frame_size=(400, 320), source_id="synthetic-plane",
    )
    quality = {"usable": True}
    if matched_context:
        quality["width_context"] = {"source_context": {"source_id": "synthetic-plane"}}
    observation = _predict(
        model, crop, frame_quality=quality, fish_mask=mask,
        fish_mask_metadata={"source": "reviewed_instance_mask", "instance_id": 9},
    )
    geometry = observation.analysis["fish_geometry"]
    assert geometry["fish_length_px"] == pytest.approx(201, abs=3)
    assert geometry["max_body_width_px"] == pytest.approx(51, abs=3)
    if matched_context:
        assert geometry["physical_calibration"]["applied"] is True
        assert geometry["fish_length_cm"] == pytest.approx(20.1, abs=.3)
        assert geometry["max_body_width_cm"] == pytest.approx(5.1, abs=.3)
    else:
        assert geometry["physical_calibration"]["applied"] is False
        assert geometry["physical_calibration"]["reason"] == "physical_calibration_context_mismatch"
        assert geometry["fish_length_cm"] is None
        assert geometry["max_body_width_cm"] is None
    assert geometry["measurement_validated"] is False
    assert geometry["used_for_grading"] is False
    assert not observation.analysis["body_width"]["score_contributed"]


def test_full_frame_parent_assignment_keeps_different_fish_measurements_separate(monkeypatch):
    # This is a controlled instance-mask substitute, not a biological validation
    # of GrabCut. The original-frame path must crop it for the correct parent.
    def synthetic_mask(crop):
        mask = crop[:, :, 0] > 80
        return mask, {
            "status": "validated_for_features", "source": "synthetic_instance_mask",
            "foreground_pixels": int(mask.sum()), "mask_validated_for_measurement": False,
        }

    monkeypatch.setattr(
        "src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", synthetic_mask,
    )
    frame = np.full((280, 500, 3), 30, dtype=np.uint8)
    cv2.ellipse(frame, (120, 90), (80, 25), 0, 0, 360, (130, 170, 200), -1)
    cv2.ellipse(frame, (370, 195), (70, 20), 0, 0, 360, (130, 170, 200), -1)
    parts = [
        _part(0, (85, 63, 155, 117)), _part(1, (40, 70, 70, 110)),
        _part(2, (170, 70, 200, 110)),
        _part(0, (340, 173, 400, 217)), _part(1, (300, 180, 330, 210)),
        _part(2, (410, 180, 440, 210)),
    ]
    parents = [
        ParentAnchor(1, (35, 60, 205, 120), .99),
        ParentAnchor(2, (295, 170, 445, 220), .99),
    ]
    observations = _model(parts, mode="full_frame").predict_full_frame(
        frame, parents, stabilize=False, frame_id="two-separate-silhouettes",
    )
    first = observations[1][0].analysis["fish_geometry"]
    second = observations[2][0].analysis["fish_geometry"]
    assert first["fish_length_px"] == pytest.approx(161, abs=3)
    assert first["max_body_width_px"] == pytest.approx(51, abs=3)
    assert second["fish_length_px"] == pytest.approx(141, abs=3)
    assert second["max_body_width_px"] == pytest.approx(41, abs=3)
    assert first["used_for_grading"] is second["used_for_grading"] is False


def test_full_frame_ambiguous_body_never_supplies_a_trusted_neighbor_width(monkeypatch):
    crop, _ = _ellipse()
    monkeypatch.setattr(
        "src.inference.fish_geometry_pipeline.generate_runtime_fish_mask",
        lambda image: (None, {"status": "unavailable", "reason": "synthetic overlap"}),
    )
    model = _model([_part(0, (90, 44, 170, 96))], mode="full_frame")
    observations = model.predict_full_frame(
        crop,
        [ParentAnchor(1, (20, 30, 240, 110), .99), ParentAnchor(2, (25, 30, 245, 110), .99)],
        stabilize=False,
    )
    for observation, _ in observations.values():
        geometry = observation.analysis["fish_geometry"]
        assert geometry["max_body_width_px"] is None
        assert geometry["relative_width_ratio"] is None
        assert not geometry["used_for_grading"]
        assert observation.analysis["body_width"]["body_bbox"] is None


def test_all_seven_saved_records_keep_grades_without_inventing_silhouettes():
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    records = [json.loads(row["Complete fish event"]) for row in rows]
    original = deepcopy(records)
    results = normalize_inspection_results(
        records, source_metadata=json.loads(rows[0]["Source metadata"]),
    )
    assert records == original
    assert len(results) == 7
    for before, after in zip(original, results):
        geometry = after["analysis"]["fish_geometry"]
        assert geometry["fish_length_px"] is None
        assert geometry["max_body_width_px"] is None
        assert geometry["relative_width_ratio"] is None
        assert geometry["measurement_validated"] is False
        assert geometry["used_for_grading"] is False
        assert after["quality"] == before["quality"]
        for key in ("final_grade", "final_score", "weighted_scores", "effective_weights"):
            assert after["analysis"][key] == before["analysis"][key]
