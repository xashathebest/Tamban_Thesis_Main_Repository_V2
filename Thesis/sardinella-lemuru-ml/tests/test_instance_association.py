"""Native instance pixels may resolve ownership without changing evidence gates."""

from dataclasses import replace

import numpy as np
import pytest

from src.inference.association import AssociationConfig, ParentAnchor, associate_parts_to_parents
from src.inference.instance_association import refine_instance_associations
from src.inference.mask_ownership import validate_candidate_masks
from src.inference.part_types import PartDetection


SHAPE = (220, 320)
FRAME_KEY = "independent-instance-test-frame"


def _candidate(parent, rectangle, shape=SHAPE):
    mask = np.zeros(shape, dtype=bool)
    x1, y1, x2, y2 = rectangle
    mask[y1:y2, x1:x2] = True
    return {"mask": mask, "parent_id": parent.track_id, "bbox_global": parent.bbox,
            "provenance": {"backend": "mobilesam_experimental", "source": "mobilesam_box_prompt_candidate",
                           "frame_key": FRAME_KEY, "parent_id": parent.track_id,
                           "coordinate_space": "original_frame", "mask_shape": list(shape),
                           "original_bbox_global": list(parent.bbox), "prompt_bbox_global": list(parent.bbox)}}


def _refine(parents, parts, candidates, *, baseline=None, protected=()):
    baseline = tuple(baseline) if baseline is not None else associate_parts_to_parents(parts, parents)
    ownership = validate_candidate_masks(candidates, parents, parts, associations=baseline,
                                         frame_shape=SHAPE, expected_frame_key=FRAME_KEY)
    return baseline, ownership, refine_instance_associations(
        candidates, ownership, parents, parts, baseline, SHAPE, FRAME_KEY, protected_parent_ids=protected)


def test_measured_mask_support_resolves_body_just_below_unchanged_score_gate():
    parent = ParentAnchor(1, (40, 40, 280, 140), .95)
    body = PartDetection.from_source_class(0, .95, (30, 70, 130, 110))
    candidates = {1: _candidate(parent, (45, 70, 250, 111))}
    baseline, ownership, (refined, diagnostics) = _refine([parent], [body], candidates)
    assert baseline[0].status == "UNASSIGNED"
    assert baseline[0].reason == "association_score_below_threshold"
    assert ownership[1]["mask_geometry_checks_passed"] is True
    assert "required_body_evidence_unavailable" in ownership[1]["reasons"]
    assert refined[0].status == "ASSIGNED" and refined[0].track_id == 1
    candidate = refined[0].candidates[0]
    assert candidate.mask_support == pytest.approx(.85)
    assert candidate.score == pytest.approx(baseline[0].candidates[0].score + .22 * .85)
    assert candidate.score >= AssociationConfig().minimum_association_score
    assert diagnostics["minimum_association_score"] == .70
    assert diagnostics["minimum_association_margin"] == .12
    assert diagnostics["ownership_validated"] is False
    assert diagnostics["parts"][0]["native_mask_support"][1]["exclusive_intersection_pixels"] == 3400


def test_disjoint_masks_resolve_identical_parent_boxes_using_real_roi_overlap():
    parents = [ParentAnchor(1, (40, 60, 280, 180), .95), ParentAnchor(2, (40, 60, 280, 180), .95)]
    body = PartDetection.from_source_class(0, .95, (70, 80, 250, 101))
    candidates = {1: _candidate(parents[0], (60, 80, 261, 101)),
                  2: _candidate(parents[1], (60, 140, 261, 161))}
    baseline, _, (refined, diagnostics) = _refine(parents, [body], candidates)
    assert baseline[0].status == "AMBIGUOUS"
    assert refined[0].status == "ASSIGNED" and refined[0].track_id == 1
    assert refined[0].margin == pytest.approx(.22)
    assert diagnostics["parts"][0]["native_mask_support"][1]["measured_mask_support"] == 1
    assert diagnostics["parts"][0]["native_mask_support"][2]["measured_mask_support"] == 0


def test_shared_mask_pixels_never_establish_either_parents_ownership():
    parents = [ParentAnchor(1, (40, 60, 280, 180), .95), ParentAnchor(2, (40, 60, 280, 180), .95)]
    body = PartDetection.from_source_class(0, .95, (70, 109, 250, 111))
    candidates = {1: _candidate(parents[0], (60, 90, 261, 111)),
                  2: _candidate(parents[1], (60, 109, 261, 130))}
    baseline, ownership, (refined, diagnostics) = _refine(parents, [body], candidates)
    assert all(record["mask_geometry_checks_passed"] for record in ownership.values())
    assert baseline[0].status == refined[0].status == "AMBIGUOUS"
    assert refined[0].track_id is None
    assert all(row["applied_mask_support"] == 0 for row in diagnostics["parts"][0]["native_mask_support"].values())


def test_visible_body_can_be_associated_without_waiving_native_frame_clipping():
    parent = ParentAnchor(1, (40, 0, 280, 100), .95)
    body = PartDetection.from_source_class(0, .95, (30, 2, 130, 18))
    candidates = {1: _candidate(parent, (45, 0, 250, 21))}
    baseline, ownership, (refined, diagnostics) = _refine([parent], [body], candidates)
    assert baseline[0].status == "UNASSIGNED"
    assert ownership[1]["mask_geometry_checks_passed"] is False
    assert "mask_touches_frame_boundary" in ownership[1]["reasons"]
    assert refined[0].status == "ASSIGNED"
    assert diagnostics["applied"] is True
    assert "mask_touches_frame_boundary" in ownership[1]["reasons"]


@pytest.mark.parametrize("defect", ("frame", "parent", "provenance", "mask_shape"))
def test_unverified_native_source_does_not_supply_the_reserved_mask_score(defect):
    parent = ParentAnchor(1, (40, 40, 280, 140), .95)
    body = PartDetection.from_source_class(0, .95, (30, 70, 130, 110))
    candidate = _candidate(parent, (45, 70, 250, 111))
    if defect == "frame":
        candidate["provenance"]["frame_key"] = "another-frame"
    elif defect == "parent":
        candidate["provenance"]["parent_id"] = 2
    elif defect == "provenance":
        candidate["provenance"] = {}
    else:
        candidate["mask"] = candidate["mask"][:-1]
    baseline, _, (refined, diagnostics) = _refine([parent], [body], {1: candidate})
    assert refined == baseline
    assert diagnostics["applied"] is False
    assert diagnostics["status"] == "no_reliable_native_instance_support"


def test_existing_head_is_retained_and_duplicate_is_not_sent_to_a_neighbor_by_vacancy():
    parents = [ParentAnchor(1, (40, 60, 280, 180), .95), ParentAnchor(2, (40, 60, 280, 180), .95)]
    previous = PartDetection.from_source_class(1, .90, (70, 80, 95, 101))
    duplicate = PartDetection.from_source_class(4, .97, (72, 80, 97, 101))
    baseline = list(associate_parts_to_parents([previous, duplicate], parents))
    baseline[0] = replace(baseline[0], status="ASSIGNED", track_id=1,
                          confidence=baseline[0].candidates[0].score, margin=.2, reason=None)
    candidates = {1: _candidate(parents[0], (60, 80, 261, 101)),
                  2: _candidate(parents[1], (60, 140, 261, 161))}
    _, _, (refined, _) = _refine(parents, [previous, duplicate], candidates, baseline=baseline)
    assert refined[0] == baseline[0]
    assert refined[1].status == "UNASSIGNED" and refined[1].track_id is None
    assert not any(row.status == "ASSIGNED" and row.track_id == 2 for row in refined)


def test_reviewed_parent_does_not_receive_an_engineering_assignment():
    parent = ParentAnchor(1, (40, 40, 280, 140), .95)
    body = PartDetection.from_source_class(0, .95, (30, 70, 130, 110))
    candidates = {1: _candidate(parent, (45, 70, 250, 111))}
    baseline, _, (refined, diagnostics) = _refine([parent], [body], candidates, protected={1})
    assert refined == baseline
    assert diagnostics["protected_parent_ids"] == [1]


def test_postassociation_native_failure_rolls_back_the_supporting_mask(monkeypatch):
    import src.inference.instance_association as implementation
    parent = ParentAnchor(1, (40, 40, 280, 140), .95)
    body = PartDetection.from_source_class(0, .95, (30, 70, 130, 110))
    candidates = {1: _candidate(parent, (45, 70, 250, 111))}
    validate = implementation.validate_candidate_masks

    def failed_after_assignment(*args, **kwargs):
        records = validate(*args, **kwargs)
        if any(row.status == "ASSIGNED" for row in kwargs["associations"]):
            records[1]["mask_geometry_checks_passed"] = False
            records[1]["reasons"].append("candidate_contains_neighbor_anatomical_evidence")
        return records

    monkeypatch.setattr(implementation, "validate_candidate_masks", failed_after_assignment)
    baseline, _, (refined, diagnostics) = _refine([parent], [body], candidates)
    assert refined[0].status == baseline[0].status == "UNASSIGNED"
    assert diagnostics["refinement_iterations"] == 2
    assert "post_association_native_recheck_failed" in diagnostics["excluded_parent_masks"][1]
