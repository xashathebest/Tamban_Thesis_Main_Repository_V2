"""Reproductions of ownership bugs, using exact detector-space geometry.

These are software-policy fixtures, not expert-labeled fish accuracy claims.
"""
import csv
import json
from pathlib import Path

import pytest

from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.part_types import PartDetection


def part(class_id, box, confidence=.9):
    return PartDetection.from_source_class(class_id, confidence, box)


def test_ineligible_parent_cannot_veto_a_contained_head():
    parents = (ParentAnchor(1, (0, 0, 120, 80)), ParentAnchor(2, (78.5, 0, 198.5, 80)))
    row, = associate_parts_to_parents([part(1, (70, 30, 110, 50))], parents)
    assert (row.status, row.track_id) == ("ASSIGNED", 1)
    alternate = next(candidate for candidate in row.to_dict()["candidates"] if candidate["track_id"] == 2)
    assert alternate["eligible"] is False
    assert "part_not_contained" in alternate["failed_checks"]
    assert "association_score_below_threshold" in alternate["failed_checks"]


@pytest.mark.parametrize("reverse_parts", [False, True])
@pytest.mark.parametrize("reverse_parents", [False, True])
def test_global_selection_does_not_send_a_duplicate_to_its_second_choice(reverse_parts, reverse_parents):
    parents = [
        ParentAnchor(1, (0, 0, 120, 90), mask=((0, 0), (120, 0), (120, 90), (0, 90))),
        ParentAnchor(2, (80, 10, 190, 100)),
    ]
    parts = [part(1, (82, 30, 104, 52), .92), part(4, (84, 31, 106, 53), .9)]
    rows = associate_parts_to_parents(parts[::-1] if reverse_parts else parts,
                                      parents[::-1] if reverse_parents else parents)
    assigned = [row for row in rows if row.status == "ASSIGNED"]
    assert [(row.track_id, row.part.confidence) for row in assigned] == [(1, .92)]
    duplicate = next(row for row in rows if row.part.confidence == .9)
    assert duplicate.status == "UNASSIGNED"
    assert duplicate.reason == "duplicate_region_for_parent"
    assert len(duplicate.candidates) == 2  # Keep alternative raw geometry for review.


def test_ambiguous_detection_does_not_reserve_parent_from_clear_head():
    parents = (ParentAnchor(1, (0, 0, 120, 90)), ParentAnchor(2, (80, 0, 200, 90)))
    clear = part(1, (15, 30, 40, 50), .8)
    uncertain = part(4, (85, 30, 110, 50), .99)
    rows = associate_parts_to_parents([uncertain, clear], parents)
    assert rows[0].status == "AMBIGUOUS"
    assert (rows[1].status, rows[1].track_id) == ("ASSIGNED", 1)


def test_inconsistent_optional_tail_does_not_demote_independent_head_and_body():
    parts = (part(1, (20, 30, 40, 50)), part(0, (70, 25, 120, 55)),
             part(2, (23, 31, 43, 51)))
    rows = associate_parts_to_parents(parts, [ParentAnchor(1, (0, 0, 200, 80))])
    assert [(row.part.region, row.status) for row in rows] == [
        ("Head", "ASSIGNED"), ("Body", "ASSIGNED"), ("Tail", "AMBIGUOUS")]
    assert rows[2].reason == "anatomical_group_inconsistent"
    assert rows[2].ambiguous_track_ids == (1,)


def test_unknown_axis_does_not_reject_distinct_parts_of_diagonal_fish():
    # A nearly square whole-fish box cannot establish the native diagonal.
    # Projected centers on its guessed horizontal axis put Body outside Head–Tail.
    parts = (part(1, (30, 10, 50, 30)), part(0, (45, 35, 85, 75)),
             part(2, (30, 75, 50, 95)))
    rows = associate_parts_to_parents(parts, [ParentAnchor(1, (0, 0, 100, 100))])
    assert all(row.status == "ASSIGNED" for row in rows)
    assert rows[0].to_dict()["anatomical_checks"]["parent_axis_reliable"] is False


def test_explicit_axis_remains_a_check_and_cannot_force_neighbor_ownership():
    parents = (ParentAnchor(1, (0, 0, 120, 100), orientation=(1, 1)),
               ParentAnchor(2, (5, 0, 125, 100), orientation=(1, 1)))
    row, = associate_parts_to_parents([part(1, (50, 20, 75, 55))], parents)
    assert row.status == "AMBIGUOUS"
    assert row.track_id is None


@pytest.mark.parametrize("orientation,source", [(None, None), ((1, 0), "candidate_pca_hint")])
def test_unvalidated_axis_cannot_enable_ordering_hard_gates(orientation, source):
    parent = ParentAnchor(1, (0, 0, 100, 100), orientation=orientation,
                          orientation_reliable=False, orientation_source=source)
    parts = (part(1, (30, 10, 50, 30)), part(0, (45, 35, 85, 75)),
             part(2, (30, 75, 50, 95)))
    rows = associate_parts_to_parents(parts, [parent])
    assert all(row.status == "ASSIGNED" for row in rows)
    assert rows[0].candidates[0].to_dict()["orientation"]["reliable"] is False


def test_reliable_axis_rejects_inconsistent_tail_and_preserves_required_pair():
    parent = ParentAnchor(1, (0, 0, 200, 80), orientation=(1, 0),
                          orientation_source="reviewed_native_geometry")
    rows = associate_parts_to_parents([
        part(1, (20, 30, 40, 50)), part(0, (80, 25, 120, 55)),
        part(2, (40, 30, 60, 50))], [parent])
    assert [(row.part.region, row.status) for row in rows] == [
        ("Head", "ASSIGNED"), ("Body", "ASSIGNED"), ("Tail", "AMBIGUOUS")]
    assert rows[0].to_dict()["anatomical_checks"]["head_body_axis_overlap"] is True
    assert rows[2].reason == "anatomical_group_inconsistent"


def test_without_independent_body_conflicting_head_and_tail_stay_ambiguous():
    rows = associate_parts_to_parents([part(1, (45, 40, 58, 52)), part(2, (48, 41, 61, 53))],
                                      [ParentAnchor(1, (0, 0, 100, 100))])
    assert all(row.status == "AMBIGUOUS" for row in rows)
    assert all(row.ambiguous_track_ids == (1,) for row in rows)


@pytest.mark.parametrize("parts,parents,reason", [
    ([part(1, (10, 10, 20, 20))], [], "no_visible_parent"),
    ([part(1, (200, 10, 220, 20))], [ParentAnchor(1, (0, 0, 100, 100))], "part_not_contained"),
])
def test_every_unassigned_detection_has_exact_reason_and_thresholds(parts, parents, reason):
    row, = associate_parts_to_parents(parts, parents)
    payload = row.to_dict()
    assert row.reason == reason
    assert payload["acceptance_thresholds"]["minimum_part_inside_fraction"] == .8
    assert payload["acceptance_thresholds"]["minimum_association_score"] == .7
    assert payload["candidate_parent_ids"] == [parent.track_id for parent in parents]


def test_equal_candidates_stay_ambiguous_when_another_region_is_clear():
    parents = (ParentAnchor(1, (0, 0, 120, 100)), ParentAnchor(2, (5, 0, 125, 100)))
    rows = associate_parts_to_parents([part(1, (50, 20, 75, 55)), part(0, (7, 60, 30, 80))], parents)
    assert rows[0].status == "AMBIGUOUS"
    assert set(rows[0].ambiguous_track_ids) == {1, 2}


def test_all_seven_exported_records_replay_without_inventing_evidence():
    fixture = Path(__file__).parent / "fixtures" / "fish-inspection-upload-all.csv"
    with fixture.open(encoding="utf-8-sig", newline="") as stream:
        records = [json.loads(row["Complete fish event"]) for row in csv.DictReader(stream)]
    assert len(records) == 7
    parents = [ParentAnchor(record["id"], tuple(record["bbox"]), record["detector_confidence"])
               for record in records]
    raw = {}
    for record in records:
        # Each fish's exported trace omits ambiguities belonging exclusively
        # to other fish, so reconstruct the global raw set from all seven.
        for row in record["analysis"]["quality_inference"]["association"]["parts"]:
            evidence = row["part"]
            key = (evidence["source_class_id"], evidence["confidence"], tuple(evidence["bbox"]))
            raw[key] = PartDetection.from_source_class(key[0], key[1], key[2])
    rows = associate_parts_to_parents(raw.values(), parents)
    assert len(rows) == len(raw) == 22
    expected_regions = {1: {"Body", "Head"}, 2: {"Body"}, 3: {"Body", "Head"},
                        4: set(), 5: {"Body"}, 6: set(), 7: set()}
    for parent_id, expected in expected_regions.items():
        assert {row.part.region for row in rows if row.status == "ASSIGNED" and row.track_id == parent_id} == expected
    assert all(row.part in raw.values() for row in rows)
    assert all(row.reason for row in rows if row.status == "UNASSIGNED")
    # Pixel boxes remain in original-image space, with exact detector confidence.
    assert max(row.part.bbox[2] for row in rows) > 3000
    assert {(row.part.source_class_id, row.part.confidence, row.part.bbox) for row in rows} == set(raw)

