"""Guard the validation harness against false success or stale neural replay."""
from copy import deepcopy
import hashlib

import numpy as np
import pytest

from src.evaluation.validate_runtime_e2e import FrozenSamSession, audit_payload, part_key, verify_graded_arithmetic


def evidence():
    part = {"source_class_id": 0, "confidence": .9, "region": "Body", "bbox": [20., 20., 70., 40.]}
    association = {"parts": [{"status": "ASSIGNED", "track_id": 1, "part": deepcopy(part)}]}
    payload = {"inspection_source": {"frame_id": "source-1"}, "fish": [{"id": 1, "quality": "Ungraded", "parts": [deepcopy(part)],
        "analysis": {"quality_inference": {"association": association}, "model2_debug": {"raw_detections": [deepcopy(part)]},
            "body_width": {"score_contributed": False}, "feature_fusion": {"original_grade": "Ungraded", "final_grade": "Ungraded", "contributions_applied": []},
            "segmentation": {"frame_id": "source-1", "ownership": {"approved_for_grading": False, "ownership_validated": False}}}}]}
    return payload, {"shape": [80, 120, 3], "parts": [part], "raw_parts": [part]}


def test_harness_does_not_call_coverage_grading_accuracy():
    payload, frozen = evidence()
    result = audit_payload(payload, frozen)
    assert result["violations"] == []
    assert result["grading_accuracy"] is None
    assert result["false_association_rate"] is None
    assert result["independent_ground_truth_available"] is False
    assert result["ungraded"][0]["missing_required"] == ["Head"]


def test_harness_detects_the_original_crop_coordinate_loss():
    payload, frozen = evidence()
    payload["fish"][0]["parts"][0]["bbox"][0] += 1
    codes = {v["code"] for v in audit_payload(payload, frozen)["violations"]}
    assert "accepted_native_box_changed_by_crop_or_serialization" in codes


def test_harness_detects_raw_native_boxes_lost_by_crop_debug_filtering():
    payload, frozen = evidence()
    payload["fish"][0]["analysis"]["model2_debug"]["raw_detections"] = []
    assert "native_raw_trace_lost_or_changed" in {v["code"] for v in audit_payload(payload, frozen)["violations"]}


def test_harness_withholds_automatic_mask_and_width_approval_claims():
    payload, frozen = evidence()
    analysis = payload["fish"][0]["analysis"]
    analysis["segmentation"]["ownership"]["ownership_validated"] = True
    analysis["body_width"]["score_contributed"] = True
    codes = {v["code"] for v in audit_payload(payload, frozen)["violations"]}
    assert {"automatic_mask_claimed_independent_validation", "unexpected_uncalibrated_width_contribution"}.issubset(codes)


def session_source():
    image = np.zeros((20, 40, 3), np.uint8)
    candidate = {"provenance": {"original_bbox_global": [1., 2., 30., 15.], "frame_key": "frame-key"}}
    frozen = {"pixel_sha256": hashlib.sha256(memoryview(image)).hexdigest(), "candidates": {"1": candidate}}
    from types import SimpleNamespace
    return image, SimpleNamespace(frozen=frozen, masks={"1": np.ones((20, 40), bool)})


def test_frozen_masks_are_bound_to_exact_source_pixels_and_frame_identity():
    image, service = session_source()
    session = FrozenSamSession(service, image, "frame-key")
    row = session.predict(1, (1, 2, 30, 15))
    assert row["frozen_neural_replay"] is True
    assert session.diagnostics()["actual_encoder_forward_calls"] == 0
    with pytest.raises(ValueError, match="point prompts"):
        session.predict(1, (1, 2, 30, 15), point_coords=[[4, 4]], point_labels=[1])
    image[0, 0, 0] = 1
    with pytest.raises(ValueError, match="different pixels"):
        FrozenSamSession(service, image, "frame-key")


@pytest.mark.parametrize("frame,box,match", [
    ("new-frame", (1, 2, 30, 15), "frame identity"),
    ("frame-key", (2, 2, 30, 15), "parent prompts"),
])
def test_frozen_masks_refuse_changed_parent_or_frame_even_with_same_pixels(frame, box, match):
    image, service = session_source()
    with pytest.raises(ValueError, match=match):
        FrozenSamSession(service, image, frame).predict(1, box)


def test_exact_part_identity_does_not_merge_nearby_native_detections():
    _, frozen = evidence()
    first = frozen["parts"][0]
    second = deepcopy(first)
    second["bbox"][0] += .0001
    assert part_key(first) != part_key(second)


def test_weighted_policy_compliance_does_not_claim_expert_grading_accuracy():
    payload, _ = evidence()
    fish = payload["fish"][0]
    fish.update(quality="Class B", quality_confidence=.8625)
    body = fish["analysis"]["quality_inference"]["association"]["parts"][0]
    body["part"]["grade"] = "Class B"
    head = deepcopy(body)
    head["part"].update(region="Head", source_class_id=4, confidence=.8)
    fish["analysis"]["quality_inference"]["association"]["parts"].append(head)
    fish["analysis"].update(effective_weights={"Body": .625, "Head": .375, "Tail": 0},
                            weighted_scores={"Class A": 0., "Class B": .8625, "Class C": 0., "Rejected": 0.})
    result = verify_graded_arithmetic(payload)
    assert result["graded_verdicts_checked"] == 1
    assert result["violations"] == []
    assert "not expert-reference grading accuracy" in result["scope"]
    fish["analysis"]["effective_weights"]["Body"] = .5
    assert verify_graded_arithmetic(payload)["violations"][0]["code"] == "incorrect_50_30_20_or_optional_tail_weights"
