"""Distinct required anatomy is necessary even when the Tail is optional."""
import numpy as np
import pytest

from src.inference.association import ParentAnchor, associate_parts_to_parents, required_pair_geometry
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection


def part(class_id, box):
    return PartDetection.from_source_class(class_id, .9, box)


def grade(rows):
    engine = WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False))
    ambiguous = any(row.status == "AMBIGUOUS" and row.part.region in {"Head", "Body"} for row in rows)
    return engine.evaluate(1, np.full((100, 220, 3), 90, np.uint8),
        [row.part for row in rows if row.status == "ASSIGNED" and row.track_id == 1],
        stabilize=False, frame_id="required-pair", frame_quality={"association_ambiguous": ambiguous})


@pytest.mark.parametrize("tail", [False, True])
def test_same_native_box_cannot_count_as_both_required_head_and_body(tail):
    evidence = [part(1, (35, 25, 75, 65)), part(0, (35, 25, 75, 65))]
    if tail:
        evidence.append(part(2, (160, 30, 185, 60)))
    rows = associate_parts_to_parents(evidence, [ParentAnchor(1, (0, 0, 200, 80))])
    required = [row for row in rows if row.part.region in {"Head", "Body"}]
    assert all(row.status == "AMBIGUOUS" for row in required)
    assert all(row.reason == "required_anatomical_group_inconsistent" for row in required)
    assert all(row.ambiguous_track_ids == (1,) for row in required)
    result = grade(rows)
    assert result.final_grade is None
    assert "UG_ASSOCIATION_AMBIGUOUS" in result.reason_codes
    assert tuple(row.part for row in rows) == tuple(evidence)


def test_exactly_concentric_boxes_do_not_establish_two_independent_required_parts():
    rows = associate_parts_to_parents([part(1, (40, 30, 60, 50)), part(0, (20, 20, 80, 60))],
                                     [ParentAnchor(1, (0, 0, 200, 80))])
    assert all(row.status == "AMBIGUOUS" for row in rows)
    assert grade(rows).final_grade is None


@pytest.mark.parametrize("tail", [False, True])
def test_required_parts_disjoint_across_a_reliable_axis_are_withheld(tail):
    evidence = [part(1, (15, 10, 40, 25)), part(0, (70, 40, 145, 65))]
    if tail:
        evidence.append(part(2, (165, 40, 190, 65)))
    parent = ParentAnchor(1, (0, 0, 200, 80), orientation=(1, 0), orientation_reliable=True)
    rows = associate_parts_to_parents(evidence, [parent])
    assert all(row.status == "AMBIGUOUS" for row in rows if row.part.region in {"Head", "Body"})
    assert grade(rows).final_grade is None


def test_unknown_axis_does_not_turn_a_diagonal_pair_into_a_conflict():
    evidence = [part(1, (15, 10, 40, 25)), part(0, (70, 40, 145, 65))]
    parent = ParentAnchor(1, (0, 0, 200, 80), orientation=(1, 0), orientation_reliable=False)
    rows = associate_parts_to_parents(evidence, [parent])
    assert all(row.status == "ASSIGNED" for row in rows)
    assert grade(rows).final_grade == "Class A"


def test_ordinary_overlap_with_distinct_centers_preserves_the_existing_grade():
    # No new overlap, center-distance or confidence threshold is introduced.
    evidence = [part(1, (40, 30, 60, 50)), part(0, (35, 25, 75, 65))]
    rows = associate_parts_to_parents(evidence, [ParentAnchor(1, (0, 0, 200, 80))])
    assert all(row.status == "ASSIGNED" for row in rows)
    assert grade(rows).final_grade == "Class A"


def test_required_pair_conflict_is_local_to_the_affected_parent():
    evidence = [part(1, (35, 25, 75, 65)), part(0, (35, 25, 75, 65)),
                part(1, (255, 25, 285, 55)), part(0, (310, 25, 375, 65))]
    rows = associate_parts_to_parents(evidence, [ParentAnchor(1, (0, 0, 200, 80)),
                                                ParentAnchor(2, (230, 0, 430, 80))])
    assert all(row.status == "AMBIGUOUS" for row in rows[:2])
    assert all(row.status == "ASSIGNED" and row.track_id == 2 for row in rows[2:])


@pytest.mark.parametrize("axis", [(1, 0), (100, 0), (-1, 0)])
def test_shared_pair_check_is_independent_of_reliable_axis_scale_and_direction(axis):
    checks = required_pair_geometry((15, 10, 40, 25), (70, 40, 145, 65), reliable_axis=axis)
    assert checks["head_body_centers_coincident"] is False
    assert checks["head_body_axis_overlap"] is False
    assert checks["required_pair_inconsistent"] is True


@pytest.mark.parametrize("axis", [None, (0, 0), (float("nan"), 0)])
def test_shared_pair_check_does_not_guess_a_missing_or_invalid_axis(axis):
    checks = required_pair_geometry((15, 10, 40, 25), (70, 40, 145, 65), reliable_axis=axis)
    assert checks["head_body_axis_overlap"] is None
    assert checks["required_pair_inconsistent"] is False
