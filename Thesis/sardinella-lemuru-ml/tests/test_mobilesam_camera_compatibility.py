"""Experimental live masks follow Model 2 cadence and native tracked identity."""
from contextlib import contextmanager
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig
from src.evaluation.fixbody_benchmark import PARENT, quality, scene


class Service:
    def __init__(self):
        self.frames = []
        self.prompts = []

    @contextmanager
    def open_frame(self, image, key):
        self.frames.append((key, image.copy()))
        self.image, self.key = image, key
        self.frame_prompts = 0
        yield self

    def predict(self, parent, box, **options):
        self.prompts.append((self.key, parent, tuple(box)))
        self.frame_prompts += 1
        mask = np.zeros(self.image.shape[:2], np.uint8)
        cv2.ellipse(mask, (240, 160), (140, 40), 0, 0, 360, 1, -1)
        return {"status": "candidate", "parent_id": parent, "mask": mask.astype(bool), "score": .99,
                "provenance": {"backend": "mobilesam_experimental", "parent_id": parent,
                    "frame_key": self.key, "coordinate_space": "original_frame", "mask_shape": list(mask.shape),
                    "original_bbox_global": list(box), "prompt_bbox_global": list(box)}}

    def diagnostics(self):
        return {"embedding_calls": 1, "prompt_calls": self.frame_prompts}


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setenv("LEMURU_DEBUG_INFERENCE", "false")
    monkeypatch.setenv("LEMURU_RUNTIME_DIAGNOSTICS", "false")
    monkeypatch.setenv("FISH_RUNTIME_TELEMETRY", "1")
    def create(backend="mobilesam_experimental"):
        monkeypatch.setenv("SEGMENTATION_BACKEND", backend)
        ids = [7]
        detector = SimpleNamespace(model=object(), weights_path=None, confidence_threshold=.5,
            last_inference_seconds=.001,
            predict=lambda _: [Detection(0, "Fish", .98, PARENT, identity) for identity in ids])
        instance = CameraInspectionService(
            InspectionState(TrackingConfig(line_position=.9)), detector,
            quality_model=quality("full_frame"), quality_inference_mode="full_frame", quality_interval=3,
            camera_profile_path=tmp_path / "camera-profile.yaml")
        return instance, ids
    return create


@pytest.fixture
def fake_sam(monkeypatch):
    service = Service()
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    def prohibited(*args, **kwargs):
        raise AssertionError("Live MobileSAM must not also invoke GrabCut")
    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", prohibited)
    monkeypatch.setattr("src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", prohibited)
    return service


def test_live_sam_runs_only_on_scheduled_quality_frames_and_retains_provenance(build, fake_sam):
    service, _ = build()
    service.process_frame(scene("clean"), cv2)
    first = service._track_grades[7].analysis["segmentation"]
    assert first["parent_track_id"] == 7 and first["frame_id"] == 1
    assert first["mask_overlay"]["frame_id"] == 1
    assert first["used_for_grading"] is False
    assert first["validation_status"] == "Not validated"
    assert len(fake_sam.frames) == 1
    json.dumps(first, allow_nan=False)
    for frame_id in (2, 3):
        service.process_frame(scene("clean"), cv2)
        assert len(fake_sam.frames) == 1
        assert service._frame_mask_context.diagnostics()["grabcut_executions"] == 0
        assert service._frame_mask_context.diagnostics()["experimental_segmentation"]["prompt_calls"] == 0
        assert service._track_grades[7].analysis["segmentation"] == first
        assert service._frame_damage_results == {}
        assert service.runtime_diagnostics()["frame_performance"]["frame_id"] == frame_id
    service.process_frame(scene("clean"), cv2)
    assert len(fake_sam.frames) == 2
    assert [row[1] for row in fake_sam.prompts] == [7, 7]
    assert service._track_grades[7].analysis["segmentation"]["frame_id"] == 4
    assert service._frame_mask_context.diagnostics()["grabcut_executions"] == 0


def test_new_live_fish_id_cannot_reuse_previous_candidate_even_with_same_pixels(build, fake_sam):
    service, ids = build()
    image = scene("clean")
    service.process_frame(image.copy(), cv2)
    old = service._track_grades[7].analysis["segmentation"]
    ids[:] = [8]
    service.process_frame(image.copy(), cv2)
    current = service._track_grades[8].analysis["segmentation"]
    assert [row[1] for row in fake_sam.prompts] == [7, 8]
    assert len(fake_sam.frames) == 2
    assert current["parent_track_id"] == current["provenance"]["parent_id"] == 8
    assert current["frame_id"] == current["mask_overlay"]["frame_id"] == 2
    assert current["provenance"]["frame_key"] != old["provenance"]["frame_key"]
    assert current["provenance"]["prompt_bbox_global"] == list(PARENT)


def test_live_neighbor_without_track_id_competes_for_masks_without_being_graded(build, fake_sam):
    service, ids = build()
    ids.append(None)
    service.process_frame(scene("clean"), cv2)
    assert [row[1] for row in fake_sam.prompts] == [7, -1]
    assert len(fake_sam.frames) == 1
    assert set(service._track_grades) == {7}
    report = service._track_grades[7].analysis["segmentation"]
    assert report["engineering_checks_passed"] is False
    assert -1 in report["ownership"]["conflicting_parent_ids"]
    assert "overlapping_mask_ownership_conflict" in report["reasons"]
    assert report["used_for_grading"] is False


def test_live_optional_sam_cannot_change_weighted_grade(build, fake_sam):
    baseline, _ = build("geometry_only")
    baseline.process_frame(scene("clean"), cv2)
    expected = baseline._track_grades[7]
    experimental, _ = build()
    experimental.process_frame(scene("clean"), cv2)
    actual = experimental._track_grades[7]
    assert actual.quality == expected.quality
    assert actual.quality_confidence == expected.quality_confidence
    assert actual.parts == expected.parts
    for field in ("final_grade", "final_score", "weighted_scores", "effective_weights"):
        assert actual.analysis[field] == expected.analysis[field]
    assert actual.analysis["surface_damage"]["used_for_grading"] is False
    assert actual.analysis["fish_geometry"]["fish_length_cm"] is None
    assert actual.analysis["fish_geometry"]["used_for_grading"] is False


def test_camera_without_backend_override_keeps_grabcut_and_never_loads_sam(build, monkeypatch):
    service, _ = build()
    monkeypatch.delenv("SEGMENTATION_BACKEND")
    def prohibited():
        raise AssertionError("Default camera must not load MobileSAM")
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", prohibited)
    service.process_frame(scene("clean"), cv2)
    context = service._frame_mask_context.diagnostics()
    assert context["segmentation_backend"] == "opencv_cpu_grabcut"
    assert context["experimental_segmentation"] == {}
    assert context["grabcut_executions"] > 0
    assert "segmentation" not in service._track_grades[7].analysis

