"""Live diagnostics use their declared coordinate space exactly once."""
from types import SimpleNamespace

import numpy as np
import pytest

from src.api.camera import CameraInspectionService
from src.inference.preprocessing import CropBounds
from src.inference.yolo_quality_model import FishQualityObservation


def draw(debug):
    display = {"part_overlays": False, "outlines": False, "features": False,
               "model2_raw_boxes": True, "model2_associated_boxes": False,
               "model2_rejected_boxes": False, "model2_labels": False}
    service = CameraInspectionService.__new__(CameraInspectionService)
    service.state = SimpleNamespace(current_display_settings=lambda: display)
    service.debug_enabled = True
    service._frame_index = 37
    rectangles = []
    renderer = SimpleNamespace(rectangle=lambda image, start, end, *args: rectangles.append((start, end)))
    observation = FishQualityObservation(1, None, None, (), {}, {"model2_debug": debug})
    service._annotate_quality(np.zeros((200, 300, 3), np.uint8),
                              [(observation, CropBounds(40, 20, 200, 120))], renderer)
    return rectangles


def test_native_debug_box_is_not_translated_by_parent_crop_again():
    boxes = draw({"coordinate_space": "original_frame", "frame_id": 37,
                  "frame_width_px": 300, "frame_height_px": 200,
                  "raw_detections": [{"bbox": [100, 60, 130, 80]}]})
    assert boxes == [((100, 60), (130, 80))]


def test_crop_local_debug_box_keeps_the_original_translation_contract():
    assert draw({"coordinate_space": "crop_local", "raw_detections": [{"bbox": [10, 12, 40, 35]}]}) == [((50, 32), (80, 55))]


def test_item_coordinate_space_overrides_layer_default():
    assert draw({"coordinate_space": "crop_local", "raw_detections": [
        {"bbox": [100, 60, 130, 80], "coordinate_space": "original_frame"}]}) == [((100, 60), (130, 80))]


@pytest.mark.parametrize("change", [
    {"frame_id": 36}, {"frame_width_px": 301}, {"frame_height_px": 201},
    {"coordinate_space": "unverified_crop"},
])
def test_unknown_or_wrong_source_debug_coordinates_are_withheld(change):
    debug = {"coordinate_space": "original_frame", "frame_id": 37,
             "frame_width_px": 300, "frame_height_px": 200,
             "raw_detections": [{"bbox": [100, 60, 130, 80]}], **change}
    assert draw(debug) == []


@pytest.mark.parametrize("bad", [None, "bad", float("nan"), float("inf")])
def test_malformed_debug_coordinates_cannot_break_the_live_renderer(bad):
    assert draw({"coordinate_space": "original_frame", "raw_detections": [{"bbox": [bad, 60, 130, 80]}]}) == []
