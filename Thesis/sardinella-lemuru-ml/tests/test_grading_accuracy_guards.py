"""Regression controls for uncertain scores and unavailable grading evidence.

Artificial detections verify decision behavior, not real-fish accuracy.
"""
from dataclasses import replace
from itertools import combinations
import json

import numpy as np
import pytest

from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict
from src.inference.decision_fusion import fingerprint, fuse_decision
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.grading_policy import FishGradingInput, GRADE_NAMES, PART_NAMES, GradingPolicy, grade_fish
from src.inference.part_types import PartDetection
from test_decision_fusion import CONFIG, CONTEXT, SOURCE, artifact, measurements


IMAGE = np.full((32, 64, 3), 100, np.uint8)


def evidence(scores, **context):
    return FishGradingInput(part_scores={region: dict(scores) for region in PART_NAMES},
                            presence_confidence=dict.fromkeys(PART_NAMES, .9), **context)


def parts(scores):
    return [PartDetection.from_source_class(GRADE_NAMES.index(grade) * 3 + index, score,
                (index * 20, 5, index * 20 + 18, 25))
            for grade, score in scores.items() for index in range(3)]


@pytest.mark.parametrize("mode", ["standard", "strict", "two_part_v1", "tail_optional_v1"])
@pytest.mark.parametrize("grades", list(combinations(GRADE_NAMES, 2)))
def test_equal_support_never_selects_by_class_order(mode, grades):
    decision = grade_fish(evidence(dict.fromkeys(grades, .8)), GradingPolicy(grading_mode=mode))
    assert decision.final_grade is None
    assert decision.reason_codes == ("UG_LOW_MARGIN",)
    assert decision.grade_margin == pytest.approx(0.)


def test_floating_point_roundoff_does_not_break_a_mathematical_tie():
    decision = grade_fish(FishGradingInput(
        part_scores={"Body": {"Class A": .9}, "Head": {"Class B": .9}, "Tail": {"Class B": .9}},
        presence_confidence=dict.fromkeys(PART_NAMES, .9)),
        GradingPolicy(final_verdict_threshold=.3))
    assert 0 < abs(decision.weighted_scores["Class A"] - decision.weighted_scores["Class B"]) < 1e-12
    assert decision.final_grade is None and "UG_LOW_MARGIN" in decision.reason_codes


@pytest.mark.parametrize("grade", GRADE_NAMES)
def test_positive_margin_and_support_boundary_still_accept_existing_classes(grade):
    scores = {other: .49 for other in GRADE_NAMES}
    scores[grade] = .5
    decision = grade_fish(evidence(scores), GradingPolicy(grading_mode="tail_optional_v1"))
    assert decision.final_grade == grade
    assert decision.final_support == pytest.approx(.5)


@pytest.mark.parametrize("context,reason", [
    ({"model2_available": False}, "UG_MODEL2_UNAVAILABLE"),
    ({"frame_quality_rejected": True}, "UG_FRAME_QUALITY"),
])
def test_reliable_looking_cached_scores_cannot_bypass_hard_holds(context, reason):
    decision = grade_fish(evidence({"Class A": .95}, **context), GradingPolicy())
    assert decision.final_grade is None
    assert reason in decision.reason_codes
    assert decision.weighted_scores["Class A"] == pytest.approx(.95)


@pytest.mark.parametrize("stabilize", [False, True])
def test_runtime_and_offline_replay_keep_equal_scores_ungraded(stabilize):
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False))
    for frame_id in range(2 if stabilize else 1):
        result = engine.evaluate(7, IMAGE, parts({"Class A": .8, "Rejected": .8}),
                                 stabilize=stabilize, frame_id=frame_id)
    assert result.final_grade is None and "UG_LOW_MARGIN" in result.reason_codes
    replay = recompute_final_verdict({"analysis": result.to_dict()}, EvaluationRules(grading_mode="tail_optional_v1"))
    assert replay["final_grade"] == "Ungraded" and "UG_LOW_MARGIN" in replay["reason_codes"]
    json.dumps(result.to_dict(), allow_nan=False)


def test_still_image_stale_scores_cannot_grade_an_unavailable_model():
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False))
    result = engine.evaluate(7, IMAGE, parts({"Class A": .95}), stabilize=False, model2_available=False)
    assert result.final_grade is None and "UG_MODEL2_UNAVAILABLE" in result.reason_codes
    replay = recompute_final_verdict({"analysis": result.to_dict()}, EvaluationRules(grading_mode="tail_optional_v1"))
    assert replay["final_grade"] == "Ungraded" and "UG_MODEL2_UNAVAILABLE" in replay["reason_codes"]


@pytest.mark.parametrize("location", ["record", "analysis", "frame_quality", "latest"])
def test_offline_availability_hold_survives_other_cached_true_flags(location):
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False))
    result = engine.evaluate(7, IMAGE, parts({"Class A": .95}), stabilize=False)
    record = {"model2_available": True, "analysis": result.to_dict()}
    analysis = record["analysis"]
    analysis["model2_available"] = True
    scopes = {"record": record, "analysis": analysis, "frame_quality": analysis["frame_quality"],
              "latest": analysis["frame_quality"]["latest"]}
    scopes[location]["model2_available"] = False
    replay = recompute_final_verdict(record, EvaluationRules(grading_mode="tail_optional_v1"))
    assert replay["final_grade"] == "Ungraded" and "UG_MODEL2_UNAVAILABLE" in replay["reason_codes"]


@pytest.mark.parametrize("region", PART_NAMES)
def test_rejected_override_support_belongs_to_the_final_grade(region):
    policy = GradingPolicy(rejected_override_threshold=.9)
    supplied = evidence({"Class A": .98})
    supplied.part_scores[region]["Rejected"] = .94
    original = grade_fish(supplied, policy)
    assert original.top_grade == "Class A" and original.top_support == pytest.approx(.98)
    assert original.final_grade == "Rejected" and original.override["region"] == region
    assert original.final_support == pytest.approx(policy.weight(region) * .94)
    engine = WeightedGradingEngine(GradingConfig(rejected_override_threshold=.9, image_diagnostics_enabled=False))
    region_index = {"Body": 0, "Head": 1, "Tail": 2}[region]
    detections = parts({"Class A": .98}) + [PartDetection.from_source_class(
        9 + region_index, .94, (region_index * 20, 5, region_index * 20 + 18, 25))]
    result = engine.evaluate(7, IMAGE, detections, stabilize=False)
    assert result.final_score == pytest.approx(original.final_support)
    assert "override" in result.verdict_reason_text.lower()
    assert "Rejected won" not in result.verdict_reason_text
    replay = recompute_final_verdict({"analysis": result.to_dict()},
                                    EvaluationRules(rejected_override_threshold=.9))
    assert replay["final_grade"] == "Rejected"
    assert replay["final_support"] == pytest.approx(original.final_support)
    from src.api.export import inspection_row
    row = inspection_row({"quality": "Rejected", "analysis": result.to_dict()})
    assert row["final_weighted_score"] == pytest.approx(original.final_support * 100)


def test_live_unavailability_discards_stale_scores_and_needs_fresh_recovery_frames():
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False))
    detections = parts({"Class A": .95})
    for frame_id in (1, 2):
        initial = engine.evaluate(7, IMAGE, detections, stabilize=True, frame_id=frame_id)
    assert initial.final_grade == "Class A"
    unavailable = engine.evaluate(7, IMAGE, detections, stabilize=True, frame_id=3, model2_available=False)
    assert unavailable.final_grade is None and "UG_MODEL2_UNAVAILABLE" in unavailable.reason_codes
    pending = engine.evaluate(7, IMAGE, detections, stabilize=True, frame_id=4)
    assert pending.final_grade is None and "UG_TEMPORAL_EVIDENCE" in pending.reason_codes
    recovered = engine.evaluate(7, IMAGE, detections, stabilize=True, frame_id=5)
    assert recovered.final_grade == "Class A"


def test_previous_calibration_policy_cannot_be_reused_after_gate_changes():
    from src.inference.decision_fusion import FEATURE_DOMAINS
    calibrated = artifact()
    previous = CONFIG.to_dict()
    for key in ("enabled", "artifact_path"):
        previous.pop(key)
    previous.update(validation_policy_version="whole_fish_feature_validation_v3", measurement_domains=FEATURE_DOMAINS)
    calibrated["fusion_policy_id"] = fingerprint(previous)
    original = grade_fish(evidence({"Class A": .95}), GradingPolicy(grading_mode="tail_optional_v1"))
    decision, report = fuse_decision(original, measurements(), CONFIG, calibrated,
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=CONTEXT)
    assert decision == original and report["mode"] == "model2_only"


def test_geometry_transfer_cannot_create_a_class_order_tie_decision():
    from src.inference.geometric_support import integrate_geometric_support
    from test_anatomical_width_features import calibrated
    policy = GradingPolicy(final_verdict_threshold=.4)
    supplied = evidence({"Class A": .6, "Class C": .4})
    original = grade_fish(supplied, policy)
    width = {"measurement_available": True, "reliable_for_scoring": True,
             "score_status": "Calibrated", "class_c_supporting_points": 10.}
    decision, _, report = integrate_geometric_support(original, width, calibrated(), policy,
                                                      part_scores=supplied.part_scores)
    assert decision == original
    assert report["contribution_applied"] is False
    assert report["candidate_scores"]["Class A"] == pytest.approx(report["candidate_scores"]["Class C"])


def test_major_structure_restriction_cannot_choose_between_equal_remaining_grades():
    from src.inference.feature_fusion import integrate_structural_support
    from test_structural_feature_fusion import SOURCE as STRUCTURAL_SOURCE, calibrated, evidence as crack_evidence
    policy = GradingPolicy()
    original = grade_fish(evidence({"Class A": .9, "Class B": .6, "Class C": .6}), policy)
    decision, _, eligibility = integrate_structural_support(original, crack_evidence(), calibrated(), policy,
        fish_id=7, frame_id="frame-1", source_context=STRUCTURAL_SOURCE)
    assert eligibility["restricted_grades"] == ["Class A"]
    assert decision.final_grade is None and decision.grade_margin == pytest.approx(0.)


def test_structural_transfer_with_a_tie_preserves_original_evidence():
    from src.inference.feature_fusion import integrate_structural_support
    from test_structural_feature_fusion import SOURCE as STRUCTURAL_SOURCE, calibrated, evidence as crack_evidence
    policy = GradingPolicy(final_verdict_threshold=.4)
    original = grade_fish(evidence({"Class A": .6, "Class B": .4}), policy)
    config = calibrated(maximum_structural_contribution=.1,
                        severity_support={"moderate": {"target": "Class B", "fraction": .1}})
    decision, report, _ = integrate_structural_support(original, crack_evidence("moderate"), config, policy,
        fish_id=7, frame_id="frame-1", source_context=STRUCTURAL_SOURCE)
    assert decision == original and report["score_shift"] == 0.


@pytest.mark.parametrize("context,reason", [
    ({"model2_available": False}, "UG_MODEL2_UNAVAILABLE"),
    ({"frame_quality_rejected": True}, "UG_FRAME_QUALITY"),
])
def test_calibrated_features_cannot_resolve_unavailable_evidence(context, reason):
    calibrated = artifact()
    policy = GradingPolicy()
    calibrated["anatomical_policy"] = policy.to_dict()
    model_context = {**CONTEXT, "anatomical_policy_sha256": fingerprint(policy.to_dict())}
    calibrated["model_context"] = model_context
    original = grade_fish(evidence({"Class A": .95}, **context), policy)
    decision, report = fuse_decision(original, measurements({"size": "Class A"}), CONFIG, calibrated,
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=model_context)
    assert report["mode"] == "calibrated_fusion"
    assert decision.final_grade is None and reason in decision.reason_codes
    assert report["resolved_score_review_reasons"] == []


def test_fused_tie_stays_ungraded_even_with_zero_configured_margin(monkeypatch):
    policy = GradingPolicy(final_verdict_threshold=.4)
    config = replace(CONFIG, minimum_fused_margin=0., minimum_decision_confidence=0.)
    calibrated = artifact()
    calibrated["anatomical_policy"] = policy.to_dict()
    model_context = {**CONTEXT, "anatomical_policy_sha256": fingerprint(policy.to_dict())}
    calibrated.update(model_context=model_context, fusion_policy_id=config.policy_id())
    original = grade_fish(evidence({"Class A": .8, "Class B": .8}), policy)
    monkeypatch.setattr("src.inference.decision_fusion.reference_support",
                        lambda *args: (np.array([.5, .5, 0., 0.]), 0.))
    decision, report = fuse_decision(original, measurements({"size": "Class A"}), config, calibrated,
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=model_context)
    assert report["mode"] == "calibrated_fusion"
    assert decision.final_grade is None and "UG_FUSION_LOW_MARGIN" in decision.reason_codes
    assert report["resolved_score_review_reasons"] == []
