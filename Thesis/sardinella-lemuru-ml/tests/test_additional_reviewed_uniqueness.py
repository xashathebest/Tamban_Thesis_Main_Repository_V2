"""Reviewed labels cannot bypass one selected anatomical region per fish."""
import numpy as np
import pytest

from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.part_types import PartDetection
from src.inference.reviewed_features import refine_reviewed_associations


def part(class_id, box, confidence=.9):
    return PartDetection.from_source_class(class_id, confidence, box)


def review(parts, *, shape=(60, 230), pixels=None):
    return {"whole_mask": np.ones(shape, bool) if pixels is None else pixels,
            "part_ownership": [{"reviewed": True, "region": item.region,
                "source_class_id": item.source_class_id, "bbox": list(item.bbox)} for item in parts]}


@pytest.mark.parametrize("reverse", [False, True])
def test_two_reviewed_detections_for_one_fish_region_are_withheld(reverse):
    parts = [part(1, (10, 10, 25, 25)), part(4, (70, 10, 85, 25), .8)]
    if reverse:
        parts.reverse()
    rows = associate_parts_to_parents(parts, [ParentAnchor(2, (0, 0, 100, 50))])
    assert sum(row.status == "ASSIGNED" for row in rows) == 1
    refined = refine_reviewed_associations(rows, {2: review(parts)}, (60, 230))
    assert all(row.status == "AMBIGUOUS" and row.track_id is None for row in refined)
    assert all(row.reason == "reviewed_region_ownership_conflict" for row in refined)
    assert all(row.ambiguous_track_ids == (2,) and row.confidence is None for row in refined)
    assert [row.part for row in refined] == parts


def test_reviewed_claim_cannot_leave_an_unreviewed_head_assigned_to_the_same_parent():
    parts = [part(1, (10, 10, 25, 25), .8), part(4, (70, 10, 85, 25), .95)]
    rows = associate_parts_to_parents(parts, [ParentAnchor(2, (0, 0, 100, 50))])
    assert rows[1].status == "ASSIGNED"
    refined = refine_reviewed_associations(rows, {2: review(parts[:1])}, (60, 230))
    assert all(row.status == "AMBIGUOUS" for row in refined)
    assert all(row.reason == "reviewed_region_ownership_conflict" for row in refined)


def test_reviewed_distinct_regions_still_belong_to_the_same_parent():
    parts = [part(1, (10, 10, 25, 25)), part(0, (40, 10, 80, 35))]
    rows = associate_parts_to_parents(parts, [ParentAnchor(2, (0, 0, 100, 50))])
    refined = refine_reviewed_associations(rows, {2: review(parts)}, (60, 230))
    assert all(row.status == "ASSIGNED" and row.track_id == 2 for row in refined)


def test_existing_conflicting_claims_on_same_detection_stay_ambiguous():
    item = part(1, (10, 10, 25, 25))
    row, = associate_parts_to_parents([item], [ParentAnchor(1, (0, 0, 100, 50))])
    # Both reviewed masks claim these pixels; conflicting-instance checks also
    # remain active. No confidence tie-break may manufacture ownership.
    refined, = refine_reviewed_associations([row], {1: review([item]), 2: review([item])}, (60, 230))
    assert refined.status == "AMBIGUOUS"
    assert refined.track_id is None
    assert set(refined.ambiguous_track_ids) == {1, 2}


def test_heads_for_separate_reviewed_fish_do_not_conflict():
    parts = [part(1, (10, 10, 25, 25)), part(4, (150, 10, 165, 25))]
    parents = [ParentAnchor(1, (0, 0, 100, 50)), ParentAnchor(2, (120, 0, 220, 50))]
    first = np.zeros((60, 230), bool)
    first[:, :100] = True
    second = np.zeros_like(first)
    second[:, 120:220] = True
    reviewed = {1: review(parts[:1], pixels=first), 2: review(parts[1:], pixels=second)}
    refined = refine_reviewed_associations(associate_parts_to_parents(parts, parents), reviewed, first.shape)
    assert [(row.status, row.track_id) for row in refined] == [("ASSIGNED", 1), ("ASSIGNED", 2)]
