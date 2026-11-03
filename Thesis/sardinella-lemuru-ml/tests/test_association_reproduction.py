"""Real fixed detector outputs; verify software invariants without ownership GT."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evaluation.evaluate_association_repairs import (
    changes_between, csv_scene, evaluate_scene, part_key,
)
from src.inference import association


FIXTURES = Path(__file__).parent / "fixtures"
REAL = json.loads((FIXTURES / "association_repair_real_cases.json").read_text(encoding="utf-8"))["records"]


def test_original_csv_recovers_every_global_candidate_from_correct_source(tmp_path):
    scene = csv_scene(image_root=tmp_path)
    assert Path(scene["source"]["path"]).name == "WIN_20260823_20_49_53_Pro.jpg"
    assert scene["source"]["analyzed_at"] == "2026-11-01T00:20:20.811Z"
    assert len(scene["detections"]) == 7
    assert Counter(p["region"] for p in scene["parts"]) == {"Head": 7, "Body": 9, "Tail": 6}
    assert len({part_key(p) for p in scene["parts"]}) == 22
    assert scene["source"]["sha256"] is None  # CSV replay still works without original pixels.
    # These are the legacy recorded parents. The current Model1 is not substituted.
    assert scene["detections"][0]["bbox"] == [447.42, 648.54, 1119.74, 2160]
    assert max(p["bbox"][2] for p in scene["parts"]) > 3800


def test_csv_replay_preserves_raw_records_and_historical_grades(tmp_path):
    scene = csv_scene(image_root=tmp_path)
    previous = deepcopy(scene)
    result = evaluate_scene(scene, association, repeats=1)
    assert scene == previous
    assert len(result["decisions"]) == 22
    assert Counter(part_key(p) for p in scene["parts"]) == Counter(part_key(r["part"]) for r in result["decisions"])
    assert [r["final_grade"] for r in result["grades"]] == [g["grade"] for g in scene["original_export_grades"]]
    assert result["correct_assignments"] is None
    assert result["false_associations"] is None
    assert result["correct_grading_coverage"] is None


@pytest.mark.parametrize("scene,fish_id", list(zip(REAL, (4, 2, 7))))
def test_real_supported_head_is_retained_and_required_parts_use_same_policy(scene, fish_id):
    previous = deepcopy(scene)
    result = evaluate_scene(scene, association, repeats=1)
    verdict = next(g for g in result["grades"] if g["id"] == fish_id)
    assert verdict["final_grade"] != "Ungraded"
    assert {"Head", "Body"}.issubset(verdict["observed_regions"])
    weights = verdict["effective_weights"]
    if "Tail" not in verdict["observed_regions"]:
        assert weights["Head"] == pytest.approx(.375)
        assert weights["Body"] == pytest.approx(.625)
        assert weights["Tail"] == 0
    else:
        assert weights == {"Head": .3, "Body": .5, "Tail": .2}
    assigned = [r for r in result["decisions"] if r["status"] == "ASSIGNED"]
    owner_regions = [(r["track_id"], r["part"]["region"]) for r in assigned]
    assert len(owner_regions) == len(set(owner_regions))
    assert Counter(part_key(r["part"]) for r in result["decisions"]) == Counter(part_key(p) for p in scene["parts"])
    assert result["independent_ownership_labels_available"] is False
    assert scene == previous


def test_change_report_does_not_claim_added_assignment_is_ground_truth():
    part = {"source_class_id": 7, "confidence": .8, "bbox": [1, 2, 3, 4]}
    before = {"decisions": [{"part": part, "status": "AMBIGUOUS", "track_id": None, "reason": "competing_parent_geometry"}]}
    after = {"decisions": [{"part": part, "status": "ASSIGNED", "track_id": 3, "reason": None}]}
    changed = changes_between(before, after)
    assert len(changed) == 1
    assert changed[0]["expert_ownership_verified"] is False
    assert changes_between(after, after) == []
