"""Crowded head review repairs evidence without borrowing anatomy or pixels."""

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import RuntimeMaskContext
from src.inference.yolo_quality_model import YoloQualityModel


def quality(parts):
    value = YoloQualityModel(Path("fixture-crowded.pt"), device="cpu", model_id="crowded-test",
        quality_inference_mode="full_frame", grading_engine=WeightedGradingEngine(GradingConfig(
            grading_mode="tail_optional_v1", image_diagnostics_enabled=False)))
    value.model = object()
    value._infer_parts = lambda _: (parts, parts)
    return value


class NativeService:
    def __init__(self, masks, *, merge_initial=False):
        self.masks, self.merge_initial = masks, merge_initial
        self.prompts, self.frames = [], []

    @contextmanager
    def open_frame(self, frame, key):
        self.key = key
        self._session_prompt_start = len(self.prompts)
        self.frames.append(key)
        yield self

    def predict(self, parent, box, **options):
        self.prompts.append((parent, options))
        mask = (np.logical_or.reduce(list(self.masks.values()))
                if self.merge_initial and not options.get("point_coords") else self.masks[parent])
        return {"status": "candidate", "parent_id": parent, "mask": mask.copy(), "score": .99,
            "provenance": {"backend": "mobilesam_experimental", "parent_id": parent,
                "frame_key": self.key, "coordinate_space": "original_frame", "mask_shape": list(mask.shape),
                "original_bbox_global": list(box), "prompt_bbox_global": list(box)}}

    def diagnostics(self):
        return {"embedding_calls": 1, "prompt_calls": len(self.prompts) - self._session_prompt_start}


def fish(shape, y):
    mask = np.zeros(shape, np.uint8)
    cv2.rectangle(mask, (30, y - 15), (170, y + 15), 1, -1)
    cv2.fillPoly(mask, [np.array(((170, y - 12), (230, y), (170, y + 12)))], 1)
    return mask.astype(bool)


def test_joint_point_refinement_resolves_crowded_masks_before_head_grading(monkeypatch):
    shape = (220, 300)
    native = {1: fish(shape, 60), 2: fish(shape, 150)}
    service = NativeService(native, merge_initial=True)
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    frame = np.random.default_rng(19).integers(30, 220, (*shape, 3), dtype=np.uint8)
    parents = [ParentAnchor(1, (15, 25, 250, 140), .99), ParentAnchor(2, (15, 80, 250, 190), .99)]
    parts = [PartDetection.from_source_class(0, .95, (30, y - 15, 171, y + 16)) for y in (60, 150)]
    masks = RuntimeMaskContext(frame, frame_id="crowded", backend="mobilesam_experimental")
    results = quality(parts).predict_full_frame(frame, parents, stabilize=False, frame_id="crowded", mask_context=masks)
    assert [results[identity][0].quality for identity in (1, 2)] == ["Rejected", "Rejected"]
    assert len(service.frames) == 1 and len(service.prompts) == 4
    for identity in (1, 2):
        analysis = results[identity][0].analysis
        assert analysis["head_integrity"]["failed_rejection_gates"] == []
        assert analysis["head_integrity"]["quality_grading_before_integrity"]["grade"] == "Ungraded"
        np.testing.assert_array_equal(masks._experimental.candidates[identity]["mask"], native[identity])
        assert masks._experimental.ownership[identity]["metrics"]["pair_overlap_fraction"] == {str(3 - identity): 0.0}
        json.dumps(analysis, allow_nan=False)
    assert masks._experimental._diagnostics["crowded_refinement"]["selection"]["replaced_parent_ids"] == [1, 2]
    assert all(options.get("point_prompt_source") == "estimated_native_mask_and_detector_geometry"
               for _, options in service.prompts[2:])


def test_native_silhouette_expands_crop_when_missing_detector_parts(monkeypatch):
    shape = (140, 300)
    native = {1: fish(shape, 65)}
    service = NativeService(native)
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    frame = np.random.default_rng(20).integers(30, 220, (*shape, 3), dtype=np.uint8)
    # The parent clips 13 pixels of real anterior tissue. The independently
    # checked native mask must expand the ROI before terminal measurements.
    parent = ParentAnchor(1, (43, 40, 235, 95), .99)
    masks = RuntimeMaskContext(frame, frame_id="expanded", backend="mobilesam_experimental")
    result, bounds = quality([]).predict_full_frame(frame, [parent], stabilize=False,
        frame_id="expanded", mask_context=masks)[1]
    assert bounds.x1 <= 30
    assert result.quality == "Rejected"
    report = result.analysis["head_integrity"]
    assert report["measurements"]["body_pixels"] == 0
    assert report["body_support"]["geometric_torso"]["eligible"] is True
    assert report["clipping_checks"]["crop_foreground_retained_fraction"] == 1.0
    assert result.analysis["quality_inference"]["association"]["clipping"]["context_expanded_for_native_silhouette"]
    assert len(service.prompts) == 1


def test_failed_optional_instance_refinement_retains_original_part_grades(monkeypatch):
    shape = (140, 300)
    native = {1: fish(shape, 65)}
    service = NativeService(native)
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    def unavailable(*args, **kwargs):
        raise RuntimeError("optional instance scoring unavailable")
    monkeypatch.setattr("src.inference.instance_association.refine_instance_associations", unavailable)
    frame = np.random.default_rng(21).integers(30, 220, (*shape, 3), dtype=np.uint8)
    parts = [PartDetection.from_source_class(0, .95, (30, 50, 171, 81)),
             PartDetection.from_source_class(1, .95, (30, 50, 55, 81))]
    masks = RuntimeMaskContext(frame, frame_id="fallback", backend="mobilesam_experimental")
    result = quality(parts).predict_full_frame(frame, [ParentAnchor(1, (15, 35, 250, 100), .99)],
        stabilize=False, frame_id="fallback", mask_context=masks)[1][0]
    assert result.quality == "Class A"
    assert result.analysis["quality_inference"]["association"]["native_instance_refinement"]["status"] == "unavailable"


def test_final_ownership_recheck_keeps_the_exact_pixels_used_for_association(monkeypatch):
    shape = (140, 300)
    service = NativeService({1: fish(shape, 65)})
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    frame = np.full((*shape, 3), 120, dtype=np.uint8)
    parent = ParentAnchor(1, (15, 35, 250, 100), .99)
    body = PartDetection.from_source_class(0, .95, (30, 50, 171, 81))
    masks = RuntimeMaskContext(frame, frame_id="fixed-evidence", backend="mobilesam_experimental")
    masks.prepare_instances([parent], [body], [])
    supporting_mask = masks._experimental.candidates[1]["mask"]
    assigned = [SimpleNamespace(status="ASSIGNED", track_id=1, part=body)]
    masks.prepare_instances([parent], [body], assigned, ownership_only=True)
    assert masks._experimental.candidates[1]["mask"] is supporting_mask
    assert len(service.frames) == 1
    assert masks._experimental._diagnostics["ownership_revalidation_runs"] == 1
    assert masks._experimental.ownership[1]["metrics"]["detected_part_box_coverage"]["Body"] > 0
    # An ordinary preparation with changed prompt evidence must regenerate;
    # ownership-only mode is not a way to reuse masks for a different source.
    masks.prepare_instances([parent], [body], assigned)
    assert len(service.frames) == 2
    assert masks._experimental._diagnostics["embedding_calls"] == 2
    frame[0, 0] ^= 1
    with pytest.raises(ValueError, match="identical source"):
        masks.prepare_instances([parent], [body], assigned, ownership_only=True)
