"""Calibrated features resolve score uncertainty, never missing evidence.

References are artificial software controls, not production calibration.
"""
from copy import deepcopy
from dataclasses import replace
import itertools
import json

import numpy as np
import pytest

from src.inference.decision_fusion import FEATURE_DOMAINS, fingerprint, fuse_decision
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.grading_policy import FishGradingInput, GRADE_NAMES, PART_NAMES, grade_fish
from src.inference.part_types import PartDetection
from test_decision_fusion import CONFIG, CONTEXT, POLICY, SOURCE, artifact, measurements, verified_fixture_records


def score_case(scores, *, policy=POLICY, part_scores=None):
    original = grade_fish(FishGradingInput(
        part_scores=part_scores or {region: dict(scores) for region in PART_NAMES},
        presence_confidence=dict.fromkeys(PART_NAMES, .9)), policy)
    calibrated = artifact()
    calibrated["anatomical_policy"] = policy.to_dict()
    context = {**CONTEXT, "anatomical_policy_sha256": fingerprint(policy.to_dict())}
    calibrated["model_context"] = context
    return original, calibrated, context


def fuse(original, calibrated, context, measured=None, **kwargs):
    return fuse_decision(original, measurements() if measured is None else measured, CONFIG, calibrated,
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=context, **kwargs)


@pytest.mark.parametrize("model_winner,target", list(itertools.permutations(GRADE_NAMES, 2)))
def test_size_resolves_close_ties_for_existing_classes(model_winner, target):
    scores = dict.fromkeys(GRADE_NAMES, 0.)
    scores.update({model_winner: .51, target: .49})
    original, calibrated, context = score_case(scores, policy=replace(POLICY, minimum_grade_margin=.15))
    assert original.final_grade is None and original.reason_codes == ("UG_LOW_MARGIN",)
    before = deepcopy((original, calibrated))
    decision, report = fuse(original, calibrated, context, measurements({"size": target}))
    assert decision.final_grade == target
    assert report["model_only_prediction"] == "Ungraded"
    assert report["model_only_verdict"]["reason_codes"] == ["UG_LOW_MARGIN"]
    assert report["resolved_score_review_reasons"] == ["UG_LOW_MARGIN"]
    assert report["baseline_blocking_reasons"] == []
    assert decision.grade_margin >= report["acceptance_thresholds"]["class_margin"]
    assert report["decision_confidence"] >= report["acceptance_thresholds"]["decision_confidence"]
    assert decision.effective_weights == original.effective_weights
    assert (original, calibrated) == before


@pytest.mark.parametrize("target", GRADE_NAMES)
def test_agreeing_features_resolve_low_grade_support(target):
    scores = {grade: .4 if grade == target else .01 for grade in GRADE_NAMES}
    original, calibrated, context = score_case(scores, policy=replace(POLICY, final_verdict_threshold=.7))
    assert original.final_grade is None and original.reason_codes == ("UG_LOW_GRADE_SUPPORT",)
    decision, report = fuse(original, calibrated, context, measurements({"size": target}))
    assert decision.final_grade == target
    assert report["resolved_score_review_reasons"] == ["UG_LOW_GRADE_SUPPORT"]
    assert report["decision_confidence"] >= .7


@pytest.mark.parametrize("reason", [
    "UG_PARENT_UNCERTAIN", "UG_ASSOCIATION_AMBIGUOUS", "UG_MISSING_PART_EVIDENCE",
    "UG_INSUFFICIENT_COVERAGE", "UG_INSUFFICIENT_REGIONS", "UG_TWO_PART_EVIDENCE",
    "UG_TEMPORAL_EVIDENCE", "UG_FRAME_QUALITY", "UG_MODEL2_UNAVAILABLE", "UG_OUT_OF_FRAME",
    "UG_CONFIRMED_MISSING_HEAD", "UG_FUTURE_EVIDENCE_HOLD",
])
def test_score_reconsideration_retains_every_other_hold_including_unknown_future_reasons(reason):
    original, calibrated, context = score_case({"Class A": .4, "Class B": .01, "Class C": .01, "Rejected": .01},
        policy=replace(POLICY, final_verdict_threshold=.7))
    original = replace(original, reason_codes=(*original.reason_codes, reason))
    decision, report = fuse(original, calibrated, context)
    assert decision.final_grade is None
    assert reason in decision.reason_codes and report["baseline_blocking_reasons"] == [reason]
    assert report["resolved_score_review_reasons"] == []


def test_missing_reason_metadata_cannot_be_assumed_to_be_a_score_only_hold():
    original, calibrated, context = score_case({"Class A": .4}, policy=replace(POLICY, final_verdict_threshold=.7))
    original = replace(original, reason_codes=())
    decision, report = fuse(original, calibrated, context)
    assert decision.final_grade is None
    assert "UG_FUSION_BASELINE_EVIDENCE_UNVERIFIED" in report["review_reasons"]


@pytest.mark.parametrize("missing", ["calibration", "measurements", "source"])
def test_score_uncertainty_remains_unchanged_without_eligible_feature_evidence(missing):
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.15))
    measured = measurements({"size": "Class B"})
    if missing == "calibration":
        calibrated = {}
    elif missing == "measurements":
        measured = {}
    else:
        measured["frame_id"] = "stale-frame"
    decision, report = fuse(original, calibrated, context, measured)
    assert decision == original
    assert report["mode"] == "model2_only"
    assert report["resolved_score_review_reasons"] == []


def test_combined_margin_still_needs_to_pass_after_reconsidering_the_raw_tie():
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.4))
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class B"}))
    assert decision.final_grade is None and "UG_FUSION_LOW_MARGIN" in decision.reason_codes
    assert report["resolved_score_review_reasons"] == []


def test_combined_confidence_still_needs_to_pass_after_reconsidering_low_support():
    original, calibrated, context = score_case({"Class A": .4, "Class B": .3, "Class C": .2, "Rejected": .1},
        policy=replace(POLICY, final_verdict_threshold=.99))
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class A"}))
    assert decision.final_grade is None and "UG_FUSION_LOW_DECISION_CONFIDENCE" in decision.reason_codes
    assert report["resolved_score_review_reasons"] == []


def test_reviewed_eligibility_restriction_still_blocks_score_recovery():
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.15))
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class B"}),
        restricted_grades=("Class B",))
    assert decision.final_grade is None
    assert "UG_FUSION_REVIEWED_ELIGIBILITY_RESTRICTION" in decision.reason_codes
    assert report["resolved_score_review_reasons"] == []


def test_single_low_weight_feature_still_cannot_resolve_a_tie_by_itself():
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.15))
    decision, report = fuse(original, calibrated, context, measurements({"color": "Class B"}))
    assert decision.final_grade is None
    assert "UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE" in decision.reason_codes
    assert not report["resolved_score_review_reasons"]


@pytest.mark.parametrize("rejected_support", [.8, .85])
def test_pending_trained_rejected_part_override_survives_score_reconsideration(rejected_support):
    policy = replace(POLICY, final_verdict_threshold=.71, rejected_override_threshold=.8)
    original, calibrated, context = score_case({}, policy=policy, part_scores={
        "Head": {"Rejected": rejected_support}, "Body": {"Class A": 1.}, "Tail": {"Class A": 1.}})
    assert original.final_grade is None and original.override is None
    assert original.reason_codes == ("UG_LOW_GRADE_SUPPORT",)
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class A"}))
    assert report["decision_confidence"] > .71
    assert decision.final_grade is None and "UG_FUSION_REJECTED_SAFEGUARD" in decision.reason_codes
    assert len(report["trained_rejected_evidence"]) == 1
    assert report["trained_rejected_evidence"][0] == {"region": "Head", "confidence": pytest.approx(rejected_support), "configured_threshold": .8}
    assert report["resolved_score_review_reasons"] == []


def test_below_threshold_rejected_part_does_not_invent_an_override():
    policy = replace(POLICY, final_verdict_threshold=.71, rejected_override_threshold=.8)
    original, calibrated, context = score_case({}, policy=policy, part_scores={
        "Head": {"Rejected": .7999}, "Body": {"Class A": 1.}, "Tail": {"Class A": 1.}})
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class A"}))
    assert decision.final_grade == "Class A"
    assert report["trained_rejected_evidence"] == []
    assert report["resolved_score_review_reasons"] == ["UG_LOW_GRADE_SUPPORT"]


def test_confirmed_head_absence_still_blocks_an_otherwise_resolved_score():
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.15))
    head = {"fish_id": 7, "frame_id": "frame-1", **SOURCE, "state": "confirmed_absent", "reviewed": True,
            "ownership_validated": True, "visibility_validated": True, "reviewer": "fixture", "review_id": "fixture"}
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class B"}), head_evidence=head)
    assert decision.final_grade is None and report["decision_state"] == "CRITICAL_ANATOMICAL_DISAGREEMENT"
    assert report["resolved_score_review_reasons"] == []


@pytest.mark.parametrize("stabilize", [False, True])
def test_runtime_uses_features_to_resolve_class_scores_after_temporal_gates(stabilize):
    config = GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False, minimum_grade_margin=.15)
    calibrated = artifact()
    calibrated["anatomical_policy"] = config.to_policy().to_dict()
    calibrated["model_context"] = {**CONTEXT, "anatomical_policy_sha256": fingerprint(calibrated["anatomical_policy"])}
    engine = WeightedGradingEngine(config, fusion_config=CONFIG, fusion_calibration=calibrated)
    parts = [PartDetection.from_source_class(i, score, (5 + i % 3 * 20, 5, 25 + i % 3 * 20, 25))
             for i, score in [(0, .51), (1, .51), (2, .51), (3, .49), (4, .49), (5, .49)]]
    frame = np.zeros((30, 70, 3), np.uint8)
    for index in range(config.minimum_track_observations if stabilize else 1):
        measured = measurements({"size": "Class B"})
        measured["frame_id"] = f"frame-{index}"
        result = engine.evaluate(7, frame, parts, stabilize=stabilize, frame_id=f"frame-{index}",
            source_context=SOURCE, fusion_measurements=measured,
            frame_quality={"fusion_checkpoint_sha256": CONTEXT["checkpoint_sha256"]})
        if stabilize and index < config.minimum_track_observations - 1:
            assert result.final_grade is None
            assert "UG_TEMPORAL_EVIDENCE" in result.reason_codes
    assert result.final_grade == "Class B"
    assert result.part_results["Body"]["grade"] == "Class A"
    assert result.feature_fusion["decision_fusion"]["resolved_score_review_reasons"] == ["UG_LOW_MARGIN"]
    json.dumps(result.to_dict(), allow_nan=False)


def test_validation_and_untouched_test_report_resolved_score_holds():
    from src.evaluation.calibrate_decision_fusion import evaluate_calibration, fit_calibration
    records = verified_fixture_records()
    policy = replace(POLICY, minimum_grade_margin=.9)
    for row in records:
        original, _, context = score_case(row["ai_baseline"]["weighted_scores"], policy=policy)
        row.update(ai_baseline=original.to_dict(), anatomical_policy=policy.to_dict(), model_context=context,
                   original_ai_prediction="Ungraded")
        assert original.final_grade is None and original.reason_codes == ("UG_LOW_MARGIN",)
    calibrated = fit_calibration(records)
    assert calibrated["validation"]["passed"] is True
    validation = calibrated["validation"]["comparison"]
    assert validation["resolved_score_review_count"] == validation["specimen_count"]
    assert validation["resolved_score_review_correct_count"] == validation["specimen_count"]
    test = evaluate_calibration(records, calibrated)
    assert test["resolved_score_review_count"] == test["specimen_count"]
    assert test["resolved_score_review_correct_count"] == test["specimen_count"]


def test_calibration_under_the_previous_score_hold_policy_requires_new_validation():
    original, calibrated, context = score_case({"Class A": .9})
    old_policy = CONFIG.to_dict()
    for key in ("enabled", "artifact_path"):
        old_policy.pop(key)
    old_policy.update(validation_policy_version="whole_fish_feature_validation_v2", measurement_domains=FEATURE_DOMAINS)
    calibrated["fusion_policy_id"] = fingerprint(old_policy)
    decision, report = fuse(original, calibrated, context)
    assert decision == original and report["mode"] == "model2_only"


def test_export_preserves_original_ungraded_result_and_identifies_resolved_score_hold():
    from src.api.export import inspection_row
    original, calibrated, context = score_case({"Class A": .51, "Class B": .49},
        policy=replace(POLICY, minimum_grade_margin=.15))
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class B"}))
    row = inspection_row({"quality": decision.final_grade, "analysis": {"feature_fusion": {"decision_fusion": report}}})
    assert row["model2_only_prediction"] == "Ungraded"
    assert row["final_fused_prediction"] == "Class B"
    assert json.loads(row["fusion_resolved_score_reasons"]) == ["UG_LOW_MARGIN"]
    assert inspection_row({})["fusion_resolved_score_reasons"] == ""
