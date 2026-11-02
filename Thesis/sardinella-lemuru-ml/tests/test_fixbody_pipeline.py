"""Cross-stage diagnostic identity, overlays, and grade-preservation checks."""
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest

from src.api.image_analysis import StillImageAnalyzer, VideoUploadAnalyzer, _UploadFish
from src.evaluation.fixbody_benchmark import quality, scene, PARENT
from src.inference import frame_diagnostics
from src.inference.fish_geometry import measure_fish_geometry
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, RuntimeMaskContext
from src.inference.yolo_fish_detector import FishDetection


def analyzer(mode="full_frame"):
    detector = SimpleNamespace(model=object(), detect=lambda _: [FishDetection(PARENT, .98)])
    return StillImageAnalyzer(detector, quality(mode))


def test_shared_fullframe_texture_has_provenance_without_changing_weighted_grade():
    result = analyzer().analyze(scene("clean"))
    fish = result["fish"][0]
    assert fish["analysis"]["weighted_scores"] == {"Class A": .59, "Class B": .24, "Class C": 0., "Rejected": 0.}
    texture = fish["analysis"]["supporting_image_measurements"]["texture"]
    assert texture["status"] == "measured"
    assert texture["mask_metadata"]["parent_track_id"] == fish["id"]
    assert texture["mask_metadata"]["coordinate_space"] == "crop_local_native_pixels"
    assert texture["mask_validated_for_cracks"] is False
    whole_source = fish["analysis"]["supporting_image_measurements"]["regions"]["Whole Fish"]["measurement_source"]
    assert "rectangular" in whole_source and "not validated" in whole_source
    assert result["performance"]["mask_context"]["cache_hits"] >= 1
    assert result["performance"]["total_processing_ms"] > 0


def test_diagnostic_damage_failure_does_not_turn_a_valid_grade_into_abstention(monkeypatch):
    baseline = analyzer().analyze(scene("clean"))["fish"][0]
    def fail(*args, **kwargs): raise RuntimeError("Synthetic diagnostic failure")
    monkeypatch.setattr(frame_diagnostics, "analyze_surface_damage", fail)
    fish = analyzer().analyze(scene("clean"))["fish"][0]
    assert fish["quality"] == baseline["quality"]
    assert fish["analysis"]["weighted_scores"] == baseline["analysis"]["weighted_scores"]
    assert fish["analysis"]["surface_damage"]["label"] == "No reliable evidence"
    assert fish["analysis"]["surface_damage"]["reason"] == "surface_diagnostics_failed"


def test_damage_cache_respects_context_flags_and_uses_correct_original_roi(monkeypatch):
    frame = scene("dark_line")
    bounds = CropBounds(90, 110, 390, 210)
    context = RuntimeMaskContext(frame, frame_id=17)
    calls = []
    original = frame_diagnostics.analyze_surface_damage
    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(frame_diagnostics, "analyze_surface_damage", count)
    first = frame_diagnostics.parent_damage(frame, bounds, 1, mask_context=context, frame_id=17)
    again = frame_diagnostics.parent_damage(frame, bounds, 1, mask_context=context, frame_id=17)
    assert len(calls) == 1 and first["locations"] == again["locations"]
    for location in first["locations"]:
        assert location["frame_bbox"][0] == location["x"] + bounds.x1
        assert location["frame_bbox"][1] == location["y"] + bounds.y1
    rejected = frame_diagnostics.parent_damage(frame, bounds, 1, mask_context=context, frame_id=17,
                                               parent_context={"overlapping": True})
    assert len(calls) == 2
    assert rejected["label"] == "No reliable evidence" and rejected["locations"] == []


def test_damage_overlay_uses_damage_bounds_even_when_grading_crop_has_padding():
    image = np.full((100, 120, 3), 100, np.uint8)
    overlay = np.zeros((20, 30), np.uint8)
    overlay[5, 7] = 255
    fish = _UploadFish(1, (40, 30, 70, 50), .9, None, CropBounds(30, 20, 80, 60),
                       {"status": "suspected", "overlay_mask": overlay}, CropBounds(40, 30, 70, 50))
    StillImageAnalyzer._draw_damage(image, fish)
    assert image[35, 47, 2] > 100
    assert np.array_equal(image[25, 37], (100, 100, 100))


def test_quality_overlay_uses_quality_crop_origin_not_damage_crop_origin():
    image = np.zeros((100, 120, 3), np.uint8)
    part = PartDetection.from_source_class(0, .9, (4, 8, 16, 18))
    fish = _UploadFish(1, (40, 30, 70, 50), .9, SimpleNamespace(parts=(part,)),
                       CropBounds(30, 20, 80, 60), None, CropBounds(40, 30, 70, 50))
    StillImageAnalyzer._draw_quality(image, fish)
    assert image[28, 34].any()
    assert not image[48, 54].any()


def test_uploaded_body_polygon_uses_the_same_frame_origin_as_its_box():
    part = PartDetection.from_source_class(0, .9, (4, 8, 16, 18), mask=((4, 8), (16, 8), (16, 18)))
    observation = SimpleNamespace(parts=(part,), analysis={}, quality="Class A", quality_confidence=.9)
    fish = _UploadFish(1, (40, 30, 70, 50), .9, observation, CropBounds(30, 20, 80, 60), None, CropBounds(40, 30, 70, 50))
    payload = analyzer()._fish_payload(fish, 120, 100)
    assert payload["parts"][0]["bbox"] == [34, 28, 46, 38]
    assert payload["parts"][0]["mask"] == [[34, 28], [46, 28], [46, 38]]
    assert payload["parts"][0]["mask_coordinate_space"] == "original_frame"


@pytest.mark.parametrize("angle", (0, 30, 90))
def test_geometry_overlay_axes_keep_native_frame_coordinates(angle):
    mask = np.zeros((240, 240), np.uint8)
    cv2.ellipse(mask, (120, 120), (80, 25), angle, 0, 360, 1, -1)
    body = PartDetection.from_source_class(0, .95, (82, 82, 158, 158))
    geometry = measure_fish_geometry(mask, [body], parent_bbox=(125, 125, 315, 315),
                                    crop_bounds=CropBounds(100, 100, 340, 340), frame_shape=(450, 450, 3),
                                    association_reliable=True)
    assert geometry["status"] == "measured", geometry["reasons"]
    visual = geometry["visualization"]
    assert visual["coordinate_space"] == "original_frame"
    assert np.linalg.norm(np.mean(visual["principal_axis"], axis=0) - np.array((220, 220))) < 3
    assert np.linalg.norm(np.subtract(*visual["width_axis"])) == pytest.approx(geometry["max_body_width_px"] - 1, abs=1)
    image = np.zeros((450, 450, 3), np.uint8)
    frame_diagnostics.draw_geometry(image, geometry)
    assert image.any()
    rejected = {**geometry, "status": "unreliable"}
    blank = np.zeros_like(image)
    frame_diagnostics.draw_geometry(blank, rejected)
    assert not blank.any()


def test_video_matching_never_assigns_two_detections_to_one_track_in_a_frame(monkeypatch):
    class Capture:
        def __init__(self, path): self.index = 0
        def isOpened(self): return True
        def get(self, prop): return 2 if prop == cv2.CAP_PROP_FRAME_COUNT else 5
        def read(self):
            self.index += 1
            return (True, np.zeros((80, 140, 3), np.uint8)) if self.index <= 2 else (False, None)
        def release(self): pass
    class Analyzer:
        def __init__(self): self.calls = 0
        def analyze(self, frame):
            self.calls += 1
            fish = [{"id": i, "bbox": box, "quality": "Class B", "detector_confidence": .9,
                     "quality_confidence": .6, "analysis": {"weighted_scores": {"Class B": .6}}}
                    for i, box in enumerate(((10, 10, 110, 50), (15, 10, 115, 50)), 1)]
            return {"fish": fish, "annotated_image": "data:image/jpeg;base64,synthetic"}
    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    result = VideoUploadAnalyzer(Analyzer()).analyze(Path("scripted.mp4"), lambda *_: None)
    assert result["frames_processed"] == 2
    assert [fish["id"] for fish in result["fish"]] == [1, 2]
    assert [fish["analysis"]["inspection_source"]["video_track_id"] for fish in result["fish"]] == [1, 2]
    assert result["quality_counters"]["Class B"] == 2


def test_video_global_matching_does_not_consume_a_neighbors_only_valid_match(monkeypatch):
    class Capture:
        def __init__(self, path): self.index = 0
        def isOpened(self): return True
        def get(self, prop): return 2 if prop == cv2.CAP_PROP_FRAME_COUNT else 5
        def read(self):
            self.index += 1
            return (True, np.zeros((80, 140, 3), np.uint8)) if self.index <= 2 else (False, None)
        def release(self): pass
    class Analyzer:
        def __init__(self): self.calls = 0
        def analyze(self, frame):
            self.calls += 1
            boxes = ((10, 10, 60, 40), (40, 10, 90, 40)) if self.calls == 1 else ((25, 10, 75, 40), (10, 10, 55, 40))
            return {"fish": [{"id": index, "bbox": box, "quality": "Class B", "quality_confidence": .6,
                              "detector_confidence": .8 + .05 * self.calls,
                              "analysis": {"weighted_scores": {"Class B": .6}}}
                             for index, box in enumerate(boxes, 1)], "annotated_image": "synthetic"}
    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    result = VideoUploadAnalyzer(Analyzer()).analyze(Path("scripted.mp4"), lambda *_: None)
    assert result["fish_detected"] == 2
    assert [fish["source_detection_id"] for fish in result["fish"]] == [2, 1]
    assert result["frame_detection_counts"] == [{"frame_index": 0, "fish_detected": 2}, {"frame_index": 1, "fish_detected": 2}]
