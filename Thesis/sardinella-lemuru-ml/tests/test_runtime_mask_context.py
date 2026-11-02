"""Frame/parent/pixel scoped segmentation reuse and preserved grading evidence."""

from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, PreprocessingError, RuntimeMaskContext, crop_fish, measurement_crop_bounds
from src.inference.yolo_quality_model import YoloQualityModel


@pytest.fixture
def mask_calls(monkeypatch):
    calls = []

    def segment(crop):
        calls.append(crop.copy())
        mask = crop[:, :, 0] > 80
        return mask, {
            "status": "validated_for_features", "source": "runtime_test_mask",
            "foreground_pixels": int(mask.sum()),
        }

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", segment)
    monkeypatch.setattr("src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", segment)
    return calls


def _frame():
    frame = np.full((180, 320, 3), 30, dtype=np.uint8)
    cv2.ellipse(frame, (160, 90), (100, 25), 0, 0, 360, (130, 170, 200), -1)
    return frame


def test_same_parent_and_exact_roi_reuses_one_mask_without_mutable_cache_outputs(mask_calls):
    frame = _frame()
    bounds = CropBounds(40, 40, 280, 140)
    context = RuntimeMaskContext(frame, frame_id="upload-1")
    first, metadata = context.get(7, bounds)
    metadata["crop_bounds"][0] = -999
    second, second_metadata = context.get(7, bounds)

    assert len(mask_calls) == 1
    np.testing.assert_array_equal(first, second)
    assert np.shares_memory(first, second)
    assert not second.flags.writeable
    with pytest.raises(ValueError):
        second.setflags(write=True)
    assert second_metadata["crop_bounds"] == [40, 40, 280, 140]
    assert second_metadata["cache_hit"] is True
    assert second_metadata["parent_track_id"] == 7
    assert second_metadata["frame_id"] == "upload-1"
    assert second_metadata["measurement_validated"] is False
    assert second_metadata["mask_validated_for_cracks"] is False
    assert context.diagnostics()["segmentation_calls"] == 1
    assert context.diagnostics()["cache_hits"] == 1
    json.dumps(second_metadata, allow_nan=False)
    json.dumps(context.diagnostics(), allow_nan=False)


def test_parent_roi_and_frame_isolation_never_alias_equal_sized_crops(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    bounds = CropBounds(20, 30, 140, 120)
    context.get(1, bounds)
    context.get(2, bounds)
    context.get(1, CropBounds(160, 30, 280, 120))
    other_frame = frame.copy()
    other_context = RuntimeMaskContext(other_frame)
    other_context.get(1, bounds)

    assert len(mask_calls) == 4
    assert context.is_for_frame(frame)
    assert not context.is_for_frame(other_frame)
    assert other_context.diagnostics()["segmentation_calls"] == 1


def test_in_place_pixel_edit_invalidates_mask_cache(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    bounds = CropBounds(40, 40, 280, 140)
    first, _ = context.get(7, bounds)
    frame[50, 50] = 255
    second, metadata = context.get(7, bounds)

    assert len(mask_calls) == 2
    assert not first[10, 10]
    assert second[10, 10]
    assert metadata["cache_hit"] is False


def test_unavailable_segmentation_is_cached_with_its_failure_reason(monkeypatch):
    calls = []

    def unavailable(crop):
        calls.append(crop.shape)
        return None, {"status": "unavailable", "reason": "synthetic area rejection"}

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", unavailable)
    context = RuntimeMaskContext(_frame())
    bounds = CropBounds(40, 40, 280, 140)
    first, _ = context.get(7, bounds)
    second, metadata = context.get(7, bounds)
    assert first is second is None
    assert len(calls) == 1
    assert metadata["status"] == "unavailable"
    assert metadata["reason"] == "synthetic area rejection"
    assert metadata["cache_hit"] is True


def test_optional_segmentation_exception_is_cached_with_provenance_and_retried_next_frame(monkeypatch):
    calls = []

    def failing(crop):
        calls.append(crop.shape)
        raise RuntimeError("Synthetic foreground algorithm failure")

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", failing)
    bounds = CropBounds(40, 40, 280, 140)
    context = RuntimeMaskContext(_frame(), frame_id=17)
    first, first_metadata = context.get(7, bounds)
    second, metadata = context.get(7, bounds)
    assert first is second is None
    assert len(calls) == 1
    assert first_metadata["cache_hit"] is False and metadata["cache_hit"] is True
    assert metadata["status"] == "unavailable"
    assert metadata["reason"] == "Runtime foreground mask processing failed."
    assert metadata["error_type"] == "RuntimeError"
    assert metadata["parent_track_id"] == 7 and metadata["frame_id"] == 17
    assert metadata["crop_bounds"] == [40, 40, 280, 140]
    assert metadata["measurement_validated"] is False
    assert metadata["mask_validated_for_cracks"] is False
    assert context.diagnostics()["segmentation_calls"] == 1
    assert context.diagnostics()["segmentation_ms"] >= metadata["segmentation_ms"]
    assert context.diagnostics()["cache_hits"] == 1
    RuntimeMaskContext(_frame(), frame_id=18).get(7, bounds)
    assert len(calls) == 2


@pytest.mark.parametrize("parent,bounds", [
    (True, CropBounds(0, 0, 100, 100)),
    (1, CropBounds(-1, 0, 100, 100)),
    (1, CropBounds(0, 0, 321, 100)),
    (1, CropBounds(0, 0, 0, 100)),
    (1, CropBounds(0.5, 0, 100, 100)),
    (1, (0, 0, 100, 100)),
])
def test_context_rejects_unverified_or_out_of_frame_bounds(parent, bounds):
    with pytest.raises(PreprocessingError):
        RuntimeMaskContext(_frame()).get(parent, bounds)


def test_feature_cache_preserves_provenance_and_freezes_nested_overlay_arrays():
    frame = _frame()
    context = RuntimeMaskContext(frame)
    bounds = CropBounds(40, 40, 280, 140)
    calls = []

    def feature():
        calls.append(1)
        return {"overlay_mask": np.zeros((100, 240), np.uint8), "locations": [{"x": 12}]}

    first = context.cached_feature(7, bounds, "damage-v1:settings-a", feature)
    first["locations"][0]["x"] = 999
    second = context.cached_feature(7, bounds, "damage-v1:settings-a", feature)
    assert len(calls) == 1
    assert second["locations"][0]["x"] == 12
    assert not second["overlay_mask"].flags.writeable
    with pytest.raises(ValueError):
        second["overlay_mask"].setflags(write=True)
    context.cached_feature(7, bounds, "damage-v1:settings-b", feature)
    context.cached_feature(8, bounds, "damage-v1:settings-a", feature)
    frame[60, 60] = 255
    context.cached_feature(7, bounds, "damage-v1:settings-a", feature)
    assert len(calls) == 4
    assert context.diagnostics()["feature_cache_hits"] == 1
    assert context.diagnostics()["feature_calls"] == 4


def test_failed_feature_factory_is_retried():
    context = RuntimeMaskContext(_frame())
    attempts = []

    def failing():
        attempts.append(1)
        raise ValueError("synthetic diagnostic failure")

    for _ in range(2):
        with pytest.raises(ValueError, match="synthetic diagnostic failure"):
            context.cached_feature(7, CropBounds(40, 40, 280, 140), "failing-v1", failing)
    assert len(attempts) == 2


def test_parallel_lookups_only_segment_same_parent_roi_once(mask_calls):
    context = RuntimeMaskContext(_frame())
    bounds = CropBounds(40, 40, 280, 140)
    with ThreadPoolExecutor(max_workers=4) as executor:
        masks = list(executor.map(lambda _: context.get(7, bounds)[0], range(8)))
    assert len(mask_calls) == 1
    assert context.diagnostics()["cache_hits"] == 7
    for mask in masks[1:]:
        np.testing.assert_array_equal(mask, masks[0])


def _quality(parts, *, mode="crop", roi_padding=0):
    model = YoloQualityModel(
        Path("synthetic-mask-context-only.pt"), model_id="synthetic-mask-context-only",
        device="cpu", quality_inference_mode=mode, roi_padding=roi_padding,
        grading_engine=WeightedGradingEngine(GradingConfig(image_diagnostics_enabled=True)),
    )
    model.model = object()
    model._infer_parts = lambda _: (list(parts), list(parts))
    return model


def _parts(offset=(0, 0)):
    x, y = offset
    return [
        PartDetection.from_source_class(class_id, confidence, (x + left, y + top, x + right, y + bottom))
        for class_id, confidence, (left, top, right, bottom) in (
            (0, .9, (70, 24, 170, 76)),
            (1, .8, (20, 30, 50, 70)),
            (2, .7, (190, 30, 220, 70)),
        )
    ]


def test_new_texture_mask_preserves_existing_hsv_and_weighted_decisions(mask_calls):
    frame = _frame()
    parent = (40, 40, 280, 140)
    crop, bounds = crop_fish(frame, parent)
    kwargs = dict(
        stabilize=False, frame_id="same-image", detection_confidence=.99,
        parent_bbox=parent, crop_bounds=bounds, frame_shape=frame.shape,
        frame_quality={"usable": True},
    )
    baseline = _quality(_parts()).predict(crop, 7, **kwargs)
    context = RuntimeMaskContext(frame, frame_id="same-image")
    measured = _quality(_parts()).predict(
        crop, 7, **kwargs, measurement_frame=frame, mask_context=context,
    )
    for key in (
        "final_grade", "final_score", "weighted_scores", "effective_weights",
        "original_weight_coverage", "part_results", "adjustments", "color",
    ):
        assert measured.analysis[key] == baseline.analysis[key]
    assert baseline.analysis["supporting_image_measurements"]["texture"]["status"] == "unavailable"
    texture = measured.analysis["supporting_image_measurements"]["texture"]
    assert texture["status"] == "measured"
    assert texture["mask_metadata"]["crop_bounds"] == [40, 40, 280, 140]
    geometry = measured.analysis["fish_geometry"]
    assert geometry["mask_metadata"]["dedicated_measurement_crop"] is True
    assert geometry["mask_crop_bounds"] != [40, 40, 280, 140]
    assert context.diagnostics()["segmentation_calls"] == 2
    context.get(7, bounds)
    assert context.diagnostics()["segmentation_calls"] == 2
    assert context.diagnostics()["cache_hits"] == 1
    json.dumps(measured.analysis, allow_nan=False)


def test_full_frame_texture_gets_correct_parent_mask_and_separate_geometry_roi(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame, frame_id="full-frame")
    model = _quality(_parts((40, 40)), mode="full_frame")
    observation, bounds = model.predict_full_frame(
        frame, [ParentAnchor(7, (40, 40, 280, 140), .99)],
        stabilize=False, frame_id="full-frame", mask_context=context,
    )[7]
    texture = observation.analysis["supporting_image_measurements"]["texture"]
    assert texture["status"] == "measured"
    assert texture["mask_metadata"]["parent_track_id"] == 7
    assert texture["mask_metadata"]["crop_bounds"] == [bounds.x1, bounds.y1, bounds.x2, bounds.y2]
    assert observation.analysis["fish_geometry"]["mask_crop_bounds"] != texture["mask_metadata"]["crop_bounds"]
    assert observation.analysis["effective_weights"] == {"Body": .5, "Head": .3, "Tail": .2}
    assert observation.analysis["weighted_scores"]["Class A"] == pytest.approx(.83)
    assert observation.analysis["adjustments"] == []
    assert texture["mask_metadata"]["source"] == "runtime_grabcut_padded_projection"
    assert texture["mask_metadata"]["projection"]["source_crop_bounds"] == observation.analysis["fish_geometry"]["mask_crop_bounds"]
    assert context.diagnostics()["segmentation_calls"] == 1
    assert context.diagnostics()["projection_calls"] == 1


def test_wrong_frame_context_is_not_used_for_crop_texture(mask_calls):
    frame = _frame()
    crop, bounds = crop_fish(frame, (40, 40, 280, 140))
    other_context = RuntimeMaskContext(frame.copy())
    observation = _quality(_parts()).predict(
        crop, 7, stabilize=False, parent_bbox=(40, 40, 280, 140),
        crop_bounds=bounds, frame_shape=frame.shape, frame_quality={"usable": True},
        measurement_frame=frame, mask_context=other_context,
    )
    assert observation.analysis["supporting_image_measurements"]["texture"]["status"] == "unavailable"
    assert other_context.diagnostics()["segmentation_calls"] == 0


def test_different_crop_pixels_cannot_borrow_mask_from_matching_sized_source_roi(mask_calls):
    frame = _frame()
    crop, bounds = crop_fish(frame, (40, 40, 280, 140))
    unrelated_crop = crop.copy()
    unrelated_crop[50, 50] = 0
    context = RuntimeMaskContext(frame)
    observation = _quality(_parts()).predict(
        unrelated_crop, 7, stabilize=False, parent_bbox=(40, 40, 280, 140),
        crop_bounds=bounds, frame_shape=frame.shape, frame_quality={"usable": True},
        measurement_frame=frame, mask_context=context,
    )
    assert observation.analysis["supporting_image_measurements"]["texture"]["status"] == "unavailable"
    assert "source_crop_pixels_mismatch" in observation.analysis["fish_geometry"]["reasons"]
    assert observation.analysis["fish_geometry"]["fish_length_px"] is None
    # Only the separate, original-frame measurement crop was segmented.
    assert context.diagnostics()["segmentation_calls"] == 1


def test_equal_grading_and_measurement_rois_can_reuse_exact_same_mask(mask_calls):
    frame = _frame()
    crop, bounds = crop_fish(frame, (40, 40, 280, 140), padding=15)
    context = RuntimeMaskContext(frame)
    observation = _quality(_parts((15, 15)), roi_padding=15).predict(
        crop, 7, stabilize=False, parent_bbox=(40, 40, 280, 140),
        crop_bounds=bounds, frame_shape=frame.shape, frame_quality={"usable": True},
        measurement_frame=frame, mask_context=context,
    )
    geometry = observation.analysis["fish_geometry"]
    assert geometry["mask_crop_bounds"] == [bounds.x1, bounds.y1, bounds.x2, bounds.y2]
    assert geometry["mask_metadata"]["dedicated_measurement_crop"] is True
    assert geometry["mask_metadata"]["cache_hit"] is True
    assert context.diagnostics()["segmentation_calls"] == 1
    assert context.diagnostics()["cache_hits"] == 1


def test_projection_uses_native_offsets_and_reports_source_and_target_provenance(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame, frame_id="projection-frame")
    source_bounds = CropBounds(*(np.int64(value) for value in (20, 15, 300, 160)))
    target_bounds = CropBounds(*(np.int64(value) for value in (40, 40, 280, 140)))
    target = frame[40:140, 40:280]
    projected, metadata = context.get_projected(7, source_bounds, target_bounds, frame=frame, target_crop=target)
    np.testing.assert_array_equal(projected, target[:, :, 0] > 80)
    assert projected.shape == (100, 240)
    assert not projected.flags.writeable
    assert metadata["projection"]["target_offset_in_source"] == [20, 25]
    assert metadata["projection"]["source_origin"] == [20, 15]
    assert metadata["projection"]["source_crop_bounds"] == [20, 15, 300, 160]
    assert metadata["crop_bounds"] == [40, 40, 280, 140]
    assert metadata["frame_id"] == "projection-frame"
    assert metadata["parent_track_id"] == 7
    assert metadata["projection"]["single_component_validation_passed"] is True
    reused, reused_metadata = context.get(7, target_bounds)
    np.testing.assert_array_equal(reused, projected)
    assert reused_metadata["cache_hit"] is True
    assert len(mask_calls) == 1
    json.dumps(metadata, allow_nan=False)


@pytest.mark.parametrize("existing_mask", [False, True])
def test_projection_never_overwrites_existing_target_even_when_it_is_unavailable(monkeypatch, existing_mask):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    bounds = CropBounds(40, 40, 280, 140)
    calls = []

    def original(crop):
        calls.append(crop.shape)
        return (crop[:, :, 0] > 80) if existing_mask else None, {
            "status": "validated_for_features" if existing_mask else "unavailable", "source": "runtime_original_target",
        }

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", original)
    initial, initial_metadata = context.get(7, bounds)
    result, metadata = context.get_projected(
        7, CropBounds(20, 15, 300, 160), bounds, frame=frame, target_crop=frame[40:140, 40:280],
    )
    assert (result is None) is (initial is None)
    assert metadata["source"] == initial_metadata["source"]
    assert "projection" not in metadata
    assert len(calls) == 1


def test_projection_keeps_parent_masks_separate_even_for_identical_source_bounds(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    source = CropBounds(20, 15, 300, 160)
    target = CropBounds(40, 40, 280, 140)
    context.get(7, source)
    _, metadata = context.get_projected(8, source, target, frame=frame, target_crop=frame[40:140, 40:280])
    assert len(mask_calls) == 2
    assert metadata["parent_track_id"] == 8
    assert metadata["source_mask_metadata"]["parent_track_id"] == 8


def test_projection_rejects_different_frame_or_target_pixels_without_any_segmentation(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    source = CropBounds(20, 15, 300, 160)
    target = CropBounds(40, 40, 280, 140)
    with pytest.raises(PreprocessingError, match="original source frame"):
        context.get_projected(7, source, target, frame=frame.copy(), target_crop=frame[40:140, 40:280])
    unrelated = frame[40:140, 40:280].copy()
    unrelated[0, 0] = 255
    with pytest.raises(PreprocessingError, match="target pixels differ"):
        context.get_projected(7, source, target, frame=frame, target_crop=unrelated)
    assert len(mask_calls) == 0


def test_projection_outside_source_roi_falls_back_to_exact_target_segmentation(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    target = CropBounds(40, 40, 280, 140)
    _, metadata = context.get_projected(7, CropBounds(60, 40, 280, 140), target, frame=frame, target_crop=frame[40:140, 40:280])
    assert metadata["projection_rejection_reason"] == "target_roi_not_contained_in_source_roi"
    assert "projection" not in metadata
    assert len(mask_calls) == 1
    assert mask_calls[0].shape == (100, 240, 3)


@pytest.mark.parametrize("rejection", ["area", "components", "retained", "source_components", "source_boundary"])
def test_projection_reliability_failures_fall_back_to_exact_target(monkeypatch, rejection):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    source = CropBounds(20, 15, 300, 160)
    target = CropBounds(40, 40, 280, 140)
    calls = []

    def segment(crop):
        calls.append(crop.shape)
        mask = crop[:, :, 0] > 80
        metadata = {"status": "validated_for_features", "source": "runtime_test_mask"}
        if crop.shape[:2] == (145, 280):
            if rejection == "area": mask[:] = True
            if rejection == "components": mask[:, 135:145] = False
            if rejection == "retained": mask[:25, 20:260] = True
            if rejection == "source_components": metadata["raw_second_component_fraction"] = .2
            if rejection == "source_boundary": metadata["foreground_touches_initialization_boundary"] = True
        return mask, metadata

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", segment)
    _, metadata = context.get_projected(7, source, target, frame=frame, target_crop=frame[40:140, 40:280])
    assert len(calls) == 2
    assert "projection" not in metadata
    assert metadata["projection_rejection_reason"]
    assert context.diagnostics()["projection_fallbacks"] == 1


def test_padding_only_mutation_invalidates_projected_mask_and_its_cached_features(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    source = CropBounds(20, 15, 300, 160)
    target = CropBounds(40, 40, 280, 140)
    crop = frame[40:140, 40:280]
    _, first_metadata = context.get_projected(7, source, target, frame=frame, target_crop=crop)
    feature_calls = []

    def feature():
        feature_calls.append(1)
        return {"generation": len(feature_calls)}

    context.cached_feature(7, target, "mask-dependent-v1", feature)
    frame[20, 30] = 31  # Outside the target ROI, inside the padded source.
    context.cached_feature(7, target, "mask-dependent-v1", feature)
    _, second_metadata = context.get_projected(7, source, target, frame=frame, target_crop=crop)
    assert len(feature_calls) == 2
    assert len(mask_calls) == 2
    assert first_metadata["projection"]["source_pixels_digest"] != second_metadata["projection"]["source_pixels_digest"]
    assert first_metadata["projection"]["target_pixels_digest"] == second_metadata["projection"]["target_pixels_digest"]
    context.cached_feature(7, target, "mask-dependent-v1", feature)
    assert len(feature_calls) == 3


def test_full_frame_overlap_keeps_exact_target_segmentation_and_skips_projection(mask_calls):
    frame = _frame()
    context = RuntimeMaskContext(frame)
    model = _quality(_parts((40, 40)), mode="full_frame")
    model.predict_full_frame(
        frame, [ParentAnchor(7, (40, 40, 280, 140), .99), ParentAnchor(8, (45, 40, 285, 140), .99)],
        stabilize=False, grade_track_ids={7}, mask_context=context,
    )
    assert len(mask_calls) == 1
    assert context.diagnostics()["projection_calls"] == 0
    assert mask_calls[0].shape == (100, 240, 3)


def test_all_seven_saved_grade_records_are_identical_with_projected_texture_masks(mask_calls):
    # Score replay uses a synthetic image to isolate the mask optimization from
    # model inference. It does not validate biological segmentation accuracy.
    fixture = Path(__file__).parent / "fixtures" / "fish-inspection-upload-all.csv"
    with fixture.open(encoding="utf-8-sig", newline="") as source:
        records = [json.loads(row["Complete fish event"]) for row in csv.DictReader(source)]
    frame = _frame()
    crop, bounds = crop_fish(frame, (40, 40, 280, 140))
    canonical_boxes = {part.region: part.bbox for part in _parts()}
    for record in records:
        saved = record["analysis"]
        config = GradingConfig(**{
            key: value for key, value in saved["grading_config"].items()
            if key in GradingConfig.__dataclass_fields__
        })
        parts = [PartDetection.from_source_class(
            part["source_class_id"], part["confidence"], canonical_boxes[part["region"]],
        ) for part in record["parts"]]
        exact_context = RuntimeMaskContext(frame)
        projected_context = RuntimeMaskContext(frame)
        exact_mask, exact_metadata = exact_context.get(record["id"], bounds)
        projected_mask, projected_metadata = projected_context.get_projected(
            record["id"], measurement_crop_bounds(frame, (40, 40, 280, 140)), bounds,
            frame=frame, target_crop=crop,
        )
        before = WeightedGradingEngine(config).evaluate(
            record["id"], crop, parts, stabilize=False, frame_quality=saved["frame_quality"],
            texture_mask=exact_mask, texture_mask_metadata=exact_metadata,
        ).to_dict()
        after = WeightedGradingEngine(config).evaluate(
            record["id"], crop, parts, stabilize=False, frame_quality=saved["frame_quality"],
            texture_mask=projected_mask, texture_mask_metadata=projected_metadata,
        ).to_dict()
        assert before["final_grade"] == after["final_grade"] == record["quality"]
        for key in ("final_score", "weighted_scores", "effective_weights", "original_weight_coverage", "reason_codes", "adjustments", "color"):
            assert after[key] == before[key]
        assert after["weighted_scores"] == saved["weighted_scores"]
        assert after["final_score"] == saved["final_score"]
    assert len(records) == 7
