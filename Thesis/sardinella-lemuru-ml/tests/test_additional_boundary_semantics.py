"""Crop contact cannot establish that a fish leaves its original image."""
import numpy as np
import pytest

from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection


def evaluate(flags, *, complete=False, stabilize=False, frame_id=1, engine=None):
    engine = engine or WeightedGradingEngine(GradingConfig(
        grading_mode="tail_optional_v1", image_diagnostics_enabled=False,
        minimum_track_observations=1))
    parts = [PartDetection.from_source_class(0, .9, (20, 10, 50, 30))]
    if complete:
        parts.append(PartDetection.from_source_class(1, .8, (5, 12, 18, 28)))
    return engine.evaluate(1, np.ones((40, 100, 3), np.uint8), parts,
                           stabilize=stabilize, frame_id=frame_id, frame_quality=flags)


@pytest.mark.parametrize("flags", [
    {"parent_crop_clipped": True}, {"crop_clipped": True},
    {"usable": False, "reasons": ["crop_clipped"]},
    {"usable": False, "reasons": ["parent_crop_clipped"]},
    {"usable": False, "reasons": ["part_roi_clipped"]},
])
def test_crop_only_clipping_keeps_missing_required_ug_without_claiming_outside_image(flags):
    result = evaluate(flags)
    assert result.final_grade is None
    assert "UG_MISSING_PART_EVIDENCE" in result.reason_codes
    assert "UG_OUT_OF_FRAME" not in result.reason_codes
    assert result.frame_quality["out_of_frame"] is False
    assert result.part_results["Head"]["visibility_state"] == "PARENT_CROP_CLIPPED"


@pytest.mark.parametrize("flags", [
    {"parent_frame_clipped": True}, {"frame_clipped": True}, {"out_of_frame": True},
    {"usable": False, "reasons": ["frame_clipped"]},
    {"usable": False, "reasons": ["bbox_outside_frame"]},
])
def test_original_image_clipping_remains_conservative(flags):
    result = evaluate(flags)
    assert result.final_grade is None
    assert "UG_OUT_OF_FRAME" in result.reason_codes
    assert result.frame_quality["out_of_frame"] is True
    assert result.part_results["Head"]["visibility_state"] == "PARENT_FRAME_CLIPPED"


@pytest.mark.parametrize("native_clipped", [False, None])
def test_explicit_frame_evidence_overrides_legacy_bbox_contact_flag(native_clipped):
    result = evaluate({"frame_clipped": True, "parent_frame_clipped": native_clipped,
                       "parent_bbox_frame_contact": True})
    assert result.frame_quality["out_of_frame"] is False
    assert "UG_OUT_OF_FRAME" not in result.reason_codes
    assert result.part_results["Head"]["visibility_state"] == "NOT_DETECTED"


@pytest.mark.parametrize("flags", [{"parent_crop_clipped": True}, {"parent_frame_clipped": True}])
def test_boundary_diagnostics_do_not_change_complete_required_part_weights(flags):
    result = evaluate(flags, complete=True)
    assert result.final_grade == "Class A"
    assert result.effective_weights == pytest.approx({"Head": .375, "Body": .625, "Tail": 0.0})
    assert result.weighted_scores["Class A"] == pytest.approx(.8625)
    assert result.part_results["Head"]["visibility_state"] == "PRESENT"


def test_live_crop_clipping_diagnostic_clears_without_persisting_out_of_frame():
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1",
        image_diagnostics_enabled=False, minimum_track_observations=1))
    first = evaluate({"parent_crop_clipped": True}, stabilize=True, frame_id=1, engine=engine)
    assert first.frame_quality["out_of_frame"] is False
    recovered = evaluate({}, complete=True, stabilize=True, frame_id=2, engine=engine)
    assert recovered.frame_quality["out_of_frame"] is False
    assert recovered.final_grade == "Class A"
