"""Native evidence survives contextual crops, diagnostics and mask previews."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.api.image_analysis import StillImageAnalyzer
from src.api.segmentation_preview import generate_mask_preview
from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import crop_assigned_evidence, crop_fish
from src.inference.yolo_fish_detector import FishDetection
from src.inference.yolo_quality_model import YoloQualityModel


def part(class_id, box, confidence=.9):
    return PartDetection.from_source_class(class_id, confidence, box)


PARENT = (40., 40., 240., 100.)
OWNED = [part(1, (39, 50, 89, 80)), part(0, (100, 48, 180, 92)), part(2, (210, 50, 235, 80))]
DISTANT = part(2, (300, 50, 320, 80))
LOW = part(4, (320, 110, 340, 130), .18)


def quality_model():
    quality = YoloQualityModel(Path("crop-provenance-test-only.pt"), device="cpu", model_id="test-only",
                               quality_inference_mode="full_frame", roi_padding=0,
                               grading_engine=WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1")))
    quality.model = object()
    calls = []
    def infer(frame):
        calls.append(frame.shape)
        return [*OWNED, DISTANT], [*OWNED, DISTANT, LOW]
    quality._infer_parts = infer
    return quality, calls


def test_contextual_crop_preserves_the_owned_head_cut_by_parent_only_crop():
    frame = np.arange(160 * 400 * 3, dtype=np.uint8).reshape(160, 400, 3)
    _, old = crop_fish(frame, PARENT)
    old_head = YoloQualityModel._part_to_crop(OWNED[0], old.origin, (old.height, old.width, 3))
    assert old_head.bbox[0] + old.x1 == 40  # Confirm the previous one-pixel loss.
    crop, bounds = crop_assigned_evidence(frame, PARENT, [item.bbox for item in OWNED])
    assert bounds.x1 < 39 and bounds.x2 < DISTANT.bbox[0]
    assert np.array_equal(crop, frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2])
    translated = YoloQualityModel._part_to_crop(OWNED[0], bounds.origin, crop.shape)
    assert translated.bbox[0] + bounds.x1 == 39
    assert translated.bbox[2] + bounds.x1 == 89


@pytest.mark.parametrize("parent,owned", [
    ((0, 20, 200, 80), [(0, 30, 40, 60)]),
    ((40, 0, 100, 150), [(50, 0, 80, 30)]),
    ((40, 40, 120, 120), [(39, 45, 70, 75), (90, 90, 121, 121)]),
])
def test_context_crop_bounds_remain_native_for_frame_edge_and_diagonal_cases(parent, owned):
    crop, bounds = crop_assigned_evidence(np.zeros((160, 250, 3), np.uint8), parent, owned)
    assert 0 <= bounds.x1 < bounds.x2 <= 250
    assert 0 <= bounds.y1 < bounds.y2 <= 160
    for box in owned:
        assert bounds.x1 <= box[0] < box[2] <= bounds.x2
        assert bounds.y1 <= box[1] < box[3] <= bounds.y2
    assert crop.shape[:2] == (bounds.height, bounds.width)


def test_still_pipeline_keeps_full_raw_boxes_and_separates_postprocessing_from_ownership():
    quality, calls = quality_model()
    detector = SimpleNamespace(model=object(), detect=lambda frame: [FishDetection(PARENT, .95)])
    payload = StillImageAnalyzer(detector, quality).analyze(np.full((160, 400, 3), 100, np.uint8),
                                                         frame_id="native-1", segmentation_backend="geometry_only")
    fish = payload["fish"][0]
    assert calls == [(160, 400, 3)]  # Exactly one full-frame Model 2 call.
    assert fish["quality"] == "Class A"
    head = next(item for item in fish["parts"] if item["region"] == "Head")
    assert head["bbox"] == list(OWNED[0].bbox)
    assert fish["bbox"] == list(PARENT)
    association = fish["analysis"]["quality_inference"]["association"]
    assert association["coordinate_space"] == "original_frame"
    assert association["frame_id"] == "native-1"
    assert association["frame_width_px"] == 400
    assert association["clipping"]["context_expanded_for_owned_parts"] is True
    assert association["clipping"]["parent_box_frame_contact"] is False
    assigned = [row for row in association["parts"] if row["status"] == "ASSIGNED"]
    assert len(assigned) == 3
    assert all(not row["clipping"]["outside_analysis_crop"] for row in assigned)
    debug = fish["analysis"]["model2_debug"]
    assert debug["coordinate_space"] == "original_frame"
    assert debug["frame_id"] == "native-1"
    assert [row["bbox"] for row in debug["raw_detections"]] == [list(item.bbox) for item in [*OWNED, DISTANT, LOW]]
    assert [row["bbox"] for row in debug["selected_detections"]] == [list(item.bbox) for item in OWNED]
    assert debug["detector_selected_count"] == 4
    assert [row["bbox"] for row in debug["rejected_detections"]] == [list(LOW.bbox)]
    assert debug["rejected_detections"][0]["rejection_reason"] == "below_detector_confidence"
    assert debug["unassigned_detections"][0]["bbox"] == list(DISTANT.bbox)
    assert "pre_NMS_logits_unavailable" in debug["raw_scope"]


def test_image_edge_contact_is_distinct_from_analysis_crop_contact():
    quality, _ = quality_model()
    observation, _ = quality.predict_full_frame(np.full((160, 400, 3), 100, np.uint8),
                                               [ParentAnchor(1, (0, 40, 240, 100), .95)], stabilize=False, frame_id="edge")[1]
    # Input is deliberately too broad to establish silhouette clipping.
    clipping = observation.analysis["quality_inference"]["association"]["clipping"]
    assert clipping["parent_box_frame_contact"] is True
    assert clipping["analysis_crop_frame_contact"] is True
    assert clipping["native_silhouette_clipped"] is None
    assert "UG_OUT_OF_FRAME" not in observation.analysis["reason_codes"]


def test_mask_preview_reuses_context_and_keeps_native_anatomical_diagnostics():
    frame = np.full((80, 150, 3), 100, np.uint8)
    mask = np.zeros(frame.shape[:2], bool)
    mask[20:50, 20:100] = True
    report = {"mask_overlay": {"contours": [[[20, 20], [100, 20], [100, 50], [20, 50]]]},
              "ownership_status": "checks_passed_unvalidated"}
    provider = SimpleNamespace(frame_id="preview-native", candidates={1: {"mask": mask}},
                               service=SimpleNamespace(status=lambda: {}), report=lambda identity: report,
                               diagnostics=lambda: {})
    context = SimpleNamespace(_experimental=provider, is_for_frame=lambda candidate: candidate is frame)
    analysis = {key: {"evidence": key} for key in ("quality_inference", "model2_debug", "model1_detection")}
    result = generate_mask_preview(frame, [{"id": 1, "bbox": [10, 10, 120, 60], "parts": [], "analysis": analysis}],
                                   image_sha256="test-native", reused=True, mask_context=context)
    assert result["detector_snapshot_reused"] is True
    assert result["source"]["frame_id"] == "preview-native"
    for key, expected in analysis.items():
        assert result["fish"][0]["analysis"][key] == expected


def test_box_border_contact_does_not_claim_the_missing_head_is_outside_image():
    quality, _ = quality_model()
    body = part(0, (70, 48, 160, 92))
    quality._infer_parts = lambda frame: ([body], [body])
    observation, _ = quality.predict_full_frame(np.full((160, 400, 3), 100, np.uint8),
                                               [ParentAnchor(1, (0, 40, 240, 100), .95)], stabilize=False, frame_id="missing-edge")[1]
    assert observation.quality is None
    assert "UG_MISSING_PART_EVIDENCE" in observation.analysis["reason_codes"]
    assert "UG_OUT_OF_FRAME" not in observation.analysis["reason_codes"]
    assert observation.analysis["part_results"]["Head"]["visibility_state"] == "NOT_DETECTED"


def test_all_seven_csv_crops_preserve_the_three_previously_truncated_native_parts(tmp_path):
    from src.evaluation.evaluate_association_repairs import csv_scene
    scene = csv_scene(image_root=tmp_path)
    parents = [ParentAnchor(item["id"], tuple(item["bbox"]), item["confidence"])
               for item in scene["detections"]]
    parts = [part(item["source_class_id"], tuple(item["bbox"]), item["confidence"]) for item in scene["parts"]]
    associations = associate_parts_to_parents(parts, parents)
    frame = np.zeros((2160, 3840, 3), np.uint8)
    truncated = []
    for parent in parents:
        owned = [row.part for row in associations if row.status == "ASSIGNED" and row.track_id == parent.track_id]
        _, old = crop_fish(frame, parent.bbox)
        crop, bounds = crop_assigned_evidence(frame, parent.bbox, [item.bbox for item in owned])
        for item in owned:
            old_local = YoloQualityModel._part_to_crop(item, old.origin, (old.height, old.width, 3))
            old_native = np.array(old_local.bbox) + np.array([old.x1, old.y1, old.x1, old.y1])
            if not np.allclose(old_native, item.bbox, rtol=0, atol=.000001):
                truncated.append((parent.track_id, item.region))
            local = YoloQualityModel._part_to_crop(item, bounds.origin, crop.shape)
            native = np.array(local.bbox) + np.array([bounds.x1, bounds.y1, bounds.x1, bounds.y1])
            assert native == pytest.approx(item.bbox, abs=.000001)
    assert sorted(truncated) == [(3, "Body"), (3, "Head"), (5, "Body")]
