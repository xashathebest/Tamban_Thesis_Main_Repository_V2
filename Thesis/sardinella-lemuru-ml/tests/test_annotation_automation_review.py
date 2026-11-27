"""Independent adversarial checks of annotation candidate integrity.

These are model-free fixtures: passing them establishes data handling behavior,
not fish detection or segmentation accuracy on real photographs.
"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.api.annotation_automation import generate_annotations
from src.annotation.masks import segmentation_to_mask
from src.inference.part_types import PartDetection
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


@pytest.fixture
def registry():
    return [{"id": source_id + 1, "name": name, "source_name": name,
             "model_class_id": source_id, "kind": "anatomy", "active": True}
            for source_id, name in SOURCE_CLASSES.items()] + [
                {"id": 101, "name": "Whole fish", "kind": "whole_fish", "active": True}]


class CandidateService:
    def __init__(self, *, bad_part=None, bad_fish=None, corrupt_pixels=None):
        self.bad_part, self.bad_fish, self.corrupt_pixels = bad_part, bad_fish, corrupt_pixels
        self.frames, self.prompts = 0, []

    @contextmanager
    def open_frame(self, frame, key):
        self.frames += 1
        self.shape, self.key = frame.shape[:2], key
        yield self

    def predict(self, identity, bbox):
        self.prompts.append((identity, bbox))
        left, top, right, bottom = map(int, bbox)
        mask = np.zeros(self.shape, np.uint8)
        cv2.ellipse(mask, ((left + right) // 2, (top + bottom) // 2),
                    (max(1, (right - left) // 2 - 2), max(1, (bottom - top) // 2 - 2)),
                    0, 0, 360, 1, -1)
        if self.corrupt_pixels == "wrong_shape":
            mask = mask[:-1]
        candidate = {"mask": mask.astype(bool), "score": .99, "parent_id": identity,
                     "provenance": {"frame_key": self.key, "parent_id": identity,
                                    "coordinate_space": "original_frame", "mask_shape": list(mask.shape)}}
        if self.corrupt_pixels == "integer":
            candidate["mask"] = mask
        corruption = self.bad_part if isinstance(identity, str) else self.bad_fish
        if corruption == "frame":
            candidate["provenance"]["frame_key"] = "a-different-image"
        elif corruption == "owner":
            candidate["parent_id"] = "a-different-prompt"
            candidate["provenance"]["parent_id"] = "a-different-prompt"
        elif corruption == "coordinates":
            candidate["provenance"]["coordinate_space"] = "resized_crop"
        return candidate

    def diagnostics(self):
        return {"embedding_calls": self.frames, "prompt_calls": len(self.prompts)}


def generate(registry, tmp_path, *, boxes=((10, 10, 150, 90),), parts=(), service=None, document=None):
    detector = SimpleNamespace(model=object(), confidence_threshold=.5,
                               detect=lambda frame: [SimpleNamespace(bbox=box, confidence=.92) for box in boxes])
    quality = SimpleNamespace(model=object(), confidence_threshold=.25, infer_crop=lambda frame: list(parts))
    return generate_annotations(document or {"id": "review-fixture"}, np.zeros((120, 320, 3), np.uint8),
                                registry, detector=detector, quality_model=quality,
                                sam_service=service or CandidateService(), reference_root=tmp_path)


def test_many_objects_share_one_embedding_and_inputs_remain_unchanged(registry, tmp_path):
    manual = {"id": "manual-copy", "status": "approved", "revision": 5,
              "annotations": [{"id": "baseline", "class_id": 1, "source": "manual",
                               "status": "manual_verified", "segmentation": [[1, 1, 5, 1, 3, 4]]}]}
    original_doc, original_registry = deepcopy(manual), deepcopy(registry)
    service = CandidateService()
    parts = [PartDetection.from_source_class(1, .91, (20, 25, 45, 60)),
             PartDetection.from_source_class(1, .93, (190, 25, 215, 60))]
    result = generate(registry, tmp_path, boxes=((10, 10, 150, 90), (180, 10, 310, 90)),
                      parts=parts, service=service, document=manual)
    assert service.frames == 1
    assert len(service.prompts) == 4
    assert manual == original_doc and registry == original_registry
    assert all(ann["source"] == "automated" and ann["status"] == "unreviewed" for ann in result["annotations"])
    head_owners = {ann["parent_id"] for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Head"}
    assert head_owners == {"fish-1", "fish-2"}


@pytest.mark.parametrize("corruption", ["wrong_shape", "integer"])
def test_invalid_pixel_buffers_never_become_training_masks(registry, tmp_path, corruption):
    result = generate(registry, tmp_path, service=CandidateService(corrupt_pixels=corruption))
    assert result["automation"]["pixel_masks"] == 0
    assert result["annotations"][0]["segmentation"] is None
    assert "missing_segmentation" in result["annotations"][0]["flags"]


def test_overlapping_fish_are_flagged_but_independent_pixel_masks_retained(registry, tmp_path):
    result = generate(registry, tmp_path, boxes=((10, 10, 150, 90), (75, 10, 215, 90)))
    fish = result["annotations"]
    assert len(fish) == 2 and all(ann["segmentation"] is not None for ann in fish)
    assert all("overlapping_or_ambiguous_masks" in ann["flags"] for ann in fish)
    first, second = (segmentation_to_mask(ann["segmentation"], 120, 320) for ann in fish)
    assert np.any(first & second) and not np.array_equal(first, second)
    assert all(ann["status"] == "unreviewed" for ann in fish)


def test_duplicate_part_is_not_assigned_to_another_fish_by_vacancy(registry, tmp_path):
    parts = [PartDetection.from_source_class(1, .95, (30, 25, 60, 65)),
             PartDetection.from_source_class(4, .82, (30, 25, 60, 65))]
    result = generate(registry, tmp_path, boxes=((10, 10, 150, 90), (180, 10, 310, 90)), parts=parts)
    heads = [ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Head"]
    assert [ann["parent_id"] for ann in heads] == ["fish-1", None]
    assert all("possible_duplicate_mask" in ann["flags"] for ann in heads)
    assert heads[1]["metadata"]["association"]["reason"] == "duplicate_region_for_parent"
    assert "head_undetected_not_confirmed_absent" in result["annotations"][1]["flags"]


def test_registry_rename_to_another_original_name_does_not_change_model_id(registry, tmp_path):
    registry[0]["name"] = SOURCE_CLASSES[1]
    registry[1]["name"] = "Operator renamed head"
    parts = [PartDetection.from_source_class(0, .9, (45, 20, 110, 75))]
    result = generate(registry, tmp_path, parts=parts)
    part = next(ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Body")
    assert part["class_id"] == registry[0]["id"]
    assert part["metadata"]["model_class_id"] == 0


def test_ownership_failure_reason_is_visible_for_review(registry, tmp_path):
    result = generate(registry, tmp_path, service=CandidateService(bad_fish="owner"))
    fish = result["annotations"][0]
    assert "candidate_parent_identity_mismatch" in fish["metadata"]["ownership"]["reasons"]
    assert "candidate_parent_identity_mismatch" in fish["flags"]


@pytest.mark.parametrize("corruption", ["frame", "owner", "coordinates"])
def test_wrong_part_provenance_is_not_saved_as_a_valid_associated_mask(registry, tmp_path, corruption):
    parts = [PartDetection.from_source_class(1, .9, (20, 25, 45, 60))]
    result = generate(registry, tmp_path, parts=parts, service=CandidateService(bad_part=corruption))
    head = next(ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Head")
    assert head["segmentation"] is None
    assert "missing_segmentation" in head["flags"]
    assert any("provenance" in flag or "identity" in flag or "coordinates" in flag for flag in head["flags"])
    assert head["status"] == "unreviewed"


def test_native_model_part_pixels_remain_exact_without_another_sam_prompt(registry, tmp_path):
    """A rough fish candidate cannot erase a selected model's real part mask."""
    polygon = ((20., 20.), (48., 25.), (44., 58.), (20., 55.))
    part = PartDetection.from_source_class(1, .93, (20, 20, 48, 58), mask=polygon)
    service = CandidateService()
    result = generate(registry, tmp_path, parts=[part], service=service)
    assert service.frames == 1
    assert service.prompts == [(1, (10, 10, 150, 90))]
    fish = result["annotations"][0]
    head = next(ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Head")
    expected = np.zeros((120, 320), np.uint8)
    cv2.fillPoly(expected, [np.asarray(polygon, dtype=np.int32)], 1)
    actual = segmentation_to_mask(head["segmentation"], 120, 320)
    parent = segmentation_to_mask(fish["segmentation"], 120, 320)
    assert np.any(expected.astype(bool) & ~parent), "Fixture must challenge incorrect parent clipping."
    assert np.array_equal(actual, expected.astype(bool))
    assert head["parent_id"] == "fish-1"
    assert any("parent" in flag or "ownership" in flag for flag in head["flags"])
    assert head["metadata"]["mask_provenance"]["source"] == "existing_model2_instance_segmentation"
    assert head["source"] == "automated" and head["status"] == "unreviewed"


def test_boxlike_native_prediction_gets_foreground_fallback_and_raw_pixels_are_retained(registry, tmp_path):
    polygon = ((20., 20.), (48., 20.), (48., 58.), (20., 58.))
    part = PartDetection.from_source_class(1, .93, (20, 20, 48, 58), mask=polygon)
    service = CandidateService()
    result = generate(registry, tmp_path, parts=[part], service=service)
    head = next(a for a in result["annotations"] if a.get("metadata", {}).get("region") == "Head")
    assert service.frames == 1 and len(service.prompts) == 2
    assert service.prompts[1] == ("part-0", part.bbox)
    actual = segmentation_to_mask(head["segmentation"], 120, 320)
    raw = segmentation_to_mask(head["metadata"]["original_native_predicted_segmentation"], 120, 320)
    expected_raw = np.zeros((120, 320), np.uint8)
    cv2.fillPoly(expected_raw, [np.asarray(polygon, dtype=np.int32)], 1)
    assert np.array_equal(raw, expected_raw)
    assert 0 < actual.sum() < raw.sum() and not np.array_equal(actual, raw)
    assert "native_part_mask_boxlike_requires_review" in head["flags"]
    assert head["metadata"]["mask_provenance"]["parent_id"] == "part-0"
    assert head["metadata"]["model_class_id"] == 1 and head["confidence"] == .93
    assert part.mask == polygon and head["status"] == "unreviewed"


def test_boxlike_native_mask_is_not_reused_if_foreground_fallback_is_invalid(registry, tmp_path):
    part = PartDetection.from_source_class(1, .93, (20, 20, 48, 58),
                                           mask=((20., 20.), (48., 20.), (48., 58.), (20., 58.)))
    result = generate(registry, tmp_path, parts=[part], service=CandidateService(bad_part="frame"))
    head = next(a for a in result["annotations"] if a.get("metadata", {}).get("region") == "Head")
    assert head["segmentation"] is None and "missing_segmentation" in head["flags"]
    assert head["metadata"]["original_native_predicted_segmentation"] is not None
    assert "mask_provenance_mismatch_requires_regeneration" in head["flags"]
    assert head["status"] == "unreviewed"


def test_sam_part_clipping_preserves_lossless_original_candidate(registry, tmp_path):
    """Reviewers can recover every original pixel removed by parent clipping."""
    part = PartDetection.from_source_class(1, .93, (20, 20, 50, 60))
    service = CandidateService()
    result = generate(registry, tmp_path, parts=[part], service=service)
    head = next(ann for ann in result["annotations"] if ann.get("metadata", {}).get("region") == "Head")
    assert service.prompts == [(1, (10, 10, 150, 90)), ("part-0", (20., 20., 50., 60.))]
    assert "part_mask_clipped_to_candidate_parent_requires_review" in head["flags"]
    expected = np.zeros((120, 320), np.uint8)
    cv2.ellipse(expected, (35, 40), (13, 18), 0, 0, 360, 1, -1)
    original = segmentation_to_mask(head["metadata"]["original_predicted_segmentation"], 120, 320)
    actual = segmentation_to_mask(head["segmentation"], 120, 320)
    parent = segmentation_to_mask(result["annotations"][0]["segmentation"], 120, 320)
    assert np.array_equal(original, expected.astype(bool))
    assert np.array_equal(actual, original & parent)
    assert np.count_nonzero(original) > np.count_nonzero(actual) > 0
