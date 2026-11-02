"""Optional foreground failures cannot suppress model-backed weighted evidence."""

from types import SimpleNamespace

import cv2
import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig
from src.api.image_analysis import StillImageAnalyzer
from src.evaluation.fixbody_benchmark import PARENT, quality, scene
from src.inference.yolo_fish_detector import FishDetection


def _failed_foreground(monkeypatch):
    calls = []

    def fail(crop):
        calls.append(crop.shape)
        raise RuntimeError("Synthetic optional foreground failure")

    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", fail)
    return calls


def _assert_grade_preserved(actual, expected):
    assert actual["quality"] == expected["quality"]
    assert actual["quality_confidence"] == expected["quality_confidence"]
    assert actual["parts"] == expected["parts"]
    for field in ("weighted_scores", "effective_weights", "original_weight_coverage", "reason_codes"):
        assert actual["analysis"][field] == expected["analysis"][field]
    assert actual["analysis"]["surface_damage"]["label"] == "No reliable evidence"
    assert actual["analysis"]["surface_damage"]["mask_validated_for_cracks"] is False
    assert actual["analysis"]["fish_geometry"]["fish_length_px"] is None
    assert actual["analysis"]["fish_geometry"]["used_for_grading"] is False


@pytest.mark.parametrize("mode", ("crop", "full_frame"))
def test_still_weighted_grade_survives_foreground_exception(mode, monkeypatch):
    def analyzer():
        detector = SimpleNamespace(model=object(), detect=lambda _: [FishDetection(PARENT, .98)])
        return StillImageAnalyzer(detector, quality(mode))

    expected = analyzer().analyze(scene("clean"))["fish"][0]
    calls = _failed_foreground(monkeypatch)
    result = analyzer().analyze(scene("clean"))
    actual = result["fish"][0]
    _assert_grade_preserved(actual, expected)
    assert actual["analysis"]["fish_mask"]["error_type"] == "RuntimeError"
    assert actual["analysis"]["supporting_image_measurements"]["texture"]["status"] == "unavailable"
    # Exact grading/damage ROI and padded metrology ROI each fail once, even
    # though all downstream diagnostics consult the same current-frame context.
    assert len(calls) == result["performance"]["mask_context"]["segmentation_calls"] == 2


@pytest.mark.parametrize("mode", ("crop", "full_frame"))
def test_live_weighted_grade_and_ids_survive_foreground_exception(mode, monkeypatch, tmp_path):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")

    def service(name):
        detection = Detection(0, "Fish", .98, PARENT, 7)
        detector = SimpleNamespace(model=object(), weights_path=None, confidence_threshold=.5,
                                   predict=lambda _: [detection])
        state = InspectionState(TrackingConfig(line_position=.9))
        return CameraInspectionService(
            state, detector, quality_model=quality(mode), quality_inference_mode=mode,
            quality_interval=1, camera_profile_path=tmp_path / name,
        )

    baseline = service("baseline.yaml")
    for _ in range(2):
        baseline.process_frame(scene("clean"), cv2)
    expected = baseline._track_grades[7].to_dict()
    calls = _failed_foreground(monkeypatch)
    current = service("failure.yaml")
    for _ in range(2):
        annotated = current.process_frame(scene("clean"), cv2)
        assert annotated.shape == (320, 480, 3)
    actual = current._track_grades[7].to_dict()
    _assert_grade_preserved(actual, expected)
    assert actual["track_id"] == expected["track_id"] == 7
    assert current._model2_failure_count == 0
    assert actual["analysis"]["model2_available"] is True
    assert actual["analysis"]["fish_mask"]["error_type"] == "RuntimeError"
    assert len(calls) == 4  # two distinct ROIs in each fresh frame context
    assert current._frame_mask_context.diagnostics()["segmentation_calls"] == 2
