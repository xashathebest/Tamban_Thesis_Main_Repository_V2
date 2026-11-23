"""Synthetic policy controls, not a real-fish accuracy or calibration claim."""
from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pytest

from src.inference.decision_fusion import (
    EXTRACTOR_VERSION, FAMILIES, FEATURE_KEYS, GRADE_NAMES, REQUIRED_CHECKS, WEIGHTS,
    DecisionFusionConfig, fingerprint, fuse_decision, load_decision_fusion_config,
)
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.grading_policy import FishGradingInput, GradingPolicy, grade_fish
from src.inference.part_types import PartDetection

SOURCE = {"source_id": "synthetic-fixture-only", "frame_pixels_sha256": "a" * 64}
POLICY = GradingPolicy(grading_mode="tail_optional_v1")
CONTEXT = {"checkpoint_sha256": "b" * 64, "anatomical_policy_sha256": fingerprint(POLICY.to_dict())}
CONFIG = DecisionFusionConfig()


def baseline(scores=None):
    scores = scores or {"Class A": .9, "Class B": .01, "Class C": .01, "Rejected": .01}
    return grade_fish(FishGradingInput(part_scores={part: dict(scores) for part in ("Head", "Body", "Tail")},
        presence_confidence={part: .9 for part in ("Head", "Body", "Tail")}), POLICY)


def artifact():
    return {"schema_version": "decision_fusion_calibration_v1", "extractor_version": EXTRACTOR_VERSION,
        "classes": list(GRADE_NAMES), "calibration_id": "synthetic-software-fixture-not-scientific-validation",
        "fusion_policy_id": CONFIG.policy_id(), "model_context": CONTEXT,
        "anatomical_policy": POLICY.to_dict(),
        "model2": {"validated": True, "temperature": 1.},
        "validation": {"passed": True},
        "provenance": {"manifest_sha256": "c" * 64,
                       "split_groups": {"calibration": ["specimen:fit"], "validation": ["specimen:val"], "test": ["specimen:test"]}},
        "features": {family: {"validated": True, "keys": list(FEATURE_KEYS[family]),
            "reliability": 1., "per_class_reliability": dict.fromkeys(GRADE_NAMES, 1.),
            "temperature": 1., "distance_limit": 4., "capture_profiles": ["fixture-profile"],
            "class_counts": {split: dict.fromkeys(GRADE_NAMES, 5) for split in ("calibration", "validation")},
            "distributions": {grade: {"mean": [float(i)] * len(FEATURE_KEYS[family]),
                                     "scale": [.15] * len(FEATURE_KEYS[family]), "prior": .25}
                              for i, grade in enumerate(GRADE_NAMES)}} for family in FAMILIES}}


def measurements(targets=None):
    targets = targets or dict.fromkeys(FAMILIES, "Class A")
    return {"extractor_version": EXTRACTOR_VERSION, "fish_id": 7, "frame_id": "frame-1", **SOURCE,
        "capture_profile_id": "fixture-profile",
        "features": {family: {"values": dict.fromkeys(FEATURE_KEYS[family], float(GRADE_NAMES.index(grade))),
            "checks": dict.fromkeys(REQUIRED_CHECKS[family], True), "measurement_reliability": 1.}
            for family, grade in targets.items()}}


def run(measured=None, calibration=None, **kwargs):
    return fuse_decision(baseline(), measured if measured is not None else measurements(), CONFIG,
        calibration if calibration is not None else artifact(), fish_id=7, frame_id="frame-1", source=SOURCE,
        model_context=CONTEXT, **kwargs)


def test_agreement_contributes_to_actual_accepted_support_and_preserves_anatomy():
    original = baseline()
    decision, report = run()
    assert report["decision_state"] == "AGREEMENT"
    assert decision.final_grade == "Class A" and decision.final_support > original.final_support
    assert report["review_required"] is False
    assert report["effective_weights"] == pytest.approx(WEIGHTS)
    assert decision.effective_weights == original.effective_weights == {"Head": .3, "Body": .5, "Tail": .2}
    assert sum(report["per_class_combined_support"].values()) == pytest.approx(1.)
    assert report["evidence_agreement_score"] > .9


def test_calibrated_size_can_change_the_final_grade_not_just_the_display():
    original = baseline({"Class A": .51, "Class B": .49, "Class C": 0., "Rejected": 0.})
    decision, report = fuse_decision(original, measurements({"size": "Class B"}), CONFIG, artifact(),
        fish_id=7, frame_id="frame-1", source=SOURCE, model_context=CONTEXT)
    assert original.final_grade == "Class A" and decision.final_grade == "Class B"
    assert report["model_only_prediction"] == "Class A" and report["final_fused_prediction"] == "Class B"
    assert report["features"]["size"]["used_for_grading"]
    assert report["effective_weights"] == pytest.approx({"model2": .7, "size": .3, "cracks": 0., "color": 0., "texture": 0.})
    assert report["decision_confidence"] >= CONFIG.minimum_decision_confidence


def test_one_low_weight_disagreement_does_not_automatically_downgrade():
    decision, report = run(measurements({"size": "Class A", "cracks": "Class C", "color": "Class A", "texture": "Class A"}))
    assert report["decision_state"] == "MINOR_DISAGREEMENT"
    assert decision.final_grade == "Class A" and report["review_required"] is False
    assert report["features"]["cracks"]["conflict_severity"] > 0
    assert "cracks:" in report["disagreement_reasons"][0]


def test_multiple_reliable_contradictions_force_review_even_with_model_winning():
    decision, report = run(measurements({"size": "Class C", "cracks": "Class C", "color": "Class A", "texture": "Class A"}))
    assert report["decision_state"] == "MAJOR_DISAGREEMENT"
    assert decision.final_grade is None and report["review_required"]
    assert "UG_FUSION_MAJOR_DISAGREEMENT" in decision.reason_codes
    assert report["decision_confidence"] < .5 and len(report["disagreement_reasons"]) == 2


def test_no_calibration_keeps_exact_model2_verdict_and_exposes_absent_support():
    decision, report = run(calibration={})
    assert decision == baseline()
    assert report["mode"] == "model2_only"
    assert report["model2_class_probabilities"] is None
    assert report["feature_only_prediction"] is None
    assert report["evidence_agreement_score"] is None and report["agreement_validated"] is False
    assert report["effective_weights"]["model2"] == .7
    assert sum(report["effective_weights"].values()) == .7
    assert report["unallocated_supporting_weight"] == .3
    assert not any(f["used_for_grading"] for f in report["features"].values())


@pytest.mark.parametrize("change", [{"fish_id": 8}, {"frame_id": "old"}, {"frame_pixels_sha256": "d" * 64},
    {"source_id": "other"}, {"extractor_version": "old"}, {"capture_profile_id": "uncalibrated-lighting"}])
def test_stale_other_fish_or_out_of_domain_evidence_is_excluded(change):
    measured = measurements(); measured.update(change)
    decision, report = run(measured)
    assert decision == baseline() and report["mode"] == "model2_only"


@pytest.mark.parametrize("family,check", [(family, key) for family, keys in REQUIRED_CHECKS.items() for key in keys])
def test_every_required_validation_check_withholds_its_feature(family, check):
    measured = measurements(); measured["features"][family]["checks"][check] = False
    _, report = run(measured)
    assert report["features"][family]["eligible"] is False
    assert report["effective_weights"][family] == 0.
    assert sum(report["effective_weights"].values()) == pytest.approx(1.)
    assert f"validation_failed:{check}" in report["features"][family]["reasons"]


def test_reliability_changes_supporting_weight_only_and_does_not_hide_uncertainty():
    measured = measurements({"size": "Class A", "color": "Class A"})
    measured["features"]["color"]["measurement_reliability"] = .8
    _, report = run(measured)
    assert report["effective_weights"]["model2"] == .7
    assert report["effective_weights"]["size"] == pytest.approx(.3 * .15 / (.15 + .05 * .8))
    assert report["per_feature_reliability"]["color"] == .8
    assert sum(report["effective_weights"][key] for key in FAMILIES) == pytest.approx(.3)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_missing_or_nonfinite_measurement_is_unavailable_not_poor_quality(value):
    measured = measurements(); measured["features"]["size"]["values"][FEATURE_KEYS["size"][0]] = value
    _, report = run(measured)
    assert not report["features"]["size"]["eligible"] and report["effective_weights"]["size"] == 0
    json.dumps(report, allow_nan=False)


def test_outside_reference_distribution_withholds_feature_without_downgrading():
    measured = measurements({"size": "Class A"})
    measured["features"]["size"]["values"] = dict.fromkeys(FEATURE_KEYS["size"], 1e300)
    decision, report = run(measured)
    assert decision == baseline()
    assert "outside_calibrated_reference_distribution" in report["features"]["size"]["reasons"]
    json.dumps(report, allow_nan=False)


def test_independent_head_absence_blocks_grade_even_without_any_feature_calibration():
    head = {"fish_id": 7, "frame_id": "frame-1", **SOURCE, "state": "confirmed_absent", "reviewed": True,
            "ownership_validated": True, "visibility_validated": True, "reviewer": "fixture-only", "review_id": "head-fixture"}
    decision, report = run(calibration={}, head_evidence=head)
    assert decision.final_grade is None and report["decision_state"] == "CRITICAL_ANATOMICAL_DISAGREEMENT"
    assert report["review_required"] and decision.reason_codes == ("UG_CONFIRMED_MISSING_HEAD",)
    stale, stale_report = run(calibration={}, head_evidence={**head, "frame_id": "old"})
    assert stale.final_grade == "Class A" and not stale_report["head_integrity"]["confirmed_missing_head"]


def test_fusion_never_repairs_missing_model2_evidence_or_rejected_override():
    original = replace(baseline(), final_grade=None, reason_codes=("UG_MISSING_PART_EVIDENCE",))
    decision, report = fuse_decision(original, measurements(), CONFIG, artifact(), fish_id=7,
        frame_id="frame-1", source=SOURCE, model_context=CONTEXT)
    assert decision.final_grade is None and "UG_MISSING_PART_EVIDENCE" in decision.reason_codes
    rejected = replace(baseline(), final_grade="Rejected", override={"applied": True})
    decision, _ = fuse_decision(rejected, measurements(), CONFIG, artifact(), fish_id=7,
        frame_id="frame-1", source=SOURCE, model_context=CONTEXT)
    assert decision.final_grade != "Class A" and decision.override == rejected.override


def test_runtime_engine_uses_same_fusion_and_preserves_original_model_parts():
    config = GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False)
    calibrated = artifact()
    calibrated["model_context"] = {**CONTEXT, "anatomical_policy_sha256": fingerprint(config.to_policy().to_dict())}
    engine = WeightedGradingEngine(config, fusion_config=CONFIG, fusion_calibration=calibrated)
    detections = [PartDetection.from_source_class(i, score, (5 + i % 3 * 20, 5, 25 + i % 3 * 20, 25))
                  for i, score in [(0, .51), (1, .51), (2, .51), (3, .49), (4, .49), (5, .49)]]
    result = engine.evaluate(7, np.zeros((30, 70, 3), np.uint8), detections, stabilize=False,
        frame_id="frame-1", source_context=SOURCE, fusion_measurements=measurements({"size": "Class B"}),
        frame_quality={"fusion_checkpoint_sha256": CONTEXT["checkpoint_sha256"]})
    assert result.final_grade == "Class B"
    assert result.feature_fusion["decision_fusion"]["model_only_prediction"] == "Class A"
    assert result.part_results["Body"]["grade"] == "Class A"
    assert result.effective_weights == {"Head": .3, "Body": .5, "Tail": .2}
    assert result.feature_fusion["contributions_applied"] == ["size"]
    json.dumps(result.to_dict(), allow_nan=False)


def test_shipped_weights_and_input_records_are_preserved():
    assert load_decision_fusion_config().to_dict()["configured_weights"] == WEIGHTS
    measured, calibrated = measurements(), artifact()
    before = deepcopy((measured, calibrated))
    run(measured, calibrated)
    assert (measured, calibrated) == before


def verified_fixture_records():
    """Artificial separable classes test fitting mechanics, never accuracy."""
    import hashlib
    records = []
    rng = np.random.default_rng(17)
    for split, count in (("calibration", 6), ("validation", 5), ("test", 2)):
        for i, grade in enumerate(GRADE_NAMES):
            for index in range(count):
                name = f"{split}-{i}-{index}"
                digest = hashlib.sha256(name.encode()).hexdigest()
                source = {"source_id": "fixture-only", "frame_pixels_sha256": digest}
                measured = measurements(dict.fromkeys(FAMILIES, grade))
                measured.update(**source, frame_id=name)
                for family in FAMILIES:
                    measured["features"][family]["values"] = {key: i + float(rng.normal(0, .02)) for key in FEATURE_KEYS[family]}
                scores = {label: .85 if label == grade else .05 for label in GRADE_NAMES}
                original = baseline(scores)
                records.append({"specimen_id": name, "capture_group_id": f"capture-{name}",
                    "duplicate_group_id": f"lineage-{name}", "image_sha256": digest,
                    "split": split, "annotator_verified": True, "annotator_id": "fixture-not-real-annotator",
                    "review_id": f"fixture-review-{name}", "human_grade": grade,
                    "original_ai_prediction": grade, "ai_baseline": original.to_dict(),
                    "measurements": measured, "model_context": CONTEXT, "anatomical_policy": POLICY.to_dict(),
                    "source": source, "fish_id": 7, "frame_id": name})
    return records


def test_fit_uses_real_class_distributions_and_keeps_test_for_separate_evaluation():
    from src.evaluation.calibrate_decision_fusion import evaluate_calibration, fit_calibration
    rows = verified_fixture_records(); before = deepcopy(rows)
    calibrated = fit_calibration(rows, CONFIG)
    assert calibrated["validation"]["passed"] is True
    assert calibrated["provenance"]["test_labels_used_for_fitting"] is False
    assert all(entry["validated"] for entry in calibrated["features"].values())
    result = evaluate_calibration(rows, calibrated, CONFIG)
    assert result["split"] == "test" and result["specimen_count"] == 8
    assert len(result["candidate"]["confusion_matrix"]) == 4
    assert result["candidate"]["confusion_columns"][-1] == "Ungraded"
    assert result["bootstrap_repetitions"] == 500
    altered = deepcopy(rows)
    for row in altered:
        if row["split"] == "test": row["human_grade"] = "Rejected"
    second = fit_calibration(altered, CONFIG)
    assert second["features"] == calibrated["features"]
    assert second["model2"] == calibrated["model2"]
    assert rows == before
    json.dumps(calibrated, allow_nan=False)


@pytest.mark.parametrize("identity", ["specimen_id", "capture_group_id", "duplicate_group_id", "image_sha256"])
def test_physical_specimen_capture_and_duplicate_leakage_is_rejected(identity):
    from src.evaluation.calibrate_decision_fusion import validate_records
    rows = verified_fixture_records()
    first = rows[0]; last = rows[-1]
    last[identity] = first[identity]
    with pytest.raises(ValueError, match="leakage|physical specimen"):
        validate_records(rows)


def test_renamed_duplicate_native_pixels_cannot_evade_partition_checks():
    from src.evaluation.calibrate_decision_fusion import validate_records
    rows = verified_fixture_records()
    rows[-1]["source"]["frame_pixels_sha256"] = rows[0]["source"]["frame_pixels_sha256"]
    rows[-1]["measurements"]["frame_pixels_sha256"] = rows[0]["source"]["frame_pixels_sha256"]
    with pytest.raises(ValueError, match="frame_pixels_sha256"):
        validate_records(rows)


def test_pseudo_labels_and_unknown_specimens_cannot_establish_calibration():
    from src.evaluation.calibrate_decision_fusion import fit_calibration
    for changes in ({"annotator_verified": False}, {"specimen_id": "unknown"}, {"annotator_id": ""}):
        rows = verified_fixture_records(); rows[0].update(changes)
        with pytest.raises(ValueError): fit_calibration(rows)


def test_export_keeps_original_ai_separate_from_review_and_records_disagreement():
    from src.api.export import inspection_row
    original = baseline()
    decision, report = run(measurements({"size": "Class C", "color": "Class C"}))
    event = {"track_id": 7, "quality": "Ungraded", "manual_grade": "Class B", "manual_override": True,
             "analysis": {"final_grade": "Ungraded", "verdict_status": "NEEDS_REVIEW",
                          "weighted_scores": decision.weighted_scores,
                          "feature_fusion": {"schema_version": "feature_fusion_v1", "original_grade": original.final_grade,
                              "final_grade": "Ungraded", "final_support": decision.final_support, "decision_fusion": report}}}
    row = inspection_row(event)
    assert row["model2_only_prediction"] == "Class A" and row["final_fused_prediction"] == "Ungraded"
    assert row["manual_grade"] == "Class B" and row["fusion_review_required"] == "Yes"
    assert row["fusion_decision_state"] == "MAJOR_DISAGREEMENT"
    assert json.loads(row["fusion_effective_weights"])["model2"] == .7


def test_review_export_requires_real_specimen_link_and_keeps_original_prediction(tmp_path):
    from src.api.database import InspectionDatabase
    from src.evaluation.calibrate_decision_fusion import export_review_records
    database = InspectionDatabase(tmp_path / "reviews.sqlite")
    session = database.create_session({})
    _, report = run()
    database.upsert_event(session, {"track_id": 7, "timestamp": "2026-11-23T00:00:00-05:00", "quality": "Class A",
        "analysis": {"final_grade": "Class A", "feature_fusion": {"decision_fusion": report},
                     "frame_quality": {"latest": {"fusion_measurements": measurements(), "source_context": SOURCE}}}})
    database.apply_manual_review(session, 7, "Class B", reviewer="fixture-reviewer")
    missing = export_review_records(database.path, [])
    assert missing["records"] == [] and len(missing["withheld"]) == 1
    identities = [{"session_id": session, "track_id": 7, "specimen_id": "fixture-specimen", "capture_group_id": "fixture-capture",
                   "duplicate_group_id": "fixture-lineage", "image_sha256": "a" * 64, "split": "calibration"}]
    result = export_review_records(database.path, identities)
    assert result["records"][0]["original_ai_prediction"] == "Class A"
    assert result["records"][0]["human_grade"] == "Class B"
    stored = database.events(session_id=session)[0]
    assert stored["analysis"]["final_grade"] == "Class A" and stored["manual_grade"] == "Class B"


def test_whole_fish_measurements_ignore_background_and_require_explicit_validation():
    from src.features.fusion import extract_fusion_measurements
    import cv2
    image = np.full((40, 80, 3), 140, np.uint8)
    mask = np.zeros((40, 80), np.uint8); cv2.ellipse(mask, (40, 20), (32, 14), 0, 0, 360, 1, -1)
    first = extract_fusion_measurements(image, mask, fish_id=7, frame_id="frame-1", source=SOURCE)
    image[mask == 0] = 255
    second = extract_fusion_measurements(image, mask, fish_id=7, frame_id="frame-1", source=SOURCE)
    assert first["features"] == second["features"]
    assert all(not all(entry["checks"].values()) for entry in first["features"].values())
    assert all(entry["measurement_reliability"] == 0 for entry in first["features"].values())
    assert first["features"]["color"]["values"]["mean_value"] == pytest.approx(140 / 255)


def test_complete_mask_and_lighting_checks_cannot_be_inferred_from_segmentation_success():
    from src.features.fusion import extract_fusion_measurements
    validation = {"fish_id": 7, "frame_id": "frame-1", **SOURCE, "reviewed": True,
        "complete_mask": True, "ownership_validated": True, "measurement_validated": True,
        "capture_profile_id": "fixture-profile", "validation_provenance": {"reviewer": "fixture", "review_id": "fixture", "reference_set_id": "fixture"},
        "color": {"lighting_calibrated": True},
        "lighting": {"validated": True, "profile_id": "fixture-profile", "rgb_gains": [1., 1., 1.], "rgb_offsets": [0., 0., 0.]}}
    mask = np.ones((10, 20), np.uint8)
    args = dict(fish_id=7, frame_id="frame-1", source=SOURCE, validation=validation)
    measured = extract_fusion_measurements(np.full((10, 20, 3), 100, np.uint8), mask, **args,
        mask_metadata={"full_frame_foreground_pixels": 300})
    assert measured["features"]["color"]["checks"]["complete_mask"] is False
    assert measured["features"]["color"]["measurement_reliability"] == 0
    assert measured["lighting_correction_applied"] is True
    validation["lighting"]["validated"] = False
    uncalibrated = extract_fusion_measurements(np.full((10, 20, 3), 100, np.uint8), mask, **args)
    assert uncalibrated["features"]["color"]["checks"]["lighting_calibrated"] is False


def test_saved_head_absence_holds_review_without_rewriting_ai_prediction():
    from src.inference.structural_evidence import StructuralEvidence, requires_human_review, summarize_structural_evidence
    summary = summarize_structural_evidence([StructuralEvidence("Head", "confirmed_absent", "expert_review", .95,
        "fixture-image", "2026-11-23T00:00:00-05:00", "fixture-reviewer")])
    analysis = {"final_grade": "Class A", "verdict_status": "AUTO_GRADED", "structural_evidence": summary}
    assert requires_human_review(analysis)
    assert analysis["final_grade"] == "Class A" and summary["automatic_grade_effect"] is False
    assert summary["independent_head_review_required"] is True


def test_size_requires_owned_endpoints_perpendicular_width_and_consistent_ratios():
    from src.features.fusion import _size_geometry_checks
    mask = np.ones((40, 80), bool)
    geometry = {"fish_length_px": 65., "body_profile_length_px": 40., "max_body_width_px": 29.,
        "relative_width_ratio": 29. / 65, "body_width_to_length_ratio": 29. / 40,
        "visualization": {"length_path": [[8., 20.], [40., 20.], [72., 20.]], "width_axis": [[40., 6.], [40., 34.]]}}
    metadata = {"crop_bounds": [0, 0, 80, 40]}
    assert all(_size_geometry_checks(geometry, mask, metadata).values())
    skewed = deepcopy(geometry); skewed["visualization"]["width_axis"] = [[25., 6.], [55., 34.]]
    assert not _size_geometry_checks(skewed, mask, metadata)["perpendicular_widths"]
    mask[20, 8] = False
    assert not _size_geometry_checks(geometry, mask, metadata)["anatomical_endpoints"]
    geometry["relative_width_ratio"] = .9
    assert not _size_geometry_checks(geometry, mask, metadata)["proportions"]
