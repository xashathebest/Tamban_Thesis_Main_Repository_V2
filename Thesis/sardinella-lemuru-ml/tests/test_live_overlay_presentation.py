"""Live JPEGs retain annotations while models/raw preview retain original pixels."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState
from test_camera_exposure_integration import Capture, Detector, Quality, wait_until


def test_camera_worker_publishes_actual_annotated_result_and_keeps_model_inputs_original(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    state, detector, quality = InspectionState(), Detector(), Quality()
    service = CameraInspectionService(state, detector, quality_model=quality, quality_interval=1,
                                      camera_profile_path=tmp_path / "camera.yaml")
    original = np.full((48, 64, 3), (28, 55, 82), np.uint8)
    untouched = original.copy()
    class WorkerCapture(Capture):
        def read(self):
            service._stop_event.wait(.04)
            return True, original.copy()
    capture = WorkerCapture()
    rendered, encoded, raw, jpeg_bytes = [], [], [], []
    process = service.process_frame
    encode = cv2.imencode
    def process_frame(frame, cv):
        annotated = process(frame, cv)
        rendered.append(annotated.copy())
        return annotated
    def encode_frame(extension, frame, options):
        encoded.append(frame.copy())
        success, buffer = encode(extension, frame, options)
        if success:
            jpeg_bytes.append(buffer.tobytes())
        return success, buffer
    monkeypatch.setattr(service, "_open_capture", lambda _: (capture, "DSHOW"))
    monkeypatch.setattr(service.camera_controls, "initialize_camera_settings", lambda: {"success": True})
    monkeypatch.setattr(service, "process_frame", process_frame)
    monkeypatch.setattr(service.raw_preview, "offer", lambda frame, _: raw.append(frame.copy()))
    monkeypatch.setattr(cv2, "imencode", encode_frame)
    service._models_prepared = True
    published = None
    try:
        assert service.start()
        wait_until(lambda: state.frame()[0] is not None)
        published = state.frame()[0]
    finally:
        service.stop(timeout=4)
    assert detector.frames and quality.crops and rendered and encoded and raw
    assert len(encoded) == len(rendered)
    for expected, actual in zip(rendered, encoded):
        np.testing.assert_array_equal(actual, expected)
        assert np.any(actual != untouched), "Inspection line and fish annotations must reach JPEG encoding"
    assert published in jpeg_bytes, "The encoded annotated JPEG must actually reach the live stream state"
    assert all(np.array_equal(frame, untouched) for frame in detector.frames + raw)
    assert all(np.array_equal(crop, untouched[8:40, 8:56]) for crop in quality.crops)
    np.testing.assert_array_equal(original, untouched)
    assert capture.released and not capture.writes


@pytest.fixture
def drawing(tmp_path, monkeypatch):
    state = InspectionState()
    # Rendering has existing evidence; no model or damage operation is needed.
    service = CameraInspectionService(state, Detector(), quality_model=Quality(),
                                      camera_profile_path=tmp_path / "camera.yaml")
    state.set_display_settings({"confidence": False, "features": False})
    monkeypatch.setattr(state.tracking, "active_tracks", lambda: [
        {"track_id": 1, "quality": "Class B", "counted": False},
        {"track_id": 2, "quality": "Class C", "counted": False},
    ])
    detections = [Detection(0, "Fish", .99, (40, 200, 240, 350), 1),
                  Detection(0, "Fish", .99, (500, 200, 700, 350), 2)]
    return service, detections, np.full((500, 1000, 3), 35, np.uint8)


def test_live_boxes_and_labels_use_engine_grade_colors(drawing, monkeypatch):
    service, detections, original = drawing
    labels = []
    module = importlib.import_module("src.api.camera")
    draw_label = module._draw_readable_label
    def label(image, text, x, y, color, cv, occupied=None):
        labels.append((text, color))
        draw_label(image, text, x, y, color, cv, occupied)
    monkeypatch.setattr(module, "_draw_readable_label", label)
    annotated = service._annotate(original, detections, cv2)
    # Assert visible channel semantics rather than reusing the palette under test.
    blue = annotated[275, 40]
    orange = annotated[275, 500]
    assert int(blue[0]) > int(blue[1]) > int(blue[2])
    assert int(orange[2]) > int(orange[1]) > int(orange[0])
    assert "Fish #1" in labels[0][0] and "Class B" in labels[0][0]
    assert "Fish #2" in labels[1][0] and "Class C" in labels[1][0]
    np.testing.assert_array_equal(blue, labels[0][1])
    np.testing.assert_array_equal(orange, labels[1][1])
    assert np.all(original == 35)


def test_same_grade_masks_keep_distinct_identity_fills_and_separate_review_notes(drawing, monkeypatch):
    service, detections, original = drawing
    service.state.set_display_settings({"fish_masks": True})
    monkeypatch.setattr(service.state.tracking, "active_tracks", lambda: [
        {"track_id": 1, "quality": "Class B", "counted": False},
        {"track_id": 2, "quality": "Class B", "counted": False},
    ])
    masks = {}
    for detection in detections:
        mask = np.zeros(original.shape[:2], dtype=bool)
        left, top, right, bottom = detection.bbox
        mask[top + 10:bottom - 10, left + 10:right - 10] = True
        masks[detection.track_id] = {"mask": mask}
    provider = SimpleNamespace(candidates=masks, is_current=lambda: True,
                               report=lambda fish_id: {"engineering_checks_passed": fish_id == 1})
    service._frame_mask_context = SimpleNamespace(_experimental=provider, is_for_frame=lambda frame: frame is original)
    text = []
    put_text = cv2.putText
    def draw_text(image, value, *args):
        text.append(value)
        return put_text(image, value, *args)
    monkeypatch.setattr(cv2, "putText", draw_text)
    annotated = service._annotate(original, detections, cv2)
    assert not np.array_equal(annotated[275, 100], annotated[275, 600]), "Fish ID, rather than shared grade, distinguishes mask fills"
    np.testing.assert_array_equal(annotated[275, 40], annotated[275, 500])
    primary = [label for label in text if "Fish #" in label]
    assert len(primary) == 2 and all("Class B" in label for label in primary)
    assert all("Requires Review" not in label and "Estimated" not in label for label in primary)
    assert "Mask: Estimated" in text and "Mask: Requires Review" in text
    assert np.all(original == 35)
