"""Tied evidence must not turn class order into a grading decision.

All references here are synthetic software controls, not fish calibration.
"""
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
import json

import numpy as np
import pytest

from src.evaluation.calibrate_decision_fusion import _probability_metrics
from src.inference.decision_fusion import FAMILIES, FEATURE_DOMAINS, GRADE_NAMES, fingerprint
from test_decision_fusion import CONFIG, artifact, baseline, measurements, run
from test_fusion_score_recovery import fuse, score_case


TIED_PAIRS = list(combinations(GRADE_NAMES, 2))
TIED_TARGETS = [(pair, target) for pair in TIED_PAIRS for target in pair]


@pytest.mark.parametrize("pair,target", TIED_TARGETS)
def test_agreeing_features_resolve_model_ties_equally_for_each_class(pair, target):
    original, calibrated, context = score_case(dict.fromkeys(pair, .5))
    assert original.final_grade is None and original.reason_codes == ("UG_LOW_MARGIN",)
    before = deepcopy((original, calibrated))
    decision, report = fuse(original, calibrated, context, measurements(dict.fromkeys(FAMILIES, target)))
    assert decision.final_grade == target
    assert report["decision_state"] == "AGREEMENT"
    assert report["model2_leading_grades"] == list(pair)
    assert report["feature_only_leading_grades"] == [target]
    assert report["resolved_score_review_reasons"] == ["UG_LOW_MARGIN"]
    assert report["decision_confidence"] == pytest.approx(.609375)
    assert not report["disagreement_reasons"]
    assert (original, calibrated) == before
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("family", ["cracks", "color", "texture"])
@pytest.mark.parametrize("pair,target", TIED_TARGETS)
def test_a_lone_low_weight_family_cannot_decide_a_model_tie(family, pair, target):
    original, calibrated, context = score_case(dict.fromkeys(pair, .5))
    decision, report = fuse(original, calibrated, context, measurements({family: target}))
    assert decision.final_grade is None
    assert "UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE" in decision.reason_codes
    assert not report["resolved_score_review_reasons"]


@pytest.mark.parametrize("pair,target", TIED_TARGETS)
def test_two_agreeing_low_weight_families_can_resolve_a_model_tie(pair, target):
    original, calibrated, context = score_case(dict.fromkeys(pair, .5))
    decision, report = fuse(original, calibrated, context, measurements({"color": target, "texture": target}))
    assert decision.final_grade == target
    assert report["decision_state"] == "AGREEMENT"


def tied_references(calibrated, family, grades):
    reference = deepcopy(calibrated["features"][family]["distributions"][grades[0]])
    for grade in grades:
        calibrated["features"][family]["distributions"][grade] = deepcopy(reference)


@pytest.mark.parametrize("target", ["Class A", "Class B"])
def test_ambiguous_features_report_the_tie_without_inventing_a_conflict(target):
    calibrated = artifact()
    tied_references(calibrated, "size", ("Class A", "Class B"))
    original, _, context = score_case({target: .9})
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class A"}))
    assert decision.final_grade == target
    assert report["decision_state"] == "AGREEMENT"
    assert report["feature_only_prediction"] is None
    assert report["feature_only_leading_grades"] == ["Class A", "Class B"]
    assert report["features"]["size"]["assessment"] == "Ambiguous"
    assert report["features"]["size"]["leading_grades"] == ["Class A", "Class B"]
    assert not report["disagreement_reasons"]


def test_flat_support_from_other_families_cannot_hide_one_low_weight_tiebreaker():
    original, calibrated, context = score_case({"Class A": .5, "Class B": .5})
    tied_references(calibrated, "size", ("Class A", "Class B"))
    decision, report = fuse(original, calibrated, context, measurements({"size": "Class A", "color": "Class B"}))
    assert decision.final_grade is None
    assert "UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE" in decision.reason_codes
    assert not report["resolved_score_review_reasons"]


@pytest.mark.parametrize("triple,target", [(triple, target) for triple in combinations(GRADE_NAMES, 3) for target in triple])
def test_partly_neutral_families_do_not_bypass_the_safeguard_in_three_way_ties(triple, target):
    from src.inference.decision_fusion import fuse_decision
    from test_decision_fusion import POLICY, SOURCE

    config = replace(CONFIG, minimum_decision_confidence=.2, minimum_fused_margin=0.)
    original, calibrated, context = score_case(dict.fromkeys(triple, .4),
        policy=replace(POLICY, final_verdict_threshold=.2))
    calibrated["fusion_policy_id"] = config.policy_id()
    rivals = [grade for grade in triple if grade != target]
    tied_references(calibrated, "size", (target, rivals[0]))
    tied_references(calibrated, "color", (target, rivals[1]))
    decision, report = fuse_decision(original, measurements({"size": target, "color": target}), config, calibrated,
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=context)
    assert report["fused_candidate_prediction"] == target
    assert report["decision_confidence"] > .2
    assert decision.final_grade is None
    assert "UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE" in decision.reason_codes
    assert report["tie_resolving_features"] == ["size", "color"]


def test_ambiguous_feature_uses_the_least_reliable_tied_class():
    calibrated = artifact()
    tied_references(calibrated, "size", ("Class A", "Class B"))
    calibrated["features"]["size"]["per_class_reliability"]["Class B"] = .3
    decision, report = run(measurements({"size": "Class A"}), calibrated)
    assert decision == baseline()
    assert report["mode"] == "model2_only"
    assert report["features"]["size"]["reliability"] == pytest.approx(.3)
    assert "reliability_below_acceptance_threshold" in report["features"]["size"]["reasons"]


def test_ambiguous_features_that_exclude_the_model_still_trigger_real_conflicts():
    calibrated = artifact()
    for family in ("size", "color"):
        tied_references(calibrated, family, ("Class B", "Class C"))
    decision, report = run(measurements({"size": "Class B", "color": "Class B"}), calibrated)
    assert decision.final_grade is None
    assert report["decision_state"] == "MAJOR_DISAGREEMENT"
    assert "UG_FUSION_MAJOR_DISAGREEMENT" in decision.reason_codes
    assert len(report["disagreement_reasons"]) == 2


def test_roundoff_in_a_model_tie_does_not_create_a_false_conflict():
    original, calibrated, context = score_case({"Class A": np.nextafter(.5, 1.), "Class B": .5})
    decision, report = fuse(original, calibrated, context, measurements(dict.fromkeys(FAMILIES, "Class B")))
    assert decision.final_grade == "Class B"
    assert report["model2_leading_grades"] == ["Class A", "Class B"]
    assert report["decision_state"] == "AGREEMENT"


@pytest.mark.parametrize("pair", TIED_PAIRS)
def test_calibration_metrics_do_not_count_ambiguous_predictions_as_correct(pair):
    probability = [0.5 if grade in pair else 0. for grade in GRADE_NAMES]
    metrics = _probability_metrics(list(pair), [probability, probability])
    assert metrics["balanced_accuracy"] == 0.
    assert metrics["ambiguous_prediction_count"] == 2
    assert all(metrics["per_class_recall"][grade] == 0. for grade in pair)
    assert metrics["brier_score"] == pytest.approx(.5)
    assert metrics["negative_log_likelihood"] == pytest.approx(np.log(2))


def test_previous_tie_comparison_calibrations_require_fresh_validation():
    calibrated = artifact()
    previous = CONFIG.to_dict()
    for key in ("enabled", "artifact_path"):
        previous.pop(key)
    previous.update(validation_policy_version="whole_fish_feature_validation_v4", measurement_domains=FEATURE_DOMAINS)
    calibrated["fusion_policy_id"] = fingerprint(previous)
    decision, report = run(calibration=calibrated)
    assert decision == baseline()
    assert report["mode"] == "model2_only"


@pytest.mark.parametrize("pair", TIED_PAIRS)
def test_combined_ties_retain_all_leaders_without_a_candidate_prediction(pair):
    original, calibrated, context = score_case(dict.fromkeys(pair, .5))
    tied_references(calibrated, "size", pair)
    decision, report = fuse(original, calibrated, context, measurements({"size": pair[0]}))
    assert decision.final_grade is None
    assert "UG_FUSION_LOW_MARGIN" in decision.reason_codes
    assert report["combined_leading_grades"] == list(pair)
    assert report["fused_candidate_prediction"] is None
    assert report["contribution_target_grade"] is None
    assert report["tie_resolving_features"] == []
    assert report["features"]["size"]["used_for_grading"] is True


def test_ties_and_contributions_survive_csv_and_xlsx_round_trips():
    import csv
    from io import BytesIO, StringIO
    from openpyxl import load_workbook
    from src.api.export import EXPORT_FIELDS, inspection_row, make_csv, make_xlsx

    pair = ("Class A", "Class B")
    original, calibrated, context = score_case(dict.fromkeys(pair, .5))
    tied_references(calibrated, "size", pair)
    decision, report = fuse(original, calibrated, context, measurements({"size": pair[0]}))
    event = {"quality": "Ungraded", "analysis": {"feature_fusion": {"decision_fusion": report}}}
    columns = ["fusion_model2_leading_grades", "fusion_feature_leading_grades", "fusion_combined_leading_grades"]
    fields = [*columns, "fusion_tie_resolving_features", "feature_only_prediction", "fusion_source_contributions"]
    row = inspection_row(event)
    assert all(json.loads(row[column]) == list(pair) for column in columns)
    assert row["feature_only_prediction"] == "Tied: Class A / Class B"
    assert json.loads(row["fusion_tie_resolving_features"]) == []
    assert all(inspection_row({})[column] == "" for column in columns)
    exported = next(csv.DictReader(StringIO(make_csv([event], fields).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([event], fields, {})), data_only=True)
    for index, field in enumerate(fields, start=1):
        assert exported[EXPORT_FIELDS[field]] == row[field]
        assert workbook["Fish Inspections"].cell(2, index).value == row[field]
    contributions = json.loads(row["fusion_source_contributions"])
    assert all(sum(source[grade] for source in contributions.values()) == pytest.approx(decision.weighted_scores[grade])
               for grade in GRADE_NAMES)


def test_fitting_and_untouched_evaluation_resolve_model_ties_for_all_classes():
    from src.evaluation.calibrate_decision_fusion import evaluate_calibration, fit_calibration
    from test_decision_fusion import verified_fixture_records

    records = verified_fixture_records()
    for row in records:
        target = row["human_grade"]
        other = GRADE_NAMES[(GRADE_NAMES.index(target) + 1) % len(GRADE_NAMES)]
        original, _, _ = score_case({target: .5, other: .5})
        row.update(ai_baseline=original.to_dict(), original_ai_prediction="Ungraded")
    calibrated = fit_calibration(records)
    assert calibrated["validation"]["passed"] is True
    assert calibrated["model2"]["validation_metrics"]["balanced_accuracy"] == 0.
    assert calibrated["model2"]["validation_metrics"]["ambiguous_prediction_count"] == 20
    test = evaluate_calibration(records, calibrated)
    assert test["resolved_score_review_correct_count"] == test["specimen_count"]
    assert all(test["candidate"]["per_class_recall"][grade] == 1. for grade in GRADE_NAMES)
    assert all(len(row["model2_leading_grades"]) == 2 and row["combined_leading_grades"] == [row["human_grade"]]
               for row in test["paired_outcomes"])


@pytest.mark.parametrize("target", GRADE_NAMES)
def test_runtime_resolves_ties_after_temporal_gates_for_every_class(target):
    from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
    from src.inference.part_types import PartDetection
    from test_decision_fusion import CONTEXT, SOURCE

    config = GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False)
    calibrated = artifact()
    calibrated["anatomical_policy"] = config.to_policy().to_dict()
    calibrated["model_context"] = {**CONTEXT, "anatomical_policy_sha256": fingerprint(calibrated["anatomical_policy"])}
    engine = WeightedGradingEngine(config, fusion_config=CONFIG, fusion_calibration=calibrated)
    other = GRADE_NAMES[(GRADE_NAMES.index(target) + 1) % len(GRADE_NAMES)]
    parts = [PartDetection.from_source_class(GRADE_NAMES.index(grade) * 3 + part, .5,
             (part * 20 + 1, 1, part * 20 + 18, 28)) for grade in (target, other) for part in range(3)]
    for index in range(config.minimum_track_observations):
        measured = measurements(dict.fromkeys(FAMILIES, target))
        measured["frame_id"] = index
        result = engine.evaluate(7, np.zeros((30, 70, 3), np.uint8), parts, stabilize=True, frame_id=index,
            source_context=SOURCE, fusion_measurements=measured,
            frame_quality={"fusion_checkpoint_sha256": CONTEXT["checkpoint_sha256"]})
        if index < config.minimum_track_observations - 1:
            assert result.final_grade is None and "UG_TEMPORAL_EVIDENCE" in result.reason_codes
    assert result.final_grade == target
    report = result.feature_fusion["decision_fusion"]
    assert report["model_only_prediction"] == "Ungraded"
    assert report["resolved_score_review_reasons"] == ["UG_LOW_MARGIN"]
    assert set(report["model2_leading_grades"]) == {target, other}
    json.dumps(result.to_dict(), allow_nan=False)
