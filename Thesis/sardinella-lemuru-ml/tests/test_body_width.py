"""Geometry, calibration gating, and bounded width support regression checks."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.inference.body_width import (
    BodyWidthConfig, analyze_body_width, boxes_overlap,
    load_body_width_config, supplement_body_scores,
)
from src.inference.part_types import PartDetection


def part(region, bbox, confidence=.9):
    class_id = {"Body": 0, "Head": 1, "Tail": 2}[region]
    return PartDetection.from_source_class(class_id, confidence, bbox)


def calibrated(**changes):
    # Deliberately synthetic thresholds: these are never written to runtime.
    return BodyWidthConfig(calibration_validated=True, calibration_id="synthetic-test-only",
                           validation_sample_count=20, normal_reference_min=.10,
                           normal_reference_max=.20, extreme_reference=.40, **changes)


def test_original_dimensions_proxy_and_uncalibrated_defaults():
    result = analyze_body_width((10, 20, 210, 70), [part("Body", (50, 25, 150, 65))])
    assert result["whole_fish_width_px"] == 200
    assert result["whole_fish_height_px"] == 50
    assert result["body_width_px"] == 100
    assert result["body_height_px"] == 40
    assert result["relative_width_proxy"] == .20
    assert result["reliability"] == "Reliable proxy"
    assert result["score_status"] == "Not calibrated"
    assert result["class_c_supporting_points"] is None
    assert not result["score_contributed"]
    assert not load_body_width_config().scoring_enabled
    assert not load_body_width_config().calibration_validated


def test_vertical_and_head_tail_checked_horizontal():
    vertical = analyze_body_width((10, 20, 60, 220), [part("Body", (15, 60, 55, 160))])
    assert vertical["relative_width_proxy"] == .20
    assert vertical["orientation"] == "vertical"
    # A wider silhouette can qualify with independent near-axis orientation.
    regions = [part("Head", (10, 15, 30, 45)), part("Body", (35, 10, 100, 50)), part("Tail", (110, 20, 125, 40))]
    horizontal = analyze_body_width((5, 5, 130, 55), iter(regions))
    assert horizontal["relative_width_proxy"] == .32
    assert horizontal["orientation"] == "horizontal"
    assert horizontal["measurement_method"].endswith("head_tail_checked")


@pytest.mark.parametrize("options,reason", [
    ({"clipped": True}, "clipped_fish"),
    ({"overlapping": True}, "overlapping_fish"),
    ({"association_reliable": False}, "association_unreliable"),
    ({"association_status": "AMBIGUOUS"}, "association_unreliable"),
    ({"parent_usable": False}, "parent_evidence_unreliable"),
    ({"detection_confidence": .10}, "parent_evidence_low_confidence"),
])
def test_uncertain_measurement_never_guesses(options, reason):
    result = analyze_body_width((10, 20, 210, 70), [part("Body", (50, 25, 150, 65))], **options)
    assert result["relative_width_proxy"] == .2  # Diagnostic ratio survives uncertainty.
    assert result["status"] == "measured"
    assert result["measurement_status"] == "Unreliable"
    assert not result["reliable_for_scoring"]
    assert reason in result["reliability_reasons"]
    assert not result["score_contributed"]


def test_diagonal_unconfirmed_missing_clipped_and_bad_association():
    regions = [part("Head", (15, 15, 30, 30)), part("Body", (35, 35, 65, 65)), part("Tail", (70, 70, 85, 85))]
    diagonal = analyze_body_width((10, 10, 90, 90), regions)
    assert "diagonal_orientation" in diagonal["reliability_reasons"]
    assert diagonal["relative_width_proxy"] == .375
    assert not diagonal["reliable_for_scoring"]
    assert analyze_body_width((0, 10, 200, 60), [part("Body", (30, 15, 130, 55))], frame_shape=(100, 300, 3))["measurement_status"] == "Unreliable"
    assert analyze_body_width((10, 10, 110, 80), [part("Body", (30, 15, 80, 65))])["measurement_status"] == "Unreliable"
    assert analyze_body_width((10, 10, 210, 60), [])["relative_width_proxy"] is None
    assert analyze_body_width((10, 10, 210, 60), [part("Body", (250, 15, 350, 55))])["measurement_status"] == "Unreliable"
    assert analyze_body_width((10, 10, 210, 60), [part("Body", (50, 15, 150, 55), .1)])["measurement_status"] == "Unreliable"


def test_overlap_helper_and_invalid_geometry():
    assert boxes_overlap((0, 0, 100, 20), (90, 10, 120, 30))
    assert not boxes_overlap((0, 0, 100, 20), (100, 0, 120, 30))
    assert not boxes_overlap(None, (100, 0, 120, 30))
    assert analyze_body_width((0, 0, float("nan"), 20), [])["relative_width_proxy"] is None


def test_nearly_coincident_head_tail_do_not_establish_reliable_orientation():
    regions = [part("Head", (85, 30, 105, 50)), part("Body", (80, 25, 120, 55)),
               part("Tail", (95, 30, 115, 50))]
    result = analyze_body_width((10, 10, 210, 70), regions)
    assert result["relative_width_proxy"] == .15
    assert not result["reliable_for_scoring"]
    assert "orientation_evidence_too_close" in result["reliability_reasons"]


def test_spatially_separate_body_candidates_are_unreliable_but_overlapping_hypotheses_are_valid():
    first = part("Body", (40, 25, 100, 65))
    second = part("Body", (110, 25, 170, 65), .8)
    result = analyze_body_width((10, 20, 210, 70), [first, second])
    assert result["relative_width_proxy"] == .2
    assert not result["reliable_for_scoring"]
    assert "ambiguous_body_geometry" in result["reliability_reasons"]
    overlapping = replace(second, bbox=(42, 25, 102, 65))
    assert analyze_body_width((10, 20, 210, 70), [first, overlapping])["relative_width_proxy"] == .20


def test_linear_points_calibration_and_continuity():
    cfg = calibrated()
    def measure(width):
        return analyze_body_width((10, 10, 210, 110), [
            part("Head", (15, 40, 35, 80)), part("Body", (45, 60 - width / 2, 155, 60 + width / 2)),
            part("Tail", (175, 40, 195, 80)),
        ], config=cfg)
    assert measure(40)["class_c_supporting_points"] == 0
    assert measure(60)["class_c_supporting_points"] == pytest.approx(5)
    assert measure(80)["class_c_supporting_points"] == pytest.approx(10)
    assert measure(60.0001)["class_c_supporting_points"] - measure(60)["class_c_supporting_points"] < .001
    assert not measure(60)["score_contributed"]
    # Candidate thresholds are not validated merely because their numbers exist.
    unvalidated = replace(cfg, calibration_validated=False)
    result = analyze_body_width((10, 20, 210, 70), [part("Body", (50, 25, 150, 65))], config=unvalidated)
    assert result["class_c_supporting_points"] is None
    assert result["normal_reference_range"] is None


def test_bounded_body_only_support_preserves_mass_and_rejected_without_double_counting():
    cfg = calibrated(scoring_enabled=True)
    original = {"Body": {"Class A": .30, "Class B": .30, "Class C": .30, "Rejected": .10},
                "Head": {"Class B": .8}, "Tail": {"Class A": .8}}
    analysis = {"status": "measured", "score_status": "Calibrated", "class_c_supporting_points": 10.0}
    scores, result = supplement_body_scores(original, analysis, cfg)
    assert scores["Body"] == pytest.approx({"Class A": .25, "Class B": .25, "Class C": .40, "Rejected": .10})
    assert sum(scores["Body"].values()) == pytest.approx(sum(original["Body"].values()))
    assert scores["Head"] == original["Head"]
    assert scores["Tail"] == original["Tail"]
    assert original["Body"]["Class C"] == .30
    assert result["applied_body_score_shift"] == .10
    assert result["score_contributed"]
    assert supplement_body_scores(scores, result, cfg) == (scores, result)


def test_disabled_missing_and_no_independent_c_keep_scores_identical():
    original = {"Body": {"Class A": .8, "Class B": .7, "Class C": .001, "Rejected": .5}}
    analysis = {"status": "measured", "score_status": "Calibrated", "class_c_supporting_points": 10.0}
    for cfg, measurement in [(BodyWidthConfig(), analysis), (calibrated(), analysis),
                             (calibrated(scoring_enabled=True), analysis),
                             (calibrated(scoring_enabled=True), {"status": "unavailable"})]:
        adjusted, result = supplement_body_scores(original, measurement, cfg)
        assert adjusted == original
        assert not result["score_contributed"]


def test_support_mass_and_confidence_bounds_when_independent_scores_sum_over_one():
    original = {"Body": {"Class A": .8, "Class B": .7, "Class C": .96, "Rejected": .5}}
    adjusted, result = supplement_body_scores(original, {"status": "measured", "score_status": "Calibrated", "class_c_supporting_points": 10}, calibrated(scoring_enabled=True))
    assert result["applied_body_score_shift"] == pytest.approx(.04)
    assert sum(adjusted["Body"].values()) == pytest.approx(sum(original["Body"].values()))
    assert adjusted["Body"]["Class C"] == 1
    assert adjusted["Body"]["Rejected"] == .5


@pytest.mark.parametrize("values", [
    {"calibration_validated": True}, {"scoring_enabled": "false"},
    {"maximum_body_score_shift": .11}, {"minimum_class_c_evidence": 0},
    {"normal_reference_min": .3, "normal_reference_max": .2, "extreme_reference": .4},
    {"geometry_max_axis_deviation_degrees": 45}, {"geometry_min_elongation": 2},
    {"minimum_part_inside_fraction": float("nan")}, {"misspelled_setting": 1},
    {"scoring_method": "unknown"}, {"maximum_geometric_contribution": .11},
])
def test_invalid_configuration_fails_closed(values):
    with pytest.raises(ValueError):
        BodyWidthConfig.from_mapping(values)
