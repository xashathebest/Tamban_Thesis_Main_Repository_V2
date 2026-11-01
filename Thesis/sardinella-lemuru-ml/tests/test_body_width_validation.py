"""Paired Class C measurement studies retain abstentions and review provenance."""

from copy import deepcopy
import json

import pytest

from src.evaluation.body_width_validation import evaluate_body_width_records, main


def sample(fish_id="fish-1", truth="Class B", baseline="Class B", candidate="Class B"):
    return {"fish_id": fish_id, "specimen_id": fish_id, "capture_session": "capture-1",
            "split": "validation", "expert_reviewer": "reviewer-1", "review_reference": "review-1",
            "independent_grade_review": True, "system_prediction_hidden": True,
            "association_reviewed": True, "association_correct": True,
            "true_grade": truth, "baseline_grade": baseline, "candidate_grade": candidate,
            "geometry_case": "horizontal", "manual_width_label": "normal",
            "analysis": {"body_width": {"status": "measured", "reliability": "Reliable proxy",
                "relative_width_proxy": .2, "score_contributed": False,
                "score_status": "Not calibrated", "class_c_supporting_points": None,
                "threshold_configuration": {"calibration_validated": False, "scoring_enabled": False}}}}


def with_contribution(record):
    width = record["analysis"]["body_width"]
    width.update(score_applied=True, score_contributed=True, score_status="Calibrated", class_c_supporting_points=5,
                 threshold_configuration={"calibration_validated": True, "scoring_enabled": True,
                    "calibration_id": "reviewed-validation-study", "validation_sample_count": 100,
                    "normal_reference_min": .1, "normal_reference_max": .2, "extreme_reference": .4})
    return record


def test_paired_metrics_include_ungraded_and_never_validate_descriptive_reference():
    rows = [with_contribution(sample("c", "Class C", "Ungraded", "Class C")),
            with_contribution(sample("b", "Class B", "Class B", "Class C")),
            with_contribution(sample("a", "Class A", "Class A", "Class A"))]
    rows[0]["manual_width_label"] = "widened"
    rows[0]["analysis"]["body_width"]["relative_width_proxy"] = .3
    report = evaluate_body_width_records(rows)
    assert report["baseline_class_c"]["ungraded_count"] == 1
    assert report["baseline_class_c"]["precision"] is None
    assert report["baseline_class_c"]["recall"] == 0
    assert report["candidate_class_c"]["precision"] == .5
    assert report["candidate_class_c"]["recall"] == 1
    assert report["candidate_class_c"]["false_positive_rate"] == .5
    assert report["changed_grade_count"] == 2
    assert report["reference_preparation"]["normal_observed_range"] == [.2, .2]
    assert report["reference_preparation"]["widened_observed_range"] == [.3, .3]
    assert report["reference_preparation"]["calibration_validated"] is False
    assert report["reference_preparation"]["thresholds_selected"] is False


def test_unavailable_measurements_remain_in_metrics_without_invented_proxy():
    record = sample(truth="Class C", baseline="Ungraded", candidate="Ungraded")
    record["analysis"] = {}
    record["geometry_case"] = "clipped"
    report = evaluate_body_width_records([record])
    assert report["fish_count"] == 1
    assert report["baseline_class_c"]["false_negative"] == 1
    assert report["reliability_counts"] == {"Unavailable": 1}
    assert report["reference_preparation"]["normal_observed_range"] is None
    assert report["records"][0]["relative_width_proxy"] is None


def test_applied_score_can_affect_abstention_without_an_accepted_grade():
    record = with_contribution(sample(truth="Class C", baseline="Class B", candidate="Ungraded"))
    record["analysis"]["body_width"]["score_contributed"] = False
    report = evaluate_body_width_records([record])
    assert report["records"][0]["score_applied"] is True
    assert report["records"][0]["score_contributed"] is False
    assert report["candidate_class_c"]["ungraded_count"] == 1


@pytest.mark.parametrize("field,value", [("independent_grade_review", False),
    ("system_prediction_hidden", False), ("association_reviewed", False),
    ("expert_reviewer", "UNKNOWN"), ("specimen_id", "UNKNOWN"), ("review_reference", "")])
def test_review_and_identity_are_required(field, value):
    record = sample()
    record[field] = value
    with pytest.raises(ValueError):
        evaluate_body_width_records([record])


def test_duplicate_physical_specimens_and_capture_leakage_are_rejected():
    first, second = sample(), sample("fish-2")
    second["specimen_id"] = first["specimen_id"]
    with pytest.raises(ValueError, match="Duplicate specimen_id"):
        evaluate_body_width_records([first, second])
    second["specimen_id"] = "fish-2"
    second["split"] = "test"
    with pytest.raises(ValueError, match="overlaps splits"):
        evaluate_body_width_records([first, second])


@pytest.mark.parametrize("scenario", ["diagonal", "overlapping", "clipped"])
def test_reviewed_geometry_cannot_be_reported_as_reliable(scenario):
    record = sample()
    record["geometry_case"] = scenario
    with pytest.raises(ValueError, match="must not have a reliable"):
        evaluate_body_width_records([record])


def test_bad_association_and_uncalibrated_contributions_are_rejected():
    record = sample()
    record["association_correct"] = False
    with pytest.raises(ValueError, match="correct reviewed association"):
        evaluate_body_width_records([record])
    record = sample()
    record["analysis"]["body_width"]["score_contributed"] = True
    with pytest.raises(ValueError, match="enabled validated calibration"):
        evaluate_body_width_records([record])


def test_missing_width_cannot_change_grade_or_create_fake_calibration():
    record = sample(candidate="Class C")
    record["analysis"] = {}
    with pytest.raises(ValueError, match="must be preserved"):
        evaluate_body_width_records([record])
    record = sample()
    report = evaluate_body_width_records([record])
    assert report["threshold_configuration"]["calibration_validated"] is False
    assert report["changed_grade_count"] == 0


def test_one_frozen_configuration_is_required():
    first, second = sample(), sample("fish-2")
    second["analysis"]["body_width"]["threshold_configuration"]["calibration_id"] = "different"
    with pytest.raises(ValueError, match="one frozen"):
        evaluate_body_width_records([first, second])


def test_only_requested_split_contributes_to_metrics():
    validation, test = sample(), sample("test-fish", truth="Class C", baseline="Class C", candidate="Class C")
    test.update(split="test", capture_session="capture-2")
    report = evaluate_body_width_records([validation, test], dataset_split="test")
    assert report["fish_count"] == 1
    assert report["records"][0]["fish_id"] == "test-fish"
    assert report["candidate_class_c"]["recall"] == 1


def test_csv_json_string_width_and_cli_jsonl_provenance(tmp_path):
    record = sample()
    expected = deepcopy(record["analysis"]["body_width"])
    record["body_width_analysis"] = json.dumps(expected)
    del record["analysis"]
    record["association_correct"] = "true"
    source = tmp_path / "reviewed.jsonl"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert main(["--records", str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["source_sha256"]) == 64
    assert report["records"][0]["relative_width_proxy"] == .2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -.1, 0])
def test_invalid_measurements_are_rejected(value):
    record = sample()
    record["analysis"]["body_width"]["relative_width_proxy"] = value
    with pytest.raises(ValueError, match="relative_width_proxy"):
        evaluate_body_width_records([record])


def runtime_width_record(enabled=True, method="body_component_v1", parent_usable=True):
    import numpy as np

    from src.inference.body_width import BodyWidthConfig, analyze_body_width
    from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
    from src.inference.part_types import PartDetection

    config = BodyWidthConfig(scoring_enabled=enabled, calibration_validated=True, scoring_method=method,
        calibration_id="synthetic-replay-test", validation_sample_count=1,
        normal_reference_min=.05, normal_reference_max=.1, extreme_reference=.15)
    parts = [PartDetection.from_source_class(class_id, confidence, box) for class_id, confidence, box in (
        (0, .70, (70, 25, 170, 55)), (6, .65, (70, 25, 170, 55)),
        (1, .40, (30, 25, 50, 55)), (7, .30, (30, 25, 50, 55)),
        (2, .40, (190, 25, 210, 55)), (8, .30, (190, 25, 210, 55)))]
    crop = np.zeros((100, 260, 3), dtype=np.uint8)
    width = analyze_body_width((20, 20, 220, 60), parts, config=config,
        detection_confidence=.9, frame_shape=crop.shape)
    engine = WeightedGradingEngine(GradingConfig(), body_width_config=config)
    verdict = engine.evaluate(1, crop, parts, stabilize=False, body_width=width, parent_usable=parent_usable)
    return {"analysis": verdict.to_dict()}, engine.configuration_snapshot(), verdict


@pytest.mark.parametrize("enabled", [True, False])
def test_full_runtime_snapshot_replay_matches_raw_and_adjusted_scores(enabled):
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, runtime = runtime_width_record(enabled)
    rules = EvaluationRules.from_mapping(snapshot)
    replay = recompute_final_verdict(record, rules)
    assert replay["final_grade"] == (runtime.final_grade or "Ungraded")
    assert replay["weighted_scores"] == pytest.approx(runtime.weighted_scores)
    assert replay["body_width"]["applied_body_score_shift"] == pytest.approx(.1 if enabled else 0)
    assert replay["body_width"]["score_applied"] is enabled
    assert rules.to_dict()["body_width"] == snapshot["body_width"]
    assert record["analysis"]["part_results"]["Body"]["grade_evidence"]["Class C"] == .65
    assert record["analysis"]["part_results"]["Body"]["adjusted_grade_evidence"]["Class C"] == pytest.approx(.75 if enabled else .65)


def test_replaying_adjusted_runtime_record_uses_raw_scores_once_and_can_disable():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, _ = runtime_width_record()
    before = deepcopy(record)
    first = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    second = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert first["weighted_scores"] == second["weighted_scores"]
    assert record == before
    assert first["final_grade"] == "Class C"
    snapshot["body_width"]["scoring_enabled"] = False
    baseline = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert baseline["final_grade"] == "Class A"
    assert baseline["body_width"]["score_applied"] is False
    assert baseline["weighted_scores"]["Class C"] == pytest.approx(.475)


def test_changed_thresholds_cannot_reuse_precomputed_width_points():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, _ = runtime_width_record()
    snapshot["body_width"]["extreme_reference"] = .2
    with pytest.raises(ValueError, match="saved calibration"):
        recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))


def test_missing_width_evidence_preserves_raw_baseline_even_with_enabled_snapshot():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, _ = runtime_width_record()
    del record["analysis"]["body_width"]
    replay = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert replay["final_grade"] == "Class A"
    assert replay["body_width"]["score_contributed"] is False


def test_invalid_or_unknown_width_snapshot_fails_replay_configuration():
    from src.evaluation.fish_level_validation import EvaluationRules

    with pytest.raises(ValueError, match="body_width replay configuration"):
        EvaluationRules.from_mapping({"body_width": {"calibration_validated": True}})


def test_post_weighted_replay_matches_runtime_and_preserves_original_part_support():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, runtime = runtime_width_record(method="post_weighted_v2")
    replay = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert replay["final_grade"] == runtime.final_grade == "Class C"
    assert replay["weighted_scores"] == pytest.approx(runtime.weighted_scores)
    assert sum(replay["weighted_scores"].values()) == pytest.approx(1)
    assert replay["geometric_support"] == record["analysis"]["geometric_support"]
    assert replay["geometric_support"]["original_grade"] == "Class A"
    assert replay["geometric_support"]["width_changed_classification"] is True
    assert replay["body_width"]["applied_body_score_shift"] == 0
    assert replay["body_width"]["applied_geometric_score_shift"] == pytest.approx(.1)
    assert record["analysis"]["part_results"]["Body"]["grade_evidence"] == record["analysis"]["part_results"]["Body"]["adjusted_grade_evidence"]
    twice = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert twice["weighted_scores"] == replay["weighted_scores"]
    snapshot["body_width"]["scoring_enabled"] = False
    baseline = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert baseline["final_grade"] == "Class A"
    assert baseline["weighted_scores"] == replay["geometric_support"]["original_scores"]


def test_historical_snapshot_without_scoring_method_replays_legacy_stage():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, runtime = runtime_width_record(method="body_component_v1")
    snapshot["body_width"].pop("scoring_method")
    snapshot["body_width"].pop("maximum_geometric_contribution")
    record["analysis"]["body_width"]["threshold_configuration"] = deepcopy(snapshot["body_width"])
    rules = EvaluationRules.from_mapping(snapshot)
    replay = recompute_final_verdict(record, rules)
    assert rules.body_width["scoring_method"] == "body_component_v1"
    assert replay["weighted_scores"] == runtime.weighted_scores
    assert "geometric_support" not in replay


def test_post_weighted_width_never_bypasses_original_ungraded_gates():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, _ = runtime_width_record(method="post_weighted_v2")
    record["analysis"]["temporal_stability"]["ready"] = False
    replay = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert replay["final_grade"] == "Ungraded"
    assert replay["geometric_support"]["contribution_reason"] == "baseline_ungraded_evidence_gates"
    assert replay["body_width"]["score_applied"] is False


def test_replay_preserves_recorded_parent_unusable_gate_before_width_stage():
    from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict

    record, snapshot, runtime = runtime_width_record(method="post_weighted_v2", parent_usable=False)
    assert runtime.final_grade is None
    assert record["analysis"]["frame_quality"]["parent_usable"] is False
    replay = recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))
    assert replay["final_grade"] == "Ungraded"
    assert "UG_PARENT_UNCERTAIN" in replay["reason_codes"]
    assert replay["weighted_scores"] == runtime.weighted_scores
    assert replay["body_width"]["score_applied"] is False


def test_raw_unreliable_proxy_is_retained_but_excluded_from_reference_calibration():
    record = sample()
    record["geometry_case"] = "overlapping"
    record["analysis"]["body_width"].update(reliability="Unreliable", reliable_for_scoring=False,
        measurement_status="Unreliable", measurement_available=True)
    report = evaluate_body_width_records([record])
    assert report["records"][0]["relative_width_proxy"] == .2
    assert report["reference_preparation"]["normal_count"] == 0
    assert report["reliability_counts"] == {"Unreliable": 1}
