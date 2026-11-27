"""Annotation inference contract: pixels, ownership, reference and abstention."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import cv2
import numpy as np
import pytest

from src.api.annotation_automation import generate_annotations, manual_reference
from src.annotation.masks import segmentation_to_mask
from src.inference.part_types import PartDetection
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


@pytest.fixture
def classes():
    return [{"id": key + 1, "name": name, "source_name": name, "model_class_id": key,
             "kind": "part", "active": True} for key, name in SOURCE_CLASSES.items()] + [
                 {"id": 99, "name": "Whole fish", "kind": "whole_fish", "active": True}]


class Sam:
    def __init__(self, mode="ellipse", fail_after=None):
        self.mode, self.fail_after, self.frames, self.prompts = mode, fail_after, 0, []

    @contextmanager
    def open_frame(self, frame, key):
        self.frames += 1
        self.frame, self.key = frame, key
        yield self

    def predict(self, identity, box):
        self.prompts.append((identity, box))
        if self.fail_after is not None and len(self.prompts) > self.fail_after:
            return {"status": "unavailable", "reason": "Prompt budget exhausted"}
        mask = np.zeros(self.frame.shape[:2], np.uint8)
        left, top, right, bottom = map(int, box)
        if self.mode == "ellipse":
            cv2.ellipse(mask, ((left + right)//2, (top + bottom)//2),
                        (max(1, (right-left)//2-1), max(1, (bottom-top)//2-1)), 0, 0, 360, 1, -1)
        elif self.mode == "rectangle":
            mask[top:bottom, left:right] = 1
        elif self.mode == "full":
            mask[:] = 1
        return {"mask": mask.astype(bool), "score": .9, "parent_id": identity,
                "provenance": {"frame_key": self.key, "parent_id": identity,
                               "coordinate_space": "original_frame", "mask_shape": list(mask.shape)}}

    def diagnostics(self):
        return {"embedding_calls": self.frames, "prompt_calls": len(self.prompts)}


def models(boxes=((10, 10, 150, 80),), parts=None):
    detector = SimpleNamespace(model=object(), weights_path=Path("unchanged.pt"), confidence_threshold=.5,
        detect=lambda frame: [SimpleNamespace(bbox=box, confidence=.8) for box in boxes])
    if parts is None:
        parts = [PartDetection.from_source_class(1, .85, (12, 25, 38, 55)),
                 PartDetection.from_source_class(0, .8, (48, 16, 110, 68)),
                 PartDetection.from_source_class(2, .6, (122, 30, 145, 60))]
    quality = SimpleNamespace(model=object(), weights_path=Path("also-unchanged.pt"), confidence_threshold=.25,
                              infer_crop=lambda frame: list(parts))
    return detector, quality


def run(classes, tmp_path, *, sam=None, boxes=((10, 10, 150, 80),), parts=None, quality=True):
    detector, model2 = models(boxes, parts)
    return generate_annotations({"id": "original", "width": 320, "height": 120},
        np.zeros((120, 320, 3), np.uint8), classes, detector=detector,
        quality_model=model2 if quality else None, sam_service=sam or Sam(), reference_root=tmp_path)


def test_real_native_masks_not_boxes_share_one_embedding(classes, tmp_path):
    original = deepcopy(classes)
    service = Sam()
    result = run(classes, tmp_path, sam=service)
    assert service.frames == 1 and len(service.prompts) == 4
    assert result["automation"]["pixel_masks"] == 4
    assert classes == original
    for ann in result["annotations"]:
        assert ann["status"] == "unreviewed" and ann["source"] == "automated"
        mask = segmentation_to_mask(ann["segmentation"], 120, 320)
        x, y, w, h = ann["bbox"]
        assert 0 < mask.sum() < w * h
        assert mask.shape == (120, 320)
    assert {a["parent_id"] for a in result["annotations"][1:]} == {"fish-1"}
    assert "low_confidence_review" in result["annotations"][-1]["flags"]


@pytest.mark.parametrize("mode", ["empty", "rectangle", "full"])
def test_no_fabricated_masks_when_backend_returns_unusable_pixels(classes, tmp_path, mode):
    result = run(classes, tmp_path, sam=Sam(mode))
    assert result["automation"]["pixel_masks"] == 0
    assert result["automation"]["errors"]
    assert all(ann["segmentation"] is None and "missing_segmentation" in ann["flags"] for ann in result["annotations"])
    assert all(ann["status"] == "unreviewed" for ann in result["annotations"])


def test_no_parts_or_model_does_not_assert_physical_absence(classes, tmp_path):
    result = run(classes, tmp_path, quality=False)
    assert len(result["annotations"]) == 1
    assert set(result["annotations"][0]["flags"]) >= {
        "head_undetected_not_confirmed_absent", "body_undetected_not_confirmed_absent", "tail_undetected_not_confirmed_absent"}
    assert result["automation"]["errors"]


def test_renamed_registry_classes_keep_exact_original_model_mapping(classes, tmp_path):
    classes[0]["name"] = "Custom body wording"
    result = run(classes, tmp_path)
    body = next(ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Body")
    assert body["class_id"] == 1  # Original model ID zero is NOT COCO category zero.


def test_unknown_registry_model_link_requires_repair_without_guessing(classes, tmp_path):
    classes = [c for c in classes if c.get("model_class_id") != 0]
    with pytest.raises(ValueError, match="model-linked"):
        run(classes, tmp_path)


def test_unavailable_model1_fails_explicitly(classes, tmp_path):
    with pytest.raises(RuntimeError, match="Whole-fish detection"):
        generate_annotations({"id": "x"}, np.zeros((100, 100, 3), np.uint8), classes,
                             detector=SimpleNamespace(model=None), quality_model=None, reference_root=tmp_path)


def test_prompt_budget_keeps_missing_parts_editable(classes, tmp_path):
    result = run(classes, tmp_path, sam=Sam(fail_after=1))
    assert result["automation"]["pixel_masks"] == 1
    assert len(result["annotations"]) == 4
    assert all(a["segmentation"] is None for a in result["annotations"][1:])


def test_duplicate_fish_masks_flagged_never_silently_approved(classes, tmp_path):
    result = run(classes, tmp_path, boxes=((10, 10, 150, 80), (10, 10, 150, 80)), parts=[])
    assert len(result["annotations"]) == 2
    assert all("possible_duplicate_mask" in ann["flags"] for ann in result["annotations"])
    assert all(ann["status"] == "unreviewed" for ann in result["annotations"])


def test_empty_detection_does_not_invent_negative_ground_truth(classes, tmp_path):
    result = run(classes, tmp_path, boxes=(), parts=[])
    assert result["annotations"] == []
    assert result["automation"]["status"] == "no_detections_requires_review"


def test_reference_readonly_and_heldout_labels_not_used(tmp_path):
    files = {}
    for split, name in (("train", "Grade_A_Body"), ("valid", "Grade_A_Head"), ("test", "Grade_A_Tail")):
        directory = tmp_path / split
        directory.mkdir()
        path = directory / "_annotations.coco.json"
        path.write_text(json.dumps({"categories": [{"id": 17, "name": name}],
            "images": [{"id": 1, "width": 100, "height": 100}],
            "annotations": [{"id": 2, "image_id": 1, "category_id": 17, "area": 100}]}))
        files[path] = path.read_bytes()
    reference = manual_reference(str(tmp_path))
    assert set(reference["classes"]) == {"Grade_A_Body"}
    assert [source["split"] for source in reference["sources"]] == ["train"]
    assert all(path.read_bytes() == raw for path, raw in files.items())
    assert reference["whole_fish_ground_truth_available"] is False


def test_selected_primary_descriptor_is_used_without_other_dataset_fallback(tmp_path):
    path = tmp_path / "primary.reference.json"
    value = {"annotation_unit": "fish_part", "whole_fish_ground_truth_available": False,
             "sources": [{"dataset_id": "selected-345", "sha256": "source-snapshot"}],
             "classes": {"Grade_A_Body": [{"annotation_id": 7, "split": "train", "area_fraction": .02}]}}
    path.write_text(json.dumps(value))
    assert manual_reference(str(path)) == value


@pytest.mark.parametrize("classes", [{"Grade_A_Body": [{"annotation_id": 1, "split": "test"}]},
                                     {"Grade_A_Body": "invalid"}, {"Grade_A_Body": [None]}])
def test_primary_descriptor_rejects_heldout_and_malformed_examples(tmp_path, classes):
    path = tmp_path / "invalid.reference.json"
    path.write_text(json.dumps({"annotation_unit": "fish_part", "classes": classes}))
    with pytest.raises(ValueError, match="descriptor"):
        manual_reference(str(path))
