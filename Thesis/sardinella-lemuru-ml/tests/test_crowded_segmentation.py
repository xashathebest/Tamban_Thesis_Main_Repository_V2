"""Prompt retries must resolve crowded ownership without changing mask pixels."""
from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np

from src.inference.association import ParentAnchor
from src.inference.crowded_segmentation import estimated_refinement_prompts, select_refined_candidates
from src.inference.mask_ownership import head_integrity_mask_eligibility, validate_candidate_masks
from src.inference.part_types import PartDetection


SHAPE = (140, 360)
PARENTS = (ParentAnchor(1, (10, 15, 320, 110)), ParentAnchor(2, (40, 30, 350, 125)))


def scene():
    masks = []
    for center in ((165, 45), (185, 95)):
        mask = np.zeros(SHAPE, np.uint8)
        cv2.ellipse(mask, center, (140, 14), 0, 0, 360, 1, -1)
        masks.append(mask.astype(bool))
    parts, rows = [], []
    for identity, shift in ((1, 0), (2, 50)):
        for class_id, box in ((0, (90, 33 + shift, 240, 57 + shift)),
                              (1, (40, 34 + shift, 70, 56 + shift))):
            part = PartDetection.from_source_class(class_id, .95, box)
            parts.append(part)
            rows.append(SimpleNamespace(part=part, status="ASSIGNED", track_id=identity))

    def candidates(values):
        return {parent.track_id: {"mask": mask, "parent_id": parent.track_id,
            "bbox_global": parent.bbox, "score": .99,
            "provenance": {"frame_key": "fixture"}}
            for parent, mask in zip(PARENTS, values)}

    merged = masks[0] | masks[1]
    return masks, parts, rows, candidates([merged, merged]), candidates(masks)


def test_refinement_points_are_unreviewed_interiors_and_use_both_labels():
    masks, parts, rows, initial, _ = scene()
    initial_before = {identity: candidate["mask"].copy() for identity, candidate in initial.items()}
    plans = estimated_refinement_prompts(initial, PARENTS, parts, associations=rows, frame_shape=SHAPE)
    for identity, plan in plans.items():
        assert plan["status"] == "planned"
        assert plan["estimated"] is True
        assert plan["ownership_validated"] is False
        assert plan["anatomical_truth_inferred"] is False
        assert set(plan["point_labels"]) == {0, 1}
        own, other = masks[identity - 1], masks[2 - identity]
        for point, label, evidence in zip(plan["point_coords"], plan["point_labels"], plan["point_evidence"]):
            x, y = point
            assert (own if label else other)[y, x]
            assert initial[identity]["mask"][y - 1:y + 2, x - 1:x + 2].all()
            assert evidence["reviewed"] is False
        assert np.array_equal(initial[identity]["mask"], initial_before[identity])


def test_identical_boxes_without_unique_parts_cannot_invent_points():
    _, _, _, initial, _ = scene()
    parents = (PARENTS[0], ParentAnchor(2, PARENTS[0].bbox))
    plans = estimated_refinement_prompts(initial, parents, associations=[], frame_shape=SHAPE)
    assert all(plan["status"] == "withheld" for plan in plans.values())
    assert all(plan["point_coords"] == [] for plan in plans.values())


def test_ambiguous_parts_cannot_supply_estimated_positive_points():
    _, parts, rows, initial, _ = scene()
    parents = (PARENTS[0], ParentAnchor(2, PARENTS[0].bbox))
    ambiguous = [SimpleNamespace(part=row.part, status="AMBIGUOUS", track_id=None,
                                 ambiguous_track_ids=(1, 2)) for row in rows]
    plans = estimated_refinement_prompts(initial, parents, parts, associations=ambiguous, frame_shape=SHAPE)
    assert all(plan["point_coords"] == [] for plan in plans.values())


def test_joint_fresh_predictions_can_resolve_overlapping_masks_with_unchanged_gates():
    _, parts, rows, initial, refined = scene()
    before = validate_candidate_masks(initial, PARENTS, parts, associations=rows, frame_shape=SHAPE)
    assert all(not head_integrity_mask_eligibility(row)["eligible"] for row in before.values())
    originals = {identity: candidate["mask"].copy() for identity, candidate in initial.items()}
    proposals = {identity: candidate["mask"].copy() for identity, candidate in refined.items()}
    selected, checked, diagnostics = select_refined_candidates(initial, refined, PARENTS, parts,
        associations=rows, frame_shape=SHAPE, expected_frame_key="fixture")
    assert diagnostics["selected_variant"] == "joint_refinement"
    assert diagnostics["selected_eligible_parent_ids"] == [1, 2]
    assert diagnostics["replaced_parent_ids"] == [1, 2]
    assert diagnostics["headless_geometry_used_for_selection"] is False
    for identity in (1, 2):
        assert selected[identity] is refined[identity]
        assert checked[identity]["mask_geometry_checks_passed"] is True
        assert np.array_equal(initial[identity]["mask"], originals[identity])
        assert np.array_equal(refined[identity]["mask"], proposals[identity])


def test_valid_initial_fish_are_frozen_and_never_lost_to_a_retry():
    masks, parts, rows, _, refined = scene()
    bad = dict(refined[2], mask=masks[0] | masks[1])
    selected, checked, report = select_refined_candidates(refined, {1: bad, 2: bad}, PARENTS, parts,
        associations=rows, frame_shape=SHAPE)
    assert report["protected_initial_eligible_parent_ids"] == [1, 2]
    assert report["replaced_parent_ids"] == []
    assert all(selected[identity] is refined[identity] for identity in (1, 2))
    assert all(head_integrity_mask_eligibility(row)["eligible"] for row in checked.values())


def test_retry_batch_that_contaminates_a_previously_eligible_neighbor_is_declined():
    masks, parts, rows, _, refined = scene()
    initial = {1: refined[1], 2: dict(refined[2], mask=None, status="unavailable")}
    bad = {2: dict(refined[2], mask=masks[0] | masks[1])}
    selected, _, report = select_refined_candidates(initial, bad, PARENTS, parts,
        associations=rows, frame_shape=SHAPE)
    assert report["protected_initial_eligible_parent_ids"] == [1]
    assert report["selected_variant"] == "initial"
    assert report["replaced_parent_ids"] == []
    assert all(attempt["preserves_initial_eligible_fish"] is False for attempt in report["attempts"])
    assert selected[1] is initial[1]


def test_unusable_or_wrong_identity_proposals_cannot_be_selected_over_valid_masks():
    _, parts, rows, _, refined = scene()
    invalid = {identity: dict(candidate, parent_id=99) for identity, candidate in refined.items()}
    selected, _, report = select_refined_candidates(refined, invalid, PARENTS, parts,
        associations=rows, frame_shape=SHAPE)
    assert report["selected_variant"] == "initial"
    assert all(selected[identity] is refined[identity] for identity in (1, 2))


def test_initial_eligible_fish_do_not_receive_unnecessary_prompt_retries():
    _, parts, rows, _, refined = scene()
    ownership = validate_candidate_masks(refined, PARENTS, parts, associations=rows, frame_shape=SHAPE)
    snapshot = deepcopy(ownership)
    plans = estimated_refinement_prompts(refined, PARENTS, parts, associations=rows,
        frame_shape=SHAPE, ownership=ownership)
    assert all(plan["status"] == "not_needed" for plan in plans.values())
    assert ownership == snapshot
