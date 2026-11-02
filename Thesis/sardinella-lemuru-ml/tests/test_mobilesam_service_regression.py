"""Backend failure isolation and real backend provenance/ownership contracts."""
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.inference import mobilesam_backend as sam
from src.inference.association import ParentAnchor
from src.inference.mask_ownership import validate_candidate_masks


SHAPE = (120, 640)
PARENT = ParentAnchor(1, (20, 30, 280, 90))


class Engine:
    def __init__(self, checkpoint, device):
        self.device = device
        self.images = 0
        self.prompts = 0

    def set_image(self, image):
        self.images += 1

    def predict(self, image, box, points, labels):
        self.prompts += 1
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.ellipse(mask, (150, 60), (120, 22), 0, 0, 360, 1, -1)
        return mask.astype(bool), .999

    def reset_image(self):
        pass

    def to_cpu(self):
        self.device = "cpu"


@pytest.fixture
def settings(tmp_path):
    checkpoint = tmp_path / "fake_mobile_sam.pt"
    checkpoint.write_bytes(b"unit test checkpoint only")
    return sam.MobileSamSettings(checkpoint=checkpoint,
                                expected_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())


@pytest.fixture
def image():
    return np.full((*SHAPE, 3), 80, np.uint8)


def validate(candidate, parent=PARENT):
    parts = [SimpleNamespace(region="Body", bbox=(90, 38, 215, 82), confidence=.9),
             SimpleNamespace(region="Head", bbox=(30, 47, 75, 73), confidence=.8)]
    associations = [SimpleNamespace(part=part, status="ASSIGNED", track_id=1) for part in parts]
    return validate_candidate_masks({1: candidate}, [parent], parts, associations=associations,
                                    frame_shape=SHAPE, expected_frame_key="original-frame")[1]


def candidate_from_service(settings, image, parent=PARENT):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "original-frame") as frame:
        candidate = frame.predict(parent.track_id, parent.bbox)
    # This is the actual public service schema, with no legacy bbox_global.
    assert "bbox_global" not in candidate
    return candidate


def test_actual_backend_provenance_passes_identity_checks_without_legacy_bbox(settings, image):
    candidate = candidate_from_service(settings, image)
    result = validate(candidate)
    assert result["status"] == "checks_passed_unvalidated"
    assert result["engineering_checks_passed"]
    assert result["ownership_validated"] is False
    assert result["approved_for_grading"] is False


@pytest.mark.parametrize("field,value,reason", [
    ("original_bbox_global", [21, 30, 280, 90], "candidate_prompt_box_mismatch"),
    ("original_bbox_global", None, "candidate_prompt_box_mismatch"),
    ("prompt_bbox_global", [20, 30, 281, 90], "candidate_prompt_box_mismatch"),
    ("prompt_bbox_global", None, "candidate_prompt_box_mismatch"),
    ("parent_id", 2, "candidate_parent_identity_mismatch"),
    ("parent_id", True, "candidate_parent_identity_mismatch"),
    ("parent_id", None, "candidate_parent_identity_mismatch"),
    ("coordinate_space", "crop_local", "candidate_native_coordinates_mismatch"),
    ("mask_shape", [640, 120], "candidate_native_coordinates_mismatch"),
    ("mask_shape", None, "candidate_native_coordinates_mismatch"),
    ("frame_key", "different-frame", "candidate_frame_identity_mismatch"),
])
def test_backend_provenance_mismatch_cannot_bypass_ownership_checks(settings, image, field, value, reason):
    candidate = candidate_from_service(settings, image)
    candidate["provenance"][field] = value
    result = validate(candidate)
    assert reason in result["reasons"]
    assert result["mask_geometry_checks_passed"] is False
    assert result["engineering_checks_passed"] is False


def test_backend_requires_top_level_parent_even_when_provenance_owner_matches(settings, image):
    candidate = candidate_from_service(settings, image)
    del candidate["parent_id"]
    assert "candidate_parent_identity_mismatch" in validate(candidate)["reasons"]


def test_clipped_native_prompt_compares_against_clipped_original_parent(settings, image):
    parent = ParentAnchor(1, (-20, 30, 280, 90))
    candidate = candidate_from_service(settings, image, parent)
    assert candidate["provenance"]["original_bbox_global"] == [-20, 30, 280, 90]
    assert candidate["provenance"]["prompt_bbox_global"] == [0, 30, 280, 90]
    reasons = validate(candidate, parent)["reasons"]
    assert "candidate_prompt_box_mismatch" not in reasons
    assert "parent_touches_frame_boundary" in reasons
    candidate["provenance"]["prompt_bbox_global"] = [-20, 30, 280, 90]
    assert "candidate_prompt_box_mismatch" in validate(candidate, parent)["reasons"]


def test_legacy_box_identity_check_is_preserved_with_backend_provenance(settings, image):
    candidate = candidate_from_service(settings, image)
    candidate["bbox_global"] = [21, 30, 280, 90]
    assert "candidate_prompt_box_mismatch" in validate(candidate)["reasons"]


def test_cuda_embedding_oom_reencodes_same_frame_on_cpu(settings, image):
    class EmbeddingOom(Engine):
        def set_image(self, image):
            self.images += 1
            if self.device.startswith("cuda"):
                raise RuntimeError("CUDA out of memory during encoder")
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=EmbeddingOom,
                                  memory_probe=lambda _: {"free_mb": 4096})
    with service.open_frame(image, "original-frame") as frame:
        candidate = frame.predict(1, PARENT.bbox)
        assert candidate["status"] == "candidate"
        assert candidate["provenance"]["device"] == "cpu"
        assert frame.diagnostics()["embedding_calls"] == 2
        assert frame.diagnostics()["cpu_fallbacks"] == 1
        assert frame.diagnostics()["decoder_attempts"] == 1
        assert frame.predict(1, PARENT.bbox)["cache_hit"] is True


def test_cuda_and_cpu_decoder_failure_is_explicit_and_cached(settings, image):
    class DecoderOom(Engine):
        def predict(self, *args):
            self.prompts += 1
            raise RuntimeError("CUDA out of memory" if self.device.startswith("cuda") else "CPU decoder unavailable")
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=DecoderOom,
                                  memory_probe=lambda _: {"free_mb": 4096})
    with service.open_frame(image, "original-frame") as frame:
        candidate = frame.predict(1, PARENT.bbox)
        assert candidate["status"] == "unavailable"
        assert candidate["mask"] is None
        assert "CPU decoder unavailable" in candidate["reason"]
        assert frame.diagnostics()["decoder_attempts"] == 2
        assert frame.diagnostics()["cpu_fallbacks"] == 1
        assert frame.predict(1, PARENT.bbox)["cache_hit"] is True
        assert service._engine.prompts == 2


def test_non_oom_gpu_error_does_not_retry_or_silently_run_cpu(settings, image):
    class DecoderError(Engine):
        def predict(self, *args):
            self.prompts += 1
            raise RuntimeError("Unsupported predictor interface")
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=DecoderError,
                                  memory_probe=lambda _: {"free_mb": 4096})
    with service.open_frame(image, "original-frame") as frame:
        assert frame.predict(1, PARENT.bbox)["status"] == "unavailable"
        assert frame.diagnostics()["cpu_fallbacks"] == 0
        assert frame.diagnostics()["decoder_attempts"] == 1
        assert service._device == "cuda:0"


def test_singleton_is_lazy_and_reconfiguration_requires_restart(settings, monkeypatch):
    monkeypatch.setattr(sam, "_SERVICE", None)
    first = sam.get_mobilesam_service(settings)
    assert first is sam.get_mobilesam_service(settings)
    assert first.status()["loaded"] is False
    with pytest.raises(RuntimeError, match="restart"):
        sam.get_mobilesam_service(replace(settings, gpu_budget_mb=2048))

