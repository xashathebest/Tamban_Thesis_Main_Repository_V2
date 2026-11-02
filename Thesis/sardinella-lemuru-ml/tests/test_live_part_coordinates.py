"""Live event coordinates stay aligned while renderer inputs remain local."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig
from src.inference.fish_segmenter import FishSegmentation, SegmentPart
from src.inference.inspection_results import normalize_inspection_result
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds
from src.inference.yolo_quality_model import FishQualityObservation


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    model = SimpleNamespace(model=object(), weights_path=None, confidence_threshold=.5)
    state = InspectionState(TrackingConfig(line_position=.5))
    state.set_frame_size(400, 240)
    service = CameraInspectionService(state, model, camera_profile_path=tmp_path / "camera.yaml")
    service._frame_index = 17
    return service


def _observation(*, mode="crop", mask=None):
    part = PartDetection.from_source_class(0, .9, (10.25, 8.5, 60.5, 25.75), mask=mask)
    return FishQualityObservation(
        7, "Class A", .8, (part,), {"Class A": .8},
        {"final_grade": "Class A", "final_score": .8,
         "weighted_scores": {"Class A": .8, "Class B": 0, "Class C": 0, "Rejected": 0},
         "quality_inference": {"mode": mode}},
    )


@pytest.mark.parametrize("mode", ["crop", "full_frame"])
@pytest.mark.parametrize("origin", [(0, 0), (105, 70)])
def test_recorded_live_parts_translate_exact_native_crop_origin(service, mode, origin):
    result = _observation(mode=mode)
    original_analysis = deepcopy(result.analysis)
    x, y = origin
    bounds = CropBounds(x, y, x + 80, y + 40)
    detection = Detection(0, "Fish", .95, (x + 5, y + 5, x + 75, y + 35), 7)
    fresh = []

    service._record_quality_observation(detection, result, bounds, (40, 80, 3), fresh)

    stored = service._track_grades[7].to_dict()
    part = stored["parts"][0]
    assert part["bbox"] == [x + 10.25, y + 8.5, x + 60.5, y + 25.75]
    assert part["crop_local_bbox"] == list(result.parts[0].bbox)
    assert part["coordinate_space"] == "original_frame"
    assert part["source_class_id"] == result.parts[0].source_class_id
    assert part["confidence"] == .9
    assert stored["quality"] == result.quality
    assert stored["quality_confidence"] == result.quality_confidence
    assert stored["analysis"]["weighted_scores"] == result.analysis["weighted_scores"]
    assert result.analysis == original_analysis
    assert fresh[0][0].parts[0] is result.parts[0]
    assert service._latest_part_overlays[7][0].parts[0] is result.parts[0]
    assert result.parts[0].bbox == (10.25, 8.5, 60.5, 25.75)


def test_serialized_polygon_translates_but_original_and_overlay_polygon_remain_local(service):
    polygon = ((10.25, 8.5), (60.5, 8.5), (60.5, 25.75), (10.25, 25.75))
    result = _observation(mask=polygon)
    bounds = CropBounds(105, 70, 185, 110)
    detection = Detection(0, "Fish", .95, (110, 75, 180, 105), 7)
    fresh = []

    service._record_quality_observation(detection, result, bounds, (40, 80, 3), fresh)

    part = service._track_grades[7].parts[0]
    assert part["mask"] == [[x + 105, y + 70] for x, y in polygon]
    assert part["crop_local_mask"] == [list(point) for point in polygon]
    assert part["mask_coordinate_space"] == "original_frame"
    assert result.parts[0].mask == polygon
    assert fresh[0][0].parts[0].mask == polygon


def test_legacy_binary_masks_are_not_treated_as_polygon_vertices(service):
    mask = np.ones((40, 80), dtype=bool)
    legacy = SegmentPart(0, "A_body", "A", "Body", .9, (10, 8, 60, 26), mask)
    result = FishSegmentation(7, "A", .9, (legacy,), {"A": .9})
    detection = Detection(0, "Fish", .95, (110, 75, 180, 105), 7)
    fresh = []

    service._record_quality_observation(
        detection, result, CropBounds(105, 70, 185, 110), (40, 80, 3), fresh,
    )

    part = service._track_grades[7].parts[0]
    assert part["bbox"] == [115, 78, 165, 96]
    assert part["crop_local_bbox"] == [10, 8, 60, 26]
    assert "mask" not in part
    assert "crop_local_mask" not in part
    assert fresh[0][0].parts[0].mask is mask
    assert mask.all()


def test_counted_live_event_and_export_consumer_receive_original_frame_parts_once(service):
    result = _observation()
    for when, x in ((1.0, 105), (1.1, 215)):
        detection = Detection(0, "Fish", .95, (x + 5, 75, x + 75, 105), 7)
        service._record_quality_observation(
            detection, result, CropBounds(x, 70, x + 80, 110), (40, 80, 3), [],
        )
        service.state.tracking.update(
            [detection], (400, 240), timestamp=when, grades=service._track_grades,
        )

    events = service.state.tracking.archive_history()
    assert len(events) == 1
    event = events[0]
    expected_box = [225.25, 78.5, 275.5, 95.75]
    assert event["parts"][0]["bbox"] == expected_box
    assert event["parts"][0]["crop_local_bbox"] == [10.25, 8.5, 60.5, 25.75]
    assert event["bbox"] == [220, 75, 290, 105]
    normalized = normalize_inspection_result(event, frame_shape=(240, 400))
    assert normalized["parts"][0]["bbox"] == expected_box
    assert normalized["analysis"]["body_width"]["body_bbox"] == expected_box
    assert normalized["quality"] == event["quality"] == "Class A"
    assert normalized["quality_confidence"] == event["quality_confidence"] == .8
