from copy import deepcopy

import numpy as np

from src.annotation.masks import mask_to_rle
from src.api.annotation_feedback import correction_report


def annotation(object_id="head", class_id=1):
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[3:8, 2:9] = 1
    return {"id": object_id, "class_id": class_id, "parent_id": "fish-1",
            "segmentation": mask_to_rle(mask), "confidence": .7}


def report(before, after):
    return correction_report(before, after, width=30, height=20)


def test_complete_set_acceptance_has_no_corrections():
    original = [annotation()]
    result = report(original, deepcopy(original))
    assert result["accepted_unchanged"] == 1
    assert result["counts"]["corrected_annotations"] == 0
    assert result["mean_mask_iou"] == 1
    assert result["detection_precision"] == result["detection_recall"] == 1


def test_class_mask_ownership_and_missing_part_are_separate():
    before = [annotation()]
    after = deepcopy(before)
    after[0]["class_id"] = 4
    after[0]["parent_id"] = "fish-2"
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[3:9, 2:9] = 1
    after[0]["segmentation"] = mask_to_rle(mask)
    after.append(annotation("tail", 2))
    result = report(before, after)
    assert result["counts"]["class_correction"] == 1
    assert result["counts"]["ownership_correction"] == 1
    assert result["counts"]["mask_correction"] == 1
    assert result["counts"]["missing_annotation"] == 1
    assert result["counts"]["corrected_annotations"] == 2
    assert result["mean_mask_iou"] < 1
    assert before[0]["class_id"] == 1


def test_missing_mask_and_duplicates_are_identified_without_bbox_substitution():
    missing = annotation("missing")
    missing["segmentation"] = None
    result = report([missing], [annotation("missing")])
    assert result["counts"]["missing_mask"] == 1
    assert result["mean_mask_iou"] is None
    duplicate = report([annotation("first"), annotation("second")], [annotation("first")])
    assert duplicate["counts"]["duplicate_annotation"] == 1
    assert duplicate["detection_precision"] == .5


def test_hole_correction_is_counted_losslessly():
    original = annotation()
    changed = deepcopy(original)
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[3:8, 2:9] = 1
    mask[4, 4] = 0
    changed["segmentation"] = mask_to_rle(mask)
    result = report([original], [changed])
    assert result["counts"]["mask_correction"] == 1
    assert result["mean_mask_iou"] == 34 / 35


def test_removing_an_extra_is_not_always_a_duplicate():
    first = annotation("first")
    second = annotation("second", 2)
    result = report([first, second], [first])
    assert result["counts"]["extra_annotation"] == 1
    assert result["counts"].get("duplicate_annotation", 0) == 0
