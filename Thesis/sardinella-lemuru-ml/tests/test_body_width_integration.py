"""Original-coordinate reuse and optional temporal Body supplement integration."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.api.image_analysis import StillImageAnalyzer
from src.inference.association import ParentAnchor
from src.inference.body_width import BodyWidthConfig, analyze_body_width
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.yolo_fish_detector import FishDetection
from src.inference.yolo_quality_model import YoloQualityModel


def part(class_id, box, confidence=.9):
    return PartDetection.from_source_class(class_id, confidence, box)


def model(parts, *, mode="crop", padding=0, config=None):
    quality = YoloQualityModel(
        Path("width-test-only.pt"), device="cpu", model_id="width-test-only",
        quality_inference_mode=mode, roi_padding=padding,
        grading_engine=WeightedGradingEngine(GradingConfig(), body_width_config=config),
    )
    quality.model = object()
    quality._infer_parts = lambda _: (list(parts), list(parts))
    return quality


def detector(boxes):
    return SimpleNamespace(model=object(), detect=lambda _: [FishDetection(box, .95) for box in boxes])


def test_still_crop_reuses_original_fractional_dimensions_with_padding():
    quality = model([part(0, (50, 15, 150, 55))], padding=10)
    frame = np.full((160, 360, 3), 100, dtype=np.uint8)
    result = StillImageAnalyzer(detector([(50.25, 40.5, 250.75, 90.5)]), quality, roi_padding=10).analyze(frame)
    analysis = result["fish"][0]["analysis"]
    width = analysis["body_width"]
    assert width["whole_fish_width_px"] == 200.5
    assert width["whole_fish_height_px"] == 50
    assert width["body_bbox"] == [90, 45, 190, 85]
    assert width["relative_width_proxy"] == pytest.approx(40 / 200.5)
    assert width["score_status"] == "Not calibrated"
    assert not width["score_contributed"]
    assert analysis["grading_config"]["body_width"]["scoring_enabled"] is False


def test_still_without_model2_retains_whole_fish_dimensions_and_missing_body_status():
    result = StillImageAnalyzer(detector([(20, 20, 220, 70)]), None).analyze(np.zeros((120, 300, 3), dtype=np.uint8))
    fish = result["fish"][0]
    assert fish["quality"] == "Ungraded"
    assert fish["analysis"]["body_width"]["whole_fish_width_px"] == 200
    assert fish["analysis"]["body_width"]["measurement_status"] == "Missing Detection"
    assert fish["analysis"]["body_width"]["body_width_px"] is None
    assert fish["analysis"]["body_width"]["relative_width_proxy"] is None
    assert fish["timestamp"] == result["analyzed_at"]


def test_still_crop_flags_overlapping_neighbors_without_altering_grade():
    quality = model([part(0, (40, 5, 140, 45))])
    result = StillImageAnalyzer(detector([(20, 20, 220, 70), (200, 20, 400, 70)]), quality).analyze(np.zeros((120, 450, 3), dtype=np.uint8))
    for fish in result["fish"]:
        assert "overlapping_fish" in fish["analysis"]["body_width"]["reliability_reasons"]
        assert fish["analysis"]["body_width"]["relative_width_proxy"] == .2
        assert fish["analysis"]["body_width"]["measurement_status"] == "Unreliable"
        assert not fish["analysis"]["body_width"]["reliable_for_scoring"]
        assert fish["quality"] == "Ungraded"  # Body-only .9*.5 remains below .5
        assert fish["analysis"]["weighted_scores"]["Class A"] == .45


@pytest.mark.parametrize("whole,parts,expected,reason", [
    ((20, 20, 220, 70), [part(0, (60, 25, 160, 65))], .2, None),
    ((20, 20, 70, 220), [part(0, (25, 60, 65, 160))], .2, None),
    ((20, 20, 120, 120), [part(1, (25, 25, 40, 40)), part(0, (45, 45, 90, 90)), part(2, (100, 100, 115, 115))], .45, "diagonal_orientation"),
    ((0, 20, 200, 70), [part(0, (40, 25, 140, 65))], .2, "clipped_fish"),
])
def test_full_frame_width_uses_assigned_original_boxes(whole, parts, expected, reason):
    quality = model(parts, mode="full_frame", padding=7)
    observation, _ = quality.predict_full_frame(np.zeros((300, 300, 3), dtype=np.uint8), [ParentAnchor(9, whole, .95)], stabilize=False)[9]
    width = observation.analysis["body_width"]
    assert width["relative_width_proxy"] == expected
    if reason:
        assert reason in width["reliability_reasons"]
    else:
        assert width["body_bbox"] == list(parts[0].bbox)
        assert width["coordinate_space"] == "original_frame"


def test_full_frame_uncertain_ownership_never_uses_neighbors_body():
    quality = model([part(0, (90, 30, 140, 60))], mode="full_frame")
    parents = [ParentAnchor(1, (20, 20, 220, 70), .95), ParentAnchor(2, (25, 20, 225, 70), .95)]
    results = quality.predict_full_frame(np.zeros((150, 300, 3), dtype=np.uint8), parents, stabilize=False)
    for observation, _ in results.values():
        width = observation.analysis["body_width"]
        assert width["relative_width_proxy"] is None
        assert "association_unreliable" in width["reliability_reasons"]
        assert "UG_ASSOCIATION_AMBIGUOUS" in observation.analysis["reason_codes"]


def test_temporal_width_shift_applies_once_and_missing_latest_width_restores_raw_scores():
    cfg = BodyWidthConfig(scoring_enabled=True, calibration_validated=True, scoring_method="body_component_v1",
                          calibration_id="synthetic-only", validation_sample_count=20,
                          normal_reference_min=.1, normal_reference_max=.2, extreme_reference=.4)
    geometry = [part(1, (25, 40, 45, 80)), part(0, (60, 20, 160, 100)), part(2, (180, 40, 210, 80))]
    width = analyze_body_width((20, 10, 220, 110), geometry, config=cfg)
    evidence = [part(0, (40, 5, 140, 45), .8), part(6, (40, 5, 140, 45), .4),
                part(1, (5, 10, 30, 40), .9), part(2, (170, 10, 195, 40), .9)]
    engine = WeightedGradingEngine(GradingConfig(), body_width_config=cfg)
    crop = np.zeros((50, 200, 3), dtype=np.uint8)
    for frame_id in (1, 2, 3):
        verdict = engine.evaluate(9, crop, evidence, stabilize=True, frame_id=frame_id, body_width=width)
        assert verdict.weighted_scores["Class C"] == pytest.approx(.25)
        assert verdict.body_width["applied_body_score_shift"] == pytest.approx(.1)
        assert verdict.part_results["Body"]["grade_evidence"]["Class C"] == pytest.approx(.4)
        assert verdict.part_results["Body"]["adjusted_grade_evidence"]["Class C"] == pytest.approx(.5)
        if frame_id == 1:
            assert verdict.body_width["score_applied"] is True
            assert verdict.body_width["score_contributed"] is False
            assert verdict.body_width["contribution_reason"] == "applied_to_provisional_support_only"
    assert verdict.body_width["score_contributed"] is True
    repeated = engine.evaluate(9, crop, evidence, stabilize=True, frame_id=3, body_width={"status": "unavailable"})
    assert repeated.weighted_scores == verdict.weighted_scores
    missing = engine.evaluate(9, crop, evidence, stabilize=True, frame_id=4)
    assert missing.weighted_scores["Class C"] == pytest.approx(.2)
    assert missing.body_width["relative_width_proxy"] is None
    assert not missing.body_width["score_contributed"]


def test_enabled_but_uncalibrated_or_absent_evidence_preserves_original_verdict():
    crop = np.zeros((50, 200, 3), dtype=np.uint8)
    evidence = [part(0, (40, 5, 140, 45)), part(1, (5, 10, 30, 40)), part(2, (170, 10, 195, 40))]
    baseline = WeightedGradingEngine().evaluate(9, crop, evidence, stabilize=False)
    enabled = WeightedGradingEngine(body_width_config=BodyWidthConfig(scoring_enabled=True)).evaluate(9, crop, evidence, stabilize=False)
    assert enabled.weighted_scores == baseline.weighted_scores
    assert enabled.final_grade == baseline.final_grade
    assert enabled.part_results == baseline.part_results
    assert enabled.body_width["score_status"] == "Not calibrated"
