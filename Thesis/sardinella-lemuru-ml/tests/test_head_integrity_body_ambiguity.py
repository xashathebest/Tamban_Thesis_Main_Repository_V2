"""A neighbor's ambiguous Body ROI cannot replace per-fish Head evidence."""

import cv2
import numpy as np
import pytest

from test_crowded_head_integrity_pipeline import NativeService, fish, quality
from src.inference.association import ParentAnchor
from src.inference.mask_ownership import head_integrity_mask_eligibility
from src.inference.part_types import PartDetection
from src.inference.preprocessing import RuntimeMaskContext


def scene(monkeypatch, *, share_anterior=False, ambiguous_head=False):
    shape = (260, 340)
    silver = fish(shape, 65)
    brown = fish(shape, 175)
    # The lower fish has a visible, separately detected Head; the upper fish
    # has a flat, missing-Head endpoint. Parent rectangles deliberately coincide.
    cv2.ellipse(brown.view(np.uint8), (30, 175), (18, 12), 0, 0, 360, 1, -1)
    if share_anterior:
        brown[65, 30] = True
    native = {1: silver, 2: brown}
    service = NativeService(native)
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    frame = np.random.default_rng(31).integers(30, 220, (*shape, 3), dtype=np.uint8)
    parents = [ParentAnchor(identity, (10, 20, 300, 230), .99) for identity in (1, 2)]
    # Equal native support keeps this box ambiguous under the original .12
    # ownership margin. It must never be assigned merely to unlock grading.
    body = PartDetection.from_source_class(3, .9, (80, 50, 170, 190))
    head_box = (10, 50, 45, 190) if ambiguous_head else (10, 160, 45, 190)
    head = PartDetection.from_source_class(4, .95, head_box)
    context = RuntimeMaskContext(frame, frame_id="mixed-neighbors", backend="mobilesam_experimental")
    results = quality([body, head]).predict_full_frame(frame, parents, stabilize=False,
        frame_id="mixed-neighbors", mask_context=context)
    return results, context, native


def test_independent_head_review_preserves_ambiguous_body_and_neighbors_owned_head(monkeypatch):
    results, context, native = scene(monkeypatch)
    silver, brown = results[1][0], results[2][0]
    assert silver.quality == "Rejected", silver.analysis["head_integrity"]
    assert brown.quality != "Rejected"
    assert not any(part.region in {"Body", "Head"} for part in silver.parts)
    assert any(part.region == "Head" for part in brown.parts)
    assert not any(part.region == "Body" for part in brown.parts)
    report = silver.analysis["head_integrity"]
    assert report["body_association_status"]["preserved_for_quality_grading"] == "AMBIGUOUS"
    assert report["body_association_status"]["separate_from_head_integrity"] is True
    assert report["body_association_status"]["detector_body_assignment_created"] is False
    assert report["head_detection_status"]["accepted_count"] == 0
    assert not report["head_detection_status"]["foreign_head_intersects"]
    assert report["head_endpoint_ownership"]["anterior_shared_pixels"] == 0
    assert report["head_endpoint_ownership"]["clear"] is True
    assert report["failed_rejection_gates"] == []
    assert report["quality_grading_before_integrity"]["grade"] == "Ungraded"
    rows = silver.analysis["quality_inference"]["association"]["parts"]
    assert [row["status"] for row in rows if row["part"]["region"] == "Body"] == ["AMBIGUOUS"]
    for identity, mask in native.items():
        np.testing.assert_array_equal(context._experimental.candidates[identity]["mask"], mask)


def test_even_one_shared_anterior_pixel_blocks_body_only_independent_review(monkeypatch):
    results, context, _ = scene(monkeypatch, share_anterior=True)
    report = results[1][0].analysis["head_integrity"]
    assert results[1][0].analysis["final_grade"] == "Ungraded"
    assert context._experimental.ownership[1]["metrics"]["pair_overlap_fraction"]["2"] < .10
    assert report["head_endpoint_ownership"]["anterior_shared_pixels"] == 1
    assert not report["head_endpoint_ownership"]["clear"]
    assert not report["mask_eligibility"]["eligible"]
    assert report["decision_reason"] == "head_endpoint_not_independently_clear"


def test_head_ambiguity_is_never_waived_by_a_clear_mask_endpoint(monkeypatch):
    results, _, _ = scene(monkeypatch, ambiguous_head=True)
    report = results[1][0].analysis["head_integrity"]
    assert results[1][0].analysis["final_grade"] == "Ungraded"
    assert "Head" in report["mask_eligibility"]["ambiguous_anatomical_regions"]
    assert not report["body_association_status"]["separate_from_head_integrity"]
    assert not report["mask_eligibility"]["eligible"]


@pytest.mark.parametrize("regions,rows", [([], []), (["Body"], []), (["Head"], [
    {"region": "Head", "contending_parent_ids": [1, 2]}]), (["Body"], [
    {"region": "Body", "contending_parent_ids": [2, 3]}])])
def test_legacy_unknown_or_inconsistent_ambiguity_records_fail_closed(regions, rows):
    record = {"parent_id": 1, "mask_geometry_checks_passed": True, "conflicting_parent_ids": [],
        "reasons": ["required_head_evidence_unavailable", "required_body_evidence_unavailable",
                    "required_anatomical_ownership_ambiguous"],
        "ambiguous_anatomical_regions": regions, "anatomical_ownership_ambiguities": rows}
    report = head_integrity_mask_eligibility(record, geometric_body_supported=True, independent_head_endpoint=True)
    assert not report["eligible"]
    assert not report["body_ambiguity_separate_from_head_integrity"]


def test_isolated_silver_keeps_the_same_anatomical_rejection(monkeypatch):
    shape = (260, 340)
    native = {1: fish(shape, 65)}
    service = NativeService(native)
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    frame = np.random.default_rng(32).integers(30, 220, (*shape, 3), dtype=np.uint8)
    context = RuntimeMaskContext(frame, frame_id="isolated-silver", backend="mobilesam_experimental")
    result = quality([]).predict_full_frame(frame, [ParentAnchor(1, (10, 20, 300, 230), .99)],
        stabilize=False, frame_id="isolated-silver", mask_context=context)[1][0]
    assert result.quality == "Rejected"
    assert result.analysis["head_integrity"]["classification"] == "confirmed_absent"
