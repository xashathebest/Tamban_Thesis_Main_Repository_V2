"""Synthetic reviewed records exercise policy plumbing, not crack accuracy."""
from copy import deepcopy
from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

from src.features.damage import analyze_surface_damage
from src.inference.feature_fusion import (
    StructuralFusionConfig, assess_structural_evidence, load_structural_fusion_config,
)
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection


SOURCE = {"source_id": "synthetic-software-fixture", "frame_pixels_sha256": "a" * 64}
PROVENANCE = {"review_id": "fixture-review", "reviewer": "synthetic-test-only",
              "reference_set_id": "fixture-reference-not-scientific-validation"}


def calibrated(**extra):
    return StructuralFusionConfig(enabled=True, calibration_validated=True,
        policy_id="fixture-policy", reference_set_id=PROVENANCE["reference_set_id"], validation_sample_count=1,
        policy_review_provenance=PROVENANCE, **extra)


def evidence(severity="major", **extra):
    return {"parent_track_id": 7, "frame_id": "frame-1", **SOURCE, "reviewed": True,
            "status": "confirmed", "severity": severity, "severity_reviewed": True, "region": "Body",
            "ownership_validated": True, "body_mask_validated": True, "measurement_validated": True,
            "validation_provenance": dict(PROVENANCE), "coordinate_space": "original_frame",
            "locations": [{"x": 35, "y": 20, "width": 45, "height": 4}],
            "clipped": False, "overlapping": False, "ownership_ambiguous": False, "partial_silhouette": False,
            **extra}


def parts(other_grade=None, confidence=.6, *, missing=None):
    detected = [PartDetection.from_source_class(index, .9, (5 + 25*index, 10, 25 + 25*index, 40))
                for index in range(3) if ("Body", "Head", "Tail")[index] != missing]
    if other_grade is not None:
        offset = {"Class B": 3, "Class C": 6, "Rejected": 9}[other_grade]
        detected += [PartDetection.from_source_class(offset + index, confidence, (5+25*index, 10, 25+25*index, 40))
                     for index in range(3) if ("Body", "Head", "Tail")[index] != missing]
    return detected


def grade(record=None, *, config=None, detections=None, frame="frame-1", source=SOURCE):
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False),
                                  structural_config=config or calibrated())
    return engine.evaluate(7, np.full((60, 100, 3), 100, np.uint8), detections if detections is not None else parts(),
                           stabilize=False, frame_id=frame, structural_evidence=record, source_context=source).to_dict()


def test_production_config_has_no_fabricated_severity_or_grade_effect():
    config = load_structural_fusion_config()
    assert config.enabled is config.calibration_validated is False
    assert config.minor_upper_ratio is config.moderate_upper_ratio is None
    assert config.severity_support == {} and config.maximum_structural_contribution == 0
    baseline = grade(config=config); actual = grade(evidence(), config=config)
    for field in ("final_grade", "final_score", "weighted_scores", "effective_weights", "part_results"):
        assert actual[field] == baseline[field]
    assert actual["final_grade"] == "Class A"
    assert actual["feature_fusion"]["structural"]["calibration_status"] == "Not calibrated"
    assert actual["feature_fusion"]["contributions_applied"] == []


def test_confirmed_major_excludes_a_and_uses_existing_supported_b_without_changing_weights():
    baseline = grade(detections=parts("Class B"))
    actual = grade(evidence(), detections=parts("Class B"))
    assert baseline["final_grade"] == "Class A" and actual["final_grade"] == "Class B"
    assert actual["final_score"] == pytest.approx(.6)
    assert actual["weighted_scores"] == baseline["weighted_scores"]
    assert actual["effective_weights"] == {"Head": .3, "Body": .5, "Tail": .2}
    fusion = actual["feature_fusion"]
    assert fusion["primary_anatomical"]["grade"] == "Class A"
    assert fusion["primary_anatomical"]["support"] == pytest.approx(.9)
    assert fusion["eligibility"]["restricted_grades"] == ["Class A"]
    assert fusion["structural"]["used_for_grading"] is True
    assert fusion["structural"]["score_shift"] == 0
    json.dumps(actual, allow_nan=False)


@pytest.mark.parametrize("alternative,confidence,expected", [(None,0.,"Ungraded"), ("Class B",.4,"Ungraded"),
    ("Class C",.4,"Ungraded"), ("Class C",.65,"Class C"), ("Rejected",.65,"Rejected")])
def test_major_never_invents_a_default_replacement_class(alternative, confidence, expected):
    actual = grade(evidence(), detections=parts(alternative, confidence))
    assert actual["final_grade"] == expected
    assert actual["feature_fusion"]["eligibility"]["class_a_eligible"] is False
    assert actual["feature_fusion"]["structural"]["score_shift"] == 0.


@pytest.mark.parametrize("changes", [
    {"parent_track_id": 8}, {"frame_id": "other-frame"}, {"source_id": "other-camera"},
    {"frame_pixels_sha256": "b"*64}, {"status": "suspected"}, {"reviewed": False},
    {"ownership_validated": False}, {"body_mask_validated": False}, {"measurement_validated": False},
    {"severity_reviewed": False}, {"locations": []}, {"region": "Whole Fish"},
    {"coordinate_space": "crop_local_pixels"}, {"clipped": True}, {"overlapping": True},
    {"ownership_ambiguous": True}, {"partial_silhouette": True},
    {"validation_provenance": {}}, {"validation_provenance": {**PROVENANCE,"reference_set_id":"different-set"}},
])
def test_uncertain_candidates_or_stale_review_never_restrict_class_a(changes):
    actual = grade(evidence(**changes))
    assert actual["final_grade"] == "Class A"
    assert actual["feature_fusion"]["eligibility"]["rule_applied"] is False
    assert actual["feature_fusion"]["structural"]["severity_validated"] is False


@pytest.mark.parametrize("severity", ["minor", "moderate"])
def test_reviewed_minor_or_moderate_has_no_automatic_a_restriction(severity):
    actual = grade(evidence(severity))
    assert actual["final_grade"] == "Class A"
    assert actual["feature_fusion"]["structural"]["severity"] == severity
    assert actual["feature_fusion"]["eligibility"]["class_a_eligible"] is True


@pytest.mark.parametrize("missing", ["Head", "Body"])
def test_major_cannot_fill_missing_required_anatomical_evidence(missing):
    actual = grade(evidence(), detections=parts("Class B", missing=missing))
    assert actual["final_grade"] == "Ungraded"
    assert actual["feature_fusion"]["structural"]["contribution_reason"] == "baseline_ungraded_evidence_gates"


def test_optional_tail_redistribution_survives_eligibility_filter():
    actual = grade(evidence(), detections=parts("Class B", missing="Tail"))
    assert actual["final_grade"] == "Class B"
    assert actual["effective_weights"] == pytest.approx({"Head": .375, "Body": .625, "Tail": 0.})


@pytest.mark.parametrize("ratio,expected", [(.05,"minor"),(.2,"moderate"),(.5,"major")])
def test_reviewed_ratio_ranges_are_optional_and_explicit_fixture_policy(ratio, expected):
    # These values are software fixtures, not measured fish severity ranges.
    config = calibrated(minor_upper_ratio=.1, moderate_upper_ratio=.3)
    result = assess_structural_evidence(evidence(severity="",severity_reviewed=False,
        measurements={"skeleton_length_to_body_length":ratio}), config, fish_id=7, frame_id="frame-1", source_context=SOURCE)
    assert result["severity"] == expected and result["severity_validated"]


def test_calibrated_minor_support_is_bounded_and_does_not_exclude_class_a():
    config = calibrated(maximum_structural_contribution=.1,
                        severity_support={"minor":{"target":"Class B","fraction":.03}})
    actual = grade(evidence("minor"), config=config, detections=parts("Class B"))
    assert actual["final_grade"] == "Class A"
    assert actual["feature_fusion"]["eligibility"]["class_a_eligible"] is True
    assert actual["feature_fusion"]["structural"]["score_shift"] == pytest.approx(.03)


@pytest.mark.parametrize("changes", [{"calibration_validated":True}, {"minor_upper_ratio":.1},
    {"minor_upper_ratio":.5,"moderate_upper_ratio":.1}, {"maximum_structural_contribution":True},
    {"maximum_structural_contribution":.1,"severity_support":{"major":{"target":"Rejected","fraction":.1}}}])
def test_incomplete_or_unsafe_policy_configuration_is_rejected(changes):
    with pytest.raises(ValueError): StructuralFusionConfig(**changes)


def test_structural_policy_and_review_record_are_not_mutated():
    record = evidence(); before = deepcopy(record)
    grade(record)
    assert record == before


def test_dark_line_skeleton_width_and_locations_stay_candidates_not_severity():
    image = np.full((120,180,3),150,np.uint8); mask=np.zeros((120,180),bool); mask[10:-10,10:-10]=True
    cv2.line(image,(30,35),(145,85),(20,20,20),3)
    result=analyze_surface_damage(image,mask)
    assert result["status"] == "suspected" and result["severity"] == "unassessed"
    assert result["used_for_grading"] is False
    location=result["locations"][0]
    assert location["skeleton_length_px"] > 0 and location["maximum_width_px"] >= 1
    assert location["skeleton_length_to_body_length"] is None
    assert location["skeleton_points"]
    assert all(mask[y,x] for x,y in location["skeleton_points"])
