"""Optional native-frame candidates cannot alter the established verdict."""
from contextlib import contextmanager
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from src.inference.fish_geometry import PhysicalCalibration
from src.inference.fish_geometry_pipeline import analyze_fish_geometry
from src.inference.frame_diagnostics import parent_damage
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, RuntimeMaskContext
from src.inference.yolo_quality_model import YoloQualityModel


PARENTS = (ParentAnchor(1, (20, 30, 280, 90), .99), ParentAnchor(2, (340, 30, 600, 90), .98))
BOUNDS = CropBounds(20, 30, 280, 90)


def parts():
    return [PartDetection.from_source_class(class_id, confidence, (x1 + shift, y1, x2 + shift, y2))
            for shift in (0, 320) for class_id, confidence, x1, y1, x2, y2 in
            ((0, .9, 90, 38, 215, 82), (1, .8, 30, 47, 75, 73))]


class Service:
    """Native masks stand in for the optional decoder, never expert labels."""
    def __init__(self, mode="normal"):
        self.mode = mode
        self.frames = []
        self.prompts = []

    @contextmanager
    def open_frame(self, frame, key):
        self.frames.append((frame, key))
        self.frame, self.key = frame, key
        yield self

    def predict(self, parent, box, **options):
        self.prompts.append((parent, tuple(box), options))
        if self.mode == "failed_first" and parent == 1:
            raise RuntimeError("One decoder prompt failed")
        if self.mode == "unavailable":
            return {"status": "unavailable", "reason": "Missing optional checkpoint", "mask": None}
        mask = np.zeros(self.frame.shape[:2], np.uint8)
        for shift in ((0, 320) if self.mode == "merged" else (0 if parent == 1 else 320,)):
            cv2.ellipse(mask, (150 + shift, 60), (120, 22), 0, 0, 360, 1, -1)
        return {"status": "candidate", "parent_id": parent, "mask": mask.astype(bool), "score": .999,
                "shared_embedding_ms": 12., "prompt_ms": 2.,
                "provenance": {"backend": "mobilesam_experimental", "parent_id": parent,
                    "frame_key": self.key, "coordinate_space": "original_frame", "mask_shape": list(mask.shape),
                    "original_bbox_global": list(box), "prompt_bbox_global": list(box),
                    "checkpoint_sha256": "a" * 64}}

    def diagnostics(self):
        return {"embedding_calls": 1, "prompt_calls": len(self.prompts)}


@pytest.fixture
def frame():
    return np.random.default_rng(8).integers(30, 220, (120, 640, 3), dtype=np.uint8)


@pytest.fixture(autouse=True)
def forbid_grabcut(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("Experimental/geometry-only execution must not also run GrabCut")
    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", prohibited)
    monkeypatch.setattr("src.inference.fish_geometry_pipeline.generate_runtime_fish_mask", prohibited)


def context(frame, service, monkeypatch):
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    return RuntimeMaskContext(frame, frame_id="native-1", backend="mobilesam_experimental")


def model():
    quality = YoloQualityModel(Path("fixture-parts.pt"), device="cpu", model_id="native-mask-test",
        quality_inference_mode="full_frame", grading_engine=WeightedGradingEngine(GradingConfig(
            grading_mode="tail_optional_v1", image_diagnostics_enabled=False)))
    quality.model = object()
    quality._infer_parts = lambda _: (parts(), parts())
    return quality


def test_full_frame_prompts_share_session_and_native_crop_without_point_invention(frame, monkeypatch):
    service = Service()
    masks = context(frame, service, monkeypatch)
    masks.prepare_instances(PARENTS, parts())
    first, metadata = masks.get(1, BOUNDS)
    assert first.shape == (60, 260)
    assert metadata["sampling"]["native_shape"] == [120, 640]
    assert metadata["sampling"]["estimated"] is True
    assert metadata["measurement_validated"] is False
    assert not first.flags.writeable
    assert len(service.frames) == 1
    assert [row[:2] for row in service.prompts] == [(p.track_id, p.bbox) for p in PARENTS]
    assert all("point_coords" not in options for _, _, options in service.prompts)
    masks.get(2, CropBounds(340, 30, 600, 90))
    masks.prepare_instances(PARENTS, parts())
    assert len(service.frames) == 1 and len(service.prompts) == 2
    report = masks.segmentation_report(1)
    assert report["checkpoint_sha256"] == "a" * 64
    assert report["engineering_checks_passed"] is True
    assert list(report["shadow_association"]["parents"]) == [1]
    assert all(row["proposed_track_id"] == 1 for row in report["shadow_association"]["parts"])
    assert report["used_for_grading"] is False
    json.dumps(report, allow_nan=False)
    assert masks.diagnostics()["grabcut_executions"] == 0


@pytest.mark.parametrize("mode", ["normal", "merged", "unavailable", "failed_first"])
def test_candidate_success_or_failure_never_changes_existing_weighted_grade(frame, monkeypatch, mode):
    baseline = model().predict_full_frame(frame, PARENTS, stabilize=False, frame_id="base",
                                         mask_context=RuntimeMaskContext(frame, backend="geometry_only"))
    masks = context(frame, Service(mode), monkeypatch)
    actual = model().predict_full_frame(frame, PARENTS, stabilize=False, frame_id="native-1", mask_context=masks)
    for identity in (1, 2):
        original, candidate = baseline[identity][0], actual[identity][0]
        assert candidate.quality == original.quality == "Class A"
        assert candidate.quality_confidence == original.quality_confidence
        for field in ("weighted_scores", "effective_weights", "original_grade", "final_grade"):
            assert candidate.analysis.get(field) == original.analysis.get(field)
        assert candidate.parts == original.parts
        geometry = candidate.analysis["fish_geometry"]
        assert geometry["fish_length_px"] is None
        assert geometry["fish_length_cm"] is None
        assert geometry["max_body_width_cm"] is None
        assert geometry["used_for_grading"] is False
        assert candidate.analysis["segmentation"]["used_for_grading"] is False
        if mode == "normal":
            assert geometry["sampling"]["mode"] == "mobilesam_candidate"
            assert geometry["candidate_measurements"]["fish_length_px"] == pytest.approx(241.)
            assert geometry["candidate_measurements"]["max_body_width_px"] == pytest.approx(45.)
            assert geometry["candidate_measurements"]["relative_width_ratio"] == pytest.approx(45 / 241, abs=1e-6)
    assert masks.diagnostics()["grabcut_executions"] == 0


def test_failed_prompt_preserves_another_fish_candidate(frame):
    provider = ExperimentalFrameSegmentation(frame, "partial", service=Service("failed_first"))
    provider.prepare(PARENTS, parts())
    assert provider.report(1)["status"] == "unavailable"
    assert provider.report(2)["status"] == "candidate"
    assert provider.report(2)["engineering_checks_passed"]


def test_validator_failure_withholds_candidate_without_discarding_grade(frame, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("Validator failed")
    monkeypatch.setattr("src.inference.mask_ownership.validate_candidate_masks", broken)
    masks = context(frame, Service(), monkeypatch)
    observations = model().predict_full_frame(frame, PARENTS, stabilize=False, mask_context=masks)
    assert observations[1][0].quality == "Class A"
    assert masks.get(1, BOUNDS)[0] is None
    assert masks.segmentation_report(1)["ownership_status"] == "unavailable"


def test_entire_frame_edit_invalidates_masks_features_and_overlays_even_outside_roi(frame, monkeypatch):
    service = Service()
    masks = context(frame, service, monkeypatch)
    masks.prepare_instances(PARENTS, parts())
    assert masks.get(1, BOUNDS)[0] is not None
    assert masks.cached_feature(1, BOUNDS, "test-pixels", lambda: "old") == "old"
    frame[0, 0] ^= 1  # Outside both fish; SAM's full-frame embedding still depends on it.
    assert masks.get(1, BOUNDS)[0] is None
    assert masks.cached_feature(1, BOUNDS, "test-pixels", lambda: "new") == "new"
    assert not masks.segmentation_report(1).get("mask_overlay", {}).get("contours")
    masks.prepare_instances(PARENTS, parts())
    assert masks.get(1, BOUNDS)[0] is not None
    assert len(service.frames) == 2


def test_merged_candidates_show_only_intersection_conflicts_and_remain_unusable(frame):
    provider = ExperimentalFrameSegmentation(frame, 3, service=Service("merged"))
    provider.prepare(PARENTS, parts())
    report = provider.report(1)
    assert report["ownership_status"] == "rejected"
    assert report["ownership"]["conflicting_parent_ids"] == [2]
    assert report["mask_overlay"]["conflict_contours"]
    assert provider.get(1, BOUNDS)[0] is None
    assert sum(map(len, report["mask_overlay"]["contours"])) <= 4096


def test_empty_frame_detection_list_never_opens_service(frame):
    service = Service()
    provider = ExperimentalFrameSegmentation(frame, "empty", service=service)
    provider.prepare([])
    assert service.frames == []
    assert provider.diagnostics()["candidate_count"] == 0


@pytest.mark.parametrize("backend", ["geometry_only", "mobilesam_experimental"])
@pytest.mark.parametrize("source", ["missing", "different_frame"])
def test_missing_or_wrong_measurement_frame_never_falls_back_to_grabcut(frame, backend, source):
    masks = RuntimeMaskContext(frame, backend=backend)
    geometry = analyze_fish_geometry(frame[30:90, 20:280], [], parent_bbox=PARENTS[0].bbox,
        crop_bounds=BOUNDS, frame_shape=frame.shape, parent_id=1, mask_context=masks,
        measurement_frame=None if source == "missing" else frame.copy())
    assert geometry["fish_length_px"] is None
    assert geometry["mask_metadata"]["grabcut_invocations"] == 0


def reviewed_body():
    pixels = np.zeros((120, 640), bool)
    pixels[44:76, 100:200] = True
    return {"mask": pixels, "region": "Body", "parent_track_id": 1,
            "coordinate_space": "original_frame", "orientation_reliable": True,
            "ownership_validated": True, "mask_validated": True,
            "validation_provenance": "Reviewed synthetic software fixture; no biological validation"}


def test_only_reviewed_anatomical_pixels_become_prompts_and_crack_support(frame, monkeypatch):
    service = Service()
    masks = context(frame, service, monkeypatch)
    masks.prepare_instances(PARENTS, parts())
    damage = parent_damage(frame, BOUNDS, 1, mask_context=masks)
    assert damage["status"] == "unavailable"
    assert damage["locations"] == []
    reviewed = reviewed_body()
    masks.prepare_instances(PARENTS, parts(), trusted_parts=[reviewed])
    assert len(service.frames) == 2  # Reviewed point prompts invalidate the box-only generation.
    point_options = service.prompts[2][2]
    assert point_options["point_labels"] == [1]
    x, y = point_options["point_coords"][0]
    assert reviewed["mask"][y, x]
    captured = []
    def crack_analysis(rgb, support, **kwargs):
        captured.append(support.copy())
        return {"status": "no_candidate", "locations": [], "used_for_grading": False}
    monkeypatch.setattr("src.inference.frame_diagnostics.analyze_surface_damage", crack_analysis)
    result = parent_damage(frame, BOUNDS, 1, mask_context=masks)
    np.testing.assert_array_equal(captured[0], reviewed["mask"][30:90, 20:280])
    assert result["used_for_grading"] is False


def test_even_valid_scale_cannot_convert_unvalidated_mobile_candidate_to_cm(frame, monkeypatch):
    masks = context(frame, Service(), monkeypatch)
    masks.prepare_instances(PARENTS, parts())
    geometry = analyze_fish_geometry(frame[30:90, 20:280], [], parent_bbox=PARENTS[0].bbox,
        crop_bounds=BOUNDS, frame_shape=frame.shape, parent_id=1, mask_context=masks,
        measurement_frame=frame, association_reliable=True,
        physical_calibration=PhysicalCalibration(True, "fixture", 20., (640, 120), "fixture"),
        source_context={"source_id": "fixture"})
    assert geometry["fish_length_cm"] is None
    assert geometry["max_body_width_cm"] is None
    assert "experimental_mask_requires_ownership_validation" in geometry["reasons"]


def test_video_cadence_keeps_snapshot_identity_separate_from_best_grade_frame(monkeypatch):
    from src.api import image_analysis as images
    frames = [np.full((120, 640, 3), i, np.uint8) for i in range(4)]
    class Capture:
        def isOpened(self): return True
        def get(self, prop): return 4 if prop == cv2.CAP_PROP_FRAME_COUNT else 30
        def read(self): return (True, frames.pop(0)) if frames else (False, None)
        def release(self): pass
    class Analyzer(images.StillImageAnalyzer):
        def __init__(self): self.calls = []
        def analyze(self, image, **options):
            self.calls.append(options)
            index = int(image[0, 0, 0]); identity = 7 if index < 2 else 9
            fish = {"id": identity, "bbox": [20, 30, 280, 90], "quality": "Class A",
                    "detector_confidence": .99 if index == 0 else .8, "analysis": {}}
            if options["segmentation_backend"] == "mobilesam_experimental":
                fish["analysis"]["segmentation"] = {"parent_track_id": identity,
                    "frame_id": options["frame_id"], "source_parent_bbox": fish["bbox"],
                    "mask_overlay": {"frame_id": options["frame_id"], "source_preview_image": f"source-{index}"}}
            return {"fish": [fish], "annotated_image": f"preview-{index}"}
    monkeypatch.setattr(images.cv2, "VideoCapture", lambda _: Capture())
    monkeypatch.setenv("MOBILESAM_VIDEO_FRAME_INTERVAL", "2")
    analyzer = Analyzer()
    result = images.VideoUploadAnalyzer(analyzer).analyze(Path("fixture.mp4"), lambda *args: None,
                                                        segmentation_backend="mobilesam_experimental")
    assert [call["segmentation_backend"] for call in analyzer.calls] == ["mobilesam_experimental", "geometry_only"] * 2
    fish = result["fish"][0]
    assert fish["id"] == 1 and fish["source_detection_id"] == 7
    snapshot = fish["analysis"]["segmentation"]
    assert snapshot["parent_track_id"] == 1
    assert snapshot["source_detection_id"] == 9
    assert snapshot["frame_id"] == "video-2"
    assert snapshot["mask_overlay"]["source_preview_image"] == "source-2"
