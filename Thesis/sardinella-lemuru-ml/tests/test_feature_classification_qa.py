"""Feature-to-class boundary regressions; fixtures are software controls only."""
from copy import deepcopy
import itertools
import json
import math

import numpy as np
import pytest

from src.evaluation.calibrate_decision_fusion import fit_calibration, validate_records
from src.features.fusion import extract_fusion_measurements
from src.inference.decision_fusion import (
    FEATURE_KEYS, GRADE_NAMES, fingerprint, fuse_decision, measurement_issues, reference_support,
)
from test_decision_fusion import (
    CONFIG, CONTEXT, SOURCE, artifact, baseline, measurements, run, verified_fixture_records,
)


@pytest.mark.parametrize("family,key,value", [
    (family, key, -1.) for family, keys in FEATURE_KEYS.items() for key in keys
] + [
    ("size", "relative_width_ratio", 0.),
    ("size", "body_width_to_length_ratio", 0.),
    ("cracks", "crack_area_fraction", 1.01),
    *[("color", key, 1.01) for key in FEATURE_KEYS["color"]],
    ("texture", "glcm_contrast", 226.),
    ("texture", "glcm_homogeneity", 1.01),
    ("texture", "glcm_entropy", 8.01),
    ("texture", "lbp_entropy", math.log2(10) + .01),
    ("texture", "lbp_nonuniform_ratio", 1.01),
    ("texture", "mean_gradient_proxy", math.sqrt(2) + .01),
])
def test_impossible_measurements_never_contribute_to_classes(family, key, value):
    measured = measurements({family: "Class A"})
    measured["features"][family]["values"][key] = value
    before = deepcopy(measured)
    decision, report = run(measured)
    assert decision == baseline()
    assert report["mode"] == "model2_only"
    assert report["features"][family]["used_for_grading"] is False
    assert f"measurement_out_of_range:{key}" in report["features"][family]["reasons"]
    assert measured == before
    json.dumps(report, allow_nan=False)


def test_unit_boundaries_are_valid_without_creating_grade_boundaries():
    for family in ("cracks", "color", "texture"):
        entry = measurements()["features"][family]
        entry["values"] = dict.fromkeys(FEATURE_KEYS[family], 0.)
        assert not measurement_issues(family, entry)
    color = measurements()["features"]["color"]
    color["values"] = dict.fromkeys(FEATURE_KEYS["color"], 1.)
    assert not measurement_issues("color", color)
    size = measurements()["features"]["size"]
    size["values"].update(relative_width_ratio=2., body_width_to_length_ratio=3., body_width_profile_cv=0.)
    assert not measurement_issues("size", size)
    texture = measurements()["features"]["texture"]
    texture["values"].update(glcm_contrast=225., glcm_homogeneity=1., glcm_entropy=8.,
                              lbp_entropy=math.log2(10), lbp_nonuniform_ratio=1., mean_gradient_proxy=math.sqrt(2))
    assert not measurement_issues("texture", texture)


@pytest.mark.parametrize("original_grade,target_grade", list(itertools.permutations(GRADE_NAMES, 2)))
def test_size_support_reaches_each_existing_class_with_rejected_safeguard(original_grade, target_grade):
    scores = dict.fromkeys(GRADE_NAMES, 0.)
    scores.update({original_grade: .51, target_grade: .49})
    original = baseline(scores)
    assert original.final_grade == original_grade
    decision, report = fuse_decision(original, measurements({"size": target_grade}), CONFIG, artifact(),
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=CONTEXT)
    assert report["fused_candidate_prediction"] == target_grade
    assert report["features"]["size"]["class_support_delta"][target_grade] > 0
    if original_grade == "Rejected":
        assert decision.final_grade is None
        assert "UG_FUSION_REJECTED_SAFEGUARD" in decision.reason_codes
    else:
        assert decision.final_grade == target_grade
    for grade in GRADE_NAMES:
        assert report["model2_class_probabilities"][grade] + sum(
            feature["class_support_delta"][grade] for feature in report["features"].values()
        ) == pytest.approx(decision.weighted_scores[grade])


@pytest.mark.parametrize("location", ["artifact", "measurements"])
def test_independent_part_reference_is_excluded_at_runtime(location):
    measured, calibrated = measurements(), artifact()
    (calibrated if location == "artifact" else measured)["reference_unit"] = "fish_part"
    decision, report = run(measured, calibrated)
    assert decision == baseline()
    assert report["mode"] == "model2_only"
    assert not any(entry["used_for_grading"] for entry in report["features"].values())


def test_part_measurements_cannot_fit_a_whole_fish_artifact():
    records = verified_fixture_records()
    records[0]["measurements"]["reference_unit"] = "fish_part"
    with pytest.raises(ValueError, match="Measurements must match"):
        validate_records(records)


def test_calibrations_from_the_previous_acceptance_rules_require_refitting():
    calibrated = artifact()
    old_policy = CONFIG.to_dict()
    for key in ("enabled", "artifact_path"):
        old_policy.pop(key)
    calibrated["fusion_policy_id"] = fingerprint(old_policy)
    decision, report = run(calibration=calibrated)
    assert decision == baseline()
    assert report["mode"] == "model2_only"
    assert "decision policy does not match" in report["validation_reasons"][0]


def test_successful_extraction_values_with_an_error_are_withheld():
    measured = measurements({"color": "Class A"})
    measured["features"]["color"]["measurement_error"] = "lighting correction failed"
    decision, report = run(measured)
    assert decision == baseline()
    assert "measurement_extraction_failed" in report["features"]["color"]["reasons"]


def test_validation_requires_automatic_decisions_that_actually_used_features(monkeypatch):
    # Fitting sees separable controls, but the runtime rejects every reference
    # distance. Correct fallback predictions cannot certify feature fusion.
    def outside_reference(values, calibration):
        support, _ = reference_support(values, calibration)
        return support, calibration["distance_limit"] + 1.

    monkeypatch.setattr("src.inference.decision_fusion.reference_support", outside_reference)
    calibrated = fit_calibration(verified_fixture_records())
    comparison = calibrated["validation"]["comparison"]
    assert all(entry["validated"] for entry in calibrated["features"].values())
    assert comparison["candidate"]["automatic_count"] > 0
    assert comparison["eligible_fusion_automatic_count"] == 0
    assert calibrated["validation"]["passed"] is False


def test_validation_preserves_rejected_recall_even_if_overall_f1_improves(monkeypatch):
    from src.evaluation import calibrate_decision_fusion as calibration_module
    original_evaluate = calibration_module.evaluate_calibration

    def declining_rejected_recall(*args, **kwargs):
        report = original_evaluate(*args, **kwargs)
        report["model2_only"]["macro_f1"] = .8
        report["candidate"]["macro_f1"] = .9
        report["candidate"]["per_class_recall"]["Rejected"] = .8
        return report

    monkeypatch.setattr(calibration_module, "evaluate_calibration", declining_rejected_recall)
    calibrated = fit_calibration(verified_fixture_records())
    assert calibrated["validation"]["passed"] is False


def test_feature_usage_counts_and_reference_unit_are_recorded():
    calibrated = fit_calibration(verified_fixture_records())
    comparison = calibrated["validation"]["comparison"]
    assert calibrated["reference_unit"] == "whole_fish"
    assert comparison["eligible_fusion_automatic_count"] == comparison["specimen_count"]
    assert comparison["eligible_fusion_count"] == comparison["specimen_count"]
    assert set(comparison["per_feature_usage_counts"].values()) == {comparison["specimen_count"]}


@pytest.mark.parametrize("count", [None, "invalid", True, float("nan"), float("inf"), -1, .5])
def test_bad_texture_counts_withhold_optional_features_without_interrupting_extraction(count):
    texture = dict.fromkeys(FEATURE_KEYS["texture"], .1)
    texture.update(glcm_valid_pair_count=count, lbp_valid_pixel_count=count)
    result = extract_fusion_measurements(np.full((10, 20, 3), 100, np.uint8), np.ones((10, 20), bool),
        fish_id=7, frame_id="frame-1", source=SOURCE, texture_values=texture,
        validation={"fish_id": 7, "frame_id": "frame-1", **SOURCE, "reviewed": True,
                    "complete_mask": True, "ownership_validated": True, "measurement_validated": True,
                    "validation_provenance": {"reviewer": "fixture", "review_id": "fixture", "reference_set_id": "fixture"},
                    "texture": {"glcm_valid": True, "lbp_valid": True, "surface_valid": True}})
    assert result["reference_unit"] == "whole_fish"
    assert result["features"]["texture"]["checks"]["glcm_valid"] is False
    assert result["features"]["texture"]["checks"]["lbp_valid"] is False
    assert result["features"]["texture"]["measurement_reliability"] == 0.


def test_class_support_changes_export_without_losing_other_grades():
    import csv
    from io import BytesIO, StringIO
    from openpyxl import load_workbook
    from src.api.export import EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
    decision, report = run()
    event = {"track_id": 7, "quality": decision.final_grade, "analysis": {
        "feature_fusion": {"decision_fusion": report}}}
    row = inspection_row(event)
    changes = json.loads(row["fusion_feature_class_deltas"])
    for family, entry in report["features"].items():
        assert changes[family] == entry["class_support_delta"]
        assert set(changes[family]) == set(GRADE_NAMES)
    assert inspection_row({})["fusion_feature_class_deltas"] == ""
    fields = ["fusion_feature_class_deltas"]
    exported = next(csv.DictReader(StringIO(make_csv([event], fields).decode("utf-8-sig"))))
    assert json.loads(exported[EXPORT_FIELDS[fields[0]]]) == changes
    workbook = load_workbook(BytesIO(make_xlsx([event], fields, {})), data_only=True)
    assert json.loads(workbook["Fish Inspections"].cell(2, 1).value) == changes


def test_reviewed_crack_measurement_survives_optional_candidate_detector_failure(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("Candidate detector unavailable")

    monkeypatch.setattr("src.features.fusion.analyze_surface_damage", unavailable)
    result = extract_fusion_measurements(np.full((10, 20, 3), 100, np.uint8), np.ones((10, 20), bool),
        fish_id=7, frame_id="frame-1", source=SOURCE,
        validation={"fish_id": 7, "frame_id": "frame-1", **SOURCE, "reviewed": True,
                    "complete_mask": True, "ownership_validated": True, "measurement_validated": True,
                    "validation_provenance": {"reviewer": "fixture", "review_id": "fixture", "reference_set_id": "fixture"},
                    "cracks": {"structural_discrimination": True, "measurement_source": "reviewed_structural_measurement",
                               "values": dict.fromkeys(FEATURE_KEYS["cracks"], 0.)}})
    assert not measurement_issues("cracks", result["features"]["cracks"])
    assert result["features"]["cracks"]["measurement_error"] is None
