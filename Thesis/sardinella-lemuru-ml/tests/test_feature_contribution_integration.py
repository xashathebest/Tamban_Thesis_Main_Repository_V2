"""Native-pixel software controls; these references are not fish calibration."""
from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pytest

from src.inference.decision_fusion import FAMILIES, FEATURE_KEYS, REQUIRED_CHECKS, WEIGHTS, fingerprint
from src.inference.grading_engine import WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import RuntimeMaskContext
from test_decision_fusion import artifact
from test_experimental_segmentation_pipeline import PARENTS, Service, model
from test_sam_features_runtime import catalog


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    frame = np.random.default_rng(8).integers(30, 220, (120, 640, 3), dtype=np.uint8)
    row, path, save, _ = catalog(tmp_path, frame)
    validation = {key: deepcopy(row[key]) for key in (
        "fish_id", "source_id", "frame_pixels_sha256", "reviewed",
        "ownership_validated", "measurement_validated", "validation_provenance",
    )}
    validation.update(frame_id="original-review", complete_mask=True, capture_profile_id="fixture-profile")
    validation.update({family: dict.fromkeys(checks, True) for family, checks in REQUIRED_CHECKS.items()})
    validation["lighting"] = {"validated": True, "profile_id": "fixture-profile",
                              "rgb_gains": [1., 1., 1.], "rgb_offsets": [0., 0., 0.]}
    validation["cracks"].update(measurement_source="reviewed_structural_measurement",
                                values={"crack_area_fraction": 0., "crack_length_to_fish_length": 0.})
    row["fusion_validation"] = validation
    save(row)
    monkeypatch.setenv("FISH_REVIEWED_FEATURES_PATH", str(path))
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: Service())
    quality = model()
    quality._grading_engine = WeightedGradingEngine(quality._grading_engine.config, fusion_calibration={})
    quality.checkpoint_sha256_full = "b" * 64
    # The unmodified anatomical policy accepts A at .500 versus B at .495.
    parts = [PartDetection.from_source_class(class_id, confidence, box) for class_id, confidence, box in (
        (0, 1., (90, 38, 215, 82)), (4, .99, (30, 47, 75, 73)), (5, .99, (230, 50, 260, 70)),
    )]
    quality._infer_parts = lambda _: (parts, parts)

    def analyze():
        return quality.predict_full_frame(
            frame, PARENTS[:1], stabilize=False, frame_id="native-feature-frame",
            mask_context=RuntimeMaskContext(frame, frame_id="native-feature-frame", backend="mobilesam_experimental"),
            source_context={"source_id": "fixture-source"},
        )[1][0]

    return quality, row, save, analyze


def calibrate_control(quality, original, targets):
    """Center artificial references on extracted pixels to test integration only."""
    calibrated = deepcopy(artifact())
    calibrated["anatomical_policy"] = quality._grading_engine.config.to_policy().to_dict()
    calibrated["model_context"] = {"checkpoint_sha256": quality.checkpoint_sha256_full,
        "anatomical_policy_sha256": fingerprint(calibrated["anatomical_policy"])}
    measured = original.analysis["frame_quality"]["latest"]["fusion_measurements"]
    calibrated["features"] = {family: calibrated["features"][family] for family in targets}
    for family, target in targets.items():
        values = [measured["features"][family]["values"][key] for key in FEATURE_KEYS[family]]
        target_index = calibrated["classes"].index(target)
        for index, distribution in enumerate(calibrated["features"][family]["distributions"].values()):
            distribution["mean"] = [value + index - target_index for value in values]
    engine = quality._grading_engine
    quality._grading_engine = WeightedGradingEngine(engine.config, fusion_config=engine.fusion_config,
                                                   fusion_calibration=calibrated)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("diagnostics_enabled", [False, True])
def test_each_native_feature_changes_actual_scoring_with_review_safeguards(native_case, family, diagnostics_enabled):
    quality, _, _, analyze = native_case
    quality._grading_engine.config = replace(quality._grading_engine.config, image_diagnostics_enabled=diagnostics_enabled)
    original = analyze()
    assert original.quality == "Class A"
    calibrate_control(quality, original, {family: "Class B"})
    result = analyze()
    fusion = result.analysis["feature_fusion"]["decision_fusion"]
    assert fusion["mode"] == "calibrated_fusion"
    assert fusion["model_only_prediction"] == "Class A"
    assert fusion["fused_candidate_prediction"] == "Class B"
    assert fusion["features"][family]["used_for_grading"] is True
    assert fusion["effective_weights"][family] == pytest.approx(.3)
    assert result.analysis["weighted_scores"] != original.analysis["weighted_scores"]
    assert result.analysis["effective_weights"] == original.analysis["effective_weights"]
    if family == "size":
        assert result.quality == "Class B"
        assert result.analysis["fish_geometry"]["used_for_grading"] is True
        assert result.analysis["fish_geometry"]["grading_contribution"]["calibration_id"] == fusion["calibration_id"]
        from src.api.export import inspection_row
        exported = inspection_row({"track_id": 1, "quality": result.quality, "analysis": result.analysis})
        assert exported["fish_geometry_used_for_grading"] == "Yes"
        assert json.loads(exported["fusion_source_contributions"]) == fusion["per_source_class_contributions"]
    else:
        assert result.quality is None
        assert "UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE" in fusion["review_reasons"]
        assert result.analysis["fish_geometry"]["used_for_grading"] is False


def test_all_native_features_have_numeric_contributions_that_reconstruct_the_verdict(native_case):
    quality, _, _, analyze = native_case
    original = analyze()
    calibrate_control(quality, original, dict.fromkeys(FAMILIES, "Class A"))
    result = analyze()
    fusion = result.analysis["feature_fusion"]["decision_fusion"]
    assert result.quality == "Class A" and not fusion["review_required"]
    assert fusion["effective_weights"] == pytest.approx(WEIGHTS)
    assert fusion["contribution_target_grade"] == "Class A"
    for grade, support in result.analysis["weighted_scores"].items():
        sources = fusion["per_source_class_contributions"]
        assert sum(source[grade] for source in sources.values()) == pytest.approx(support)
        assert sources["model2"][grade] == pytest.approx(.7 * fusion["model2_class_probabilities"][grade])
        assert sum(fusion["features"][family]["class_support_delta"][grade] for family in FAMILIES) == pytest.approx(
            support - fusion["model2_class_probabilities"][grade])
    for family in FAMILIES:
        contribution = fusion["features"][family]["weighted_class_contributions"]
        assert contribution["Class A"] > 0
        assert sum(contribution.values()) == pytest.approx(WEIGHTS[family])


@pytest.mark.parametrize("provenance", [None, "invalid review", 7])
def test_malformed_optional_review_withholds_features_and_preserves_model_grade(native_case, provenance):
    quality, row, save, analyze = native_case
    original = analyze()
    calibrate_control(quality, original, dict.fromkeys(FAMILIES, "Class B"))
    row["fusion_validation"]["validation_provenance"] = provenance
    save(row)
    result = analyze()
    fusion = result.analysis["feature_fusion"]["decision_fusion"]
    assert result.quality == original.quality == "Class A"
    assert fusion["mode"] == "model2_only"
    assert not any(entry["used_for_grading"] for entry in fusion["features"].values())
    assert result.analysis["fish_geometry"]["used_for_grading"] is False
