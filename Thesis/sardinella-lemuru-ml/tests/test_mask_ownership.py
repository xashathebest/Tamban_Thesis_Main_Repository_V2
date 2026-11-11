"""Experimental masks never establish biological ownership by themselves."""
from copy import deepcopy
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.mask_ownership import (
    MaskOwnershipConfig, body_support_mask, shadow_mask_associations,
    trusted_prompt_points, validate_candidate_masks,
)
from src.inference.part_types import PartDetection


SHAPE = (120, 640)
PARENT = ParentAnchor(1, (20, 30, 280, 90))


def fish(center=(150, 60), axes=(120, 22)):
    mask = np.zeros(SHAPE, np.uint8)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 1, -1)
    return mask.astype(bool)


def parts(parent=1):
    shift = 0 if parent == 1 else 320
    return [PartDetection.from_source_class(0, .9, (90 + shift, 38, 215 + shift, 82)),
            PartDetection.from_source_class(1, .8, (30 + shift, 47, 75 + shift, 73))]


def assigned(parent=1):
    return [SimpleNamespace(part=p, status="ASSIGNED", track_id=parent) for p in parts(parent)]


def candidate(mask=None, **extra):
    return {"mask": fish() if mask is None else mask, "score": .999, "parent_id": 1,
            "bbox_global": PARENT.bbox, "provenance": {"frame_key": "frame-a"}, **extra}


def validate(value, *, parents=(PARENT,), associations=None, all_parts=None):
    return validate_candidate_masks({1: value}, parents, parts() if all_parts is None else all_parts,
                                    associations=assigned() if associations is None else associations,
                                    frame_shape=SHAPE, expected_frame_key="frame-a")[1]


def trusted(mask, parent=1, region="Body", **extra):
    return {"mask": mask, "parent_track_id": parent, "region": region,
            "ownership_validated": True, "mask_validated": True, "orientation_reliable": True,
            "coordinate_space": "original_frame", "validation_provenance": "Reviewed fixture pixels", **extra}


@pytest.mark.parametrize("score", [0., .1, .999, 1., None, float("nan")])
def test_mask_score_cannot_approve_ownership_or_grading(score):
    value = candidate(score=score)
    before = value["mask"].copy()
    result = validate(value)
    assert result["status"] == "checks_passed_unvalidated"
    assert result["engineering_checks_passed"]
    for key in ("ownership_validated", "approved_for_grading", "measurement_validated", "mask_validated_for_cracks"):
        assert result[key] is False
    assert np.array_equal(value["mask"], before)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mask", [np.zeros(SHAPE, bool), np.ones((10, 20), bool),
                                  np.zeros(SHAPE, float), np.full(SHAPE, 127, np.uint8), None])
def test_invalid_empty_or_nonbinary_masks_are_unavailable(mask):
    value = candidate()
    value["mask"] = mask
    result = validate(value)
    assert result["status"] == "unavailable"
    assert not result["engineering_checks_passed"]


def test_unavailable_backend_preserves_explicit_reason():
    result = validate(candidate(status="unavailable", reason="Dependency unavailable"))
    assert result["status"] == "unavailable"
    assert result["backend_reason"] == "Dependency unavailable"


@pytest.mark.parametrize("extra,reason", [
    ({"parent_id": 2}, "candidate_parent_identity_mismatch"),
    ({"bbox_global": (21, 30, 280, 90)}, "candidate_prompt_box_mismatch"),
    ({"provenance": {"frame_key": "frame-b"}}, "candidate_frame_identity_mismatch"),
])
def test_reused_masks_cannot_cross_parent_detection_or_frame_identity(extra, reason):
    result = validate(candidate(**extra))
    assert reason in result["reasons"]
    assert not result["mask_geometry_checks_passed"]


def test_missing_required_head_is_not_physical_absence_or_mask_validation():
    from src.inference.mask_ownership import head_integrity_mask_eligibility
    result = validate(candidate(), associations=assigned()[:1])
    assert result["status"] == "ambiguous"
    assert "required_head_evidence_unavailable" in result["reasons"]
    assert result["mask_geometry_checks_passed"]
    assert not result["engineering_checks_passed"]
    eligibility = head_integrity_mask_eligibility(result)
    assert eligibility["eligible"] is True
    assert eligibility["engineering_checks_passed"] is False
    assert eligibility["head_detection_required"] is False


def test_ambiguous_required_parts_remain_unresolved():
    rows = assigned()
    rows[1] = SimpleNamespace(part=parts()[1], status="AMBIGUOUS", track_id=None, ambiguous_track_ids=(1, 2))
    result = validate(candidate(), associations=rows)
    assert "required_anatomical_ownership_ambiguous" in result["reasons"]
    assert not result["approved_for_grading"]


def test_mask_omitting_visible_head_is_withheld():
    mask = fish()
    mask[:, :85] = False
    result = validate(candidate(mask))
    assert "candidate_omits_detected_head_region" in result["reasons"]


def test_optional_tail_is_not_required_for_engineering_checks():
    result = validate(candidate())
    assert result["engineering_checks_passed"]
    assert result["required_parts"] == ["Body", "Head"]


def test_fragments_are_not_silently_reduced_to_the_largest_component():
    mask = fish()
    cv2.circle(mask.view(np.uint8), (290, 60), 8, 1, -1)
    before = mask.copy()
    result = validate(candidate(mask))
    assert "fragmented_or_merged_foreground_components" in result["reasons"]
    assert np.array_equal(mask, before)
    assert result["metrics"]["component_count"] == 2


def test_implausible_holes_are_reported():
    mask = fish()
    cv2.ellipse(mask.view(np.uint8), (150, 60), (50, 10), 0, 0, 360, 0, -1)
    assert "implausible_silhouette_holes" in validate(candidate(mask))["reasons"]


def test_frame_clipping_prevents_reliable_silhouette_claims():
    mask = fish(center=(20, 60))
    parent = ParentAnchor(1, (0, 30, 150, 90))
    result = validate(candidate(mask, bbox_global=parent.bbox), parents=(parent,))
    assert "mask_touches_frame_boundary" in result["reasons"]
    assert "parent_touches_frame_boundary" in result["reasons"]


def test_neighbor_exclusive_foreground_is_rejected():
    mask = fish() | fish(center=(470, 60))
    neighbor = ParentAnchor(2, (340, 30, 600, 90))
    result = validate(candidate(mask), parents=(PARENT, neighbor))
    assert "foreground_in_neighbor_exclusive_region" in result["reasons"]
    assert result["conflicting_parent_ids"] == [2]


def test_identical_candidate_masks_conflict_even_with_perfect_model_scores():
    parents = (PARENT, ParentAnchor(2, PARENT.bbox))
    candidates = {1: candidate(), 2: candidate(parent_id=2)}
    result = validate_candidate_masks(candidates, parents, parts(), associations=assigned(), frame_shape=SHAPE)
    for owner in (1, 2):
        assert "overlapping_mask_ownership_conflict" in result[owner]["reasons"]
        assert not result[owner]["mask_geometry_checks_passed"]


def test_neighbor_intersection_diagnostics_preserve_pixels_and_overlap_gates():
    from src.inference.mask_ownership import head_integrity_mask_eligibility
    parents = (PARENT, ParentAnchor(2, PARENT.bbox))
    shared = fish()
    before = shared.copy()
    candidates = {1: candidate(shared), 2: candidate(shared, parent_id=2)}
    result = validate_candidate_masks(candidates, parents, parts(), associations=assigned(), frame_shape=SHAPE)
    for owner, neighbor in ((1, 2), (2, 1)):
        metrics = result[owner]["metrics"]
        overlap = metrics["neighbor_mask_intersections"][str(neighbor)]
        assert overlap["intersection_pixels"] == int(shared.sum())
        assert overlap["owner_intersection_fraction"] == 1.0
        assert overlap["neighbor_intersection_fraction"] == 1.0
        assert overlap["pair_overlap_check_passed"] is False
        assert overlap["shared_pixels_reassigned"] is False
        eligibility = head_integrity_mask_eligibility(result[owner])
        assert eligibility["eligible"] is False
        assert eligibility["withheld_category"] == "overlap_or_contamination"
        assert eligibility["ownership_metrics"]["neighbor_mask_intersections"] == metrics["neighbor_mask_intersections"]
    assert np.array_equal(shared, before)


def test_neighbor_exclusive_region_diagnostics_explain_existing_guard():
    mask = fish() | fish(center=(470, 60))
    neighbor = ParentAnchor(2, (340, 30, 600, 90))
    result = validate(candidate(mask), parents=(PARENT, neighbor))
    check = result["metrics"]["neighbor_box_support"]["2"]
    assert check["foreground_inside_neighbor_exclusive_pixels"] > 0
    assert check["neighbor_exclusive_foreground_fraction"] > MaskOwnershipConfig().maximum_neighbor_exclusive_fraction
    assert check["exclusive_region_check_passed"] is False


def test_neighbor_head_inside_own_box_still_contaminates_candidate():
    neighbor_head = SimpleNamespace(part=parts()[1], status="ASSIGNED", track_id=2)
    result = validate(candidate(), associations=assigned() + [neighbor_head])
    assert "candidate_contains_neighbor_anatomical_evidence" in result["reasons"]
    assert not result["engineering_checks_passed"]


def test_box_containment_and_high_score_do_not_replace_anatomical_evidence():
    result = validate(candidate(), associations=[], all_parts=[])
    assert result["status"] == "ambiguous"
    assert not result["ownership_validated"]


@pytest.mark.parametrize("bad", [float("nan"), -.1, 1.01, True])
def test_engineering_configuration_is_explicit_and_validated(bad):
    with pytest.raises(ValueError):
        MaskOwnershipConfig(maximum_pair_overlap_fraction=bad)


def test_no_fish_is_an_empty_batch_not_a_phantom_identity():
    assert validate_candidate_masks({}, (), frame_shape=SHAPE) == {}
    assert validate_candidate_masks({}, ()) == {}


def test_duplicate_parent_ids_are_programming_errors():
    with pytest.raises(ValueError, match="unique"):
        validate_candidate_masks({}, (PARENT, PARENT), frame_shape=SHAPE)


def test_normal_detector_boxes_do_not_generate_point_prompts():
    assert trusted_prompt_points(1, [part.to_dict() for part in parts()], SHAPE)["point_coords"] == []


@pytest.mark.parametrize("override", [{"orientation_reliable": False}, {"ownership_validated": False},
                                      {"mask_validated": False}, {"coordinate_space": "crop_local"},
                                      {"validation_provenance": "  "}, {"validation_provenance": True}])
def test_uncertain_anatomical_support_cannot_create_prompt_points(override):
    result = trusted_prompt_points(1, [trusted(fish(), **override)], SHAPE)
    assert result["point_coords"] == []


def test_reviewed_points_are_inside_explicit_owned_pixels_not_box_centers():
    own = fish()
    other = fish(center=(470, 60))
    result = trusted_prompt_points(1, [trusted(own), trusted(other, parent=2)], SHAPE)
    assert result["point_labels"] == [1, 0]
    for (x, y), label in zip(result["point_coords"], result["point_labels"]):
        assert (own if label else other)[y, x]
    assert not result["invented_from_boxes"]


def test_conflicting_reviewed_pixels_never_produce_contradictory_prompts():
    result = trusted_prompt_points(1, [trusted(fish()), trusted(fish(), parent=2)], SHAPE)
    assert result["point_coords"] == result["point_labels"] == []


def test_body_box_alone_never_becomes_a_validated_crack_mask():
    mask, provenance = body_support_mask(1, candidate(), validate(candidate()), [parts()[0].to_dict()], SHAPE)
    assert mask is None and provenance["validated"] is False


def test_reviewed_body_pixels_are_intersected_without_enlargement():
    body = np.zeros(SHAPE, bool)
    body[47:74, 95:210] = True
    raw = body.copy()
    mask, provenance = body_support_mask(1, candidate(), validate(candidate()), [trusted(body)], SHAPE)
    assert np.array_equal(mask, body)
    assert np.array_equal(body, raw)
    assert provenance["source"] == "reviewed_body_mask_intersection"
    assert not mask.flags.writeable


def test_candidate_omitting_reviewed_body_is_withheld():
    body = np.zeros(SHAPE, bool)
    body[47:74, 95:210] = True
    cut = fish()
    cut[:, 150:] = False
    mask, provenance = body_support_mask(1, candidate(cut), {"engineering_checks_passed": True}, [trusted(body)], SHAPE)
    assert mask is None and provenance["retained_fraction"] < .95


def test_shadow_proposals_keep_grade_inputs_and_confidence_unchanged():
    candidates = {1: candidate()}
    ownership = validate_candidate_masks(candidates, (PARENT,), parts(), associations=assigned(), frame_shape=SHAPE)
    original_parts = [p.to_dict() for p in parts()]
    original_checks = deepcopy(ownership)
    result = shadow_mask_associations(candidates, ownership, (PARENT,), parts())
    assert result["parents"][1]["required_regions_available"]
    assert result["parents"][1]["effective_weights_if_validated"] == {"Body": .625, "Head": .375}
    assert all(row["status"] == "PROPOSED" and row["proposed_track_id"] == 1 for row in result["parts"])
    assert [p.to_dict() for p in parts()] == original_parts
    assert ownership == original_checks
    assert result["applied_to_grading"] is False
    assert result["ownership_validated"] is False


def test_shadow_does_not_fill_required_parts_when_masks_conflict():
    parent2 = ParentAnchor(2, PARENT.bbox)
    candidates = {1: candidate(), 2: candidate(parent_id=2)}
    ownership = validate_candidate_masks(candidates, (PARENT, parent2), parts(), associations=assigned(), frame_shape=SHAPE)
    result = shadow_mask_associations(candidates, ownership, (PARENT, parent2), parts())
    assert all(row["status"] == "UNASSIGNED" for row in result["parts"])
    assert result["parents"][1]["evidence_status"] == "Ungraded"


def test_shadow_does_not_use_a_mask_covering_neighbor_anatomical_evidence():
    rows = assigned() + [SimpleNamespace(part=parts()[1], status="ASSIGNED", track_id=2)]
    ownership = {1: validate(candidate(), associations=rows)}
    result = shadow_mask_associations({1: candidate()}, ownership, (PARENT,), parts())
    assert all(row["status"] == "UNASSIGNED" for row in result["parts"])


def test_shadow_deduplicates_one_region_per_parent():
    candidates = {1: candidate()}
    ownership = {1: validate(candidate())}
    detections = parts() + [PartDetection.from_source_class(3, .5, (100, 40, 200, 80))]
    result = shadow_mask_associations(candidates, ownership, (PARENT,), detections)
    assert sum(row["status"] == "PROPOSED" and row["region"] == "Body" for row in result["parts"]) == 1
    assert result["parts"][-1]["reason"] == "duplicate_region_for_parent"
