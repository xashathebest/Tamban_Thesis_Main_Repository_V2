"""MobileSAM's optional model, frame, memory and prompt contracts without GPUs."""
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import time

import numpy as np
import pytest

from src.inference import mobilesam_backend as sam


class Engine:
    def __init__(self, checkpoint, device):
        self.device = device
        self.images = []
        self.prompts = []
        self.resets = 0

    def set_image(self, image):
        self.images.append(image.copy())

    def predict(self, image, box, points, labels):
        self.prompts.append((box.copy(), points, labels))
        mask = np.zeros(image.shape[:2], dtype=bool)
        left, top, right, bottom = np.asarray(box, dtype=int)
        mask[top:bottom, left:right] = True
        return mask, .99

    def reset_image(self):
        self.resets += 1

    def to_cpu(self):
        self.device = "cpu"


@pytest.fixture
def settings(tmp_path):
    checkpoint = tmp_path / "mobile_sam.pt"
    checkpoint.write_bytes(b"test-only fake checkpoint; no model weights")
    return sam.MobileSamSettings(checkpoint=checkpoint, expected_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())


@pytest.fixture
def image():
    return np.full((100, 160, 3), 80, np.uint8)


def test_import_and_empty_session_do_not_load_or_embed(settings, image):
    calls = []
    service = sam.MobileSamService(settings, predictor_factory=lambda *args: calls.append(args))
    assert not service.status()["loaded"]
    with service.open_frame(image, "empty") as frame:
        assert frame.diagnostics()["embedding_calls"] == 0
    assert calls == []


def test_one_embedding_multiple_fish_native_coords_and_cache(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, 7) as frame:
        first = frame.predict(1, (10, 20, 50, 60))
        second = frame.predict(2, (70, 10, 120, 90))
        cached = frame.predict(1, (10, 20, 50, 60))
        assert first["mask"].shape == image.shape[:2]
        assert first["mask"][20:60, 10:50].all()
        assert int(first["mask"].sum()) == 40 * 40
        assert int(second["mask"].sum()) == 50 * 80
        assert cached["cache_hit"] and cached["prompt_ms"] == 0
        assert frame.diagnostics()["embedding_calls"] == 1
        assert frame.diagnostics()["prompt_calls"] == 2
        assert frame.diagnostics()["prompt_cache_hits"] == 1
        assert not first["provenance"]["ownership_validated"]
        assert not first["provenance"]["approved_for_grading"]
        assert first["provenance"]["coordinate_space"] == "original_frame"
        assert len(service._engine.images) == 1
    assert service._engine.resets == 1


def test_detection_version_and_parent_id_do_not_alias(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "frame") as frame:
        for parent, version in ((1, 0), (2, 0), (1, 1)):
            assert frame.predict(parent, (10, 10, 30, 30), detection_version=version)["status"] == "candidate"
        assert frame.diagnostics()["prompt_calls"] == 3
        assert frame.diagnostics()["embedding_calls"] == 1


def test_cached_masks_and_metadata_cannot_be_mutated(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "frame") as frame:
        first = frame.predict(1, (10, 10, 30, 30))
        with pytest.raises(ValueError):
            first["mask"].flags.writeable = True
        first["provenance"]["ownership_validated"] = True
        assert frame.predict(1, (10, 10, 30, 30))["provenance"]["ownership_validated"] is False


def test_closed_frame_and_new_frame_do_not_reuse_stale_embeddings(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "same ID") as old:
        first = old.predict(1, (10, 10, 30, 30))
    with pytest.raises(RuntimeError, match="closed"):
        old.predict(1, (10, 10, 30, 30))
    changed = image.copy(); changed[0, 0] = 1
    with service.open_frame(changed, "same ID") as current:
        second = current.predict(1, (10, 10, 30, 30))
        assert current.diagnostics()["embedding_calls"] == 1
    assert first["provenance"]["frame_pixels_digest"] != second["provenance"]["frame_pixels_digest"]
    assert len(service._engine.images) == 2


def test_nested_frames_cannot_overwrite_embedding(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "outer") as frame:
        with pytest.raises(RuntimeError, match="Nested"):
            with service.open_frame(image, "inner"):
                pass
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "candidate"


@pytest.mark.parametrize("box", [None, [], [1, 2, 3], [5, 5, 3, 8], [0, 0, float("nan"), 8],
                                 [0, 0, float("inf"), 8], [True, 0, 10, 10], [180, 0, 190, 10]])
def test_invalid_boxes_do_not_load_backend(settings, image, box):
    calls = []
    service = sam.MobileSamService(settings, predictor_factory=lambda *args: calls.append(args))
    with service.open_frame(image, "frame") as frame:
        assert frame.predict(1, box)["status"] == "unavailable"
    assert calls == []


def test_clipped_box_preserves_original_and_native_prompt(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "frame") as frame:
        candidate = frame.predict(1, (-10, 20, 180, 110))
        assert candidate["provenance"]["prompt_clipped"]
        assert candidate["provenance"]["original_bbox_global"] == [-10, 20, 180, 110]
        assert candidate["provenance"]["prompt_bbox_global"] == [0, 20, 160, 100]


def test_anatomical_points_are_only_caller_supplied_and_scoped(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "frame") as frame:
        no_points = frame.predict(1, (10, 10, 30, 30))
        vetted = frame.predict(1, (10, 10, 30, 30), point_coords=[[20, 20], [45, 45]], point_labels=[1, 0])
        assert no_points["provenance"]["point_prompt_count"] == 0
        assert vetted["provenance"]["point_prompt_count"] == 2
        assert frame.diagnostics()["prompt_calls"] == 2
        assert frame.predict(1, (10, 10, 30, 30), point_coords=[[200, 10]], point_labels=[1])["status"] == "unavailable"


def test_missing_or_wrong_checkpoint_never_invokes_model_factory(settings, image):
    for configured in (replace(settings, checkpoint=settings.checkpoint.parent / "missing.pt"),
                       replace(settings, expected_sha256="0" * 64)):
        calls = []
        service = sam.MobileSamService(configured, predictor_factory=lambda *args: calls.append(args))
        with service.open_frame(image, "frame") as frame:
            assert frame.predict(1, (10, 10, 30, 30))["status"] == "unavailable"
        assert calls == []


def test_cpu_never_probes_gpu_and_insufficient_gpu_budget_uses_cpu(settings, image):
    def prohibited(*args): raise AssertionError("CPU must not query or initialize CUDA")
    cpu = sam.MobileSamService(settings, predictor_factory=Engine, memory_probe=prohibited)
    with cpu.open_frame(image, "cpu") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "candidate"
    gpu = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=Engine,
                              memory_probe=lambda _: {"free_mb": 400, "total_mb": 4096})
    with gpu.open_frame(image, "guarded") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["provenance"]["device"] == "cpu"
    assert "preflight" in gpu.status()["fallback_reason"]


def test_gpu_inference_oom_retries_same_frame_on_cpu(settings, image):
    class OomEngine(Engine):
        def predict(self, image, box, points, labels):
            if self.device.startswith("cuda"):
                raise RuntimeError("CUDA out of memory")
            return super().predict(image, box, points, labels)
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=OomEngine,
                                  memory_probe=lambda _: {"free_mb": 2048, "total_mb": 4096})
    with service.open_frame(image, "oom") as frame:
        result = frame.predict(1, (10, 10, 30, 30))
        assert result["status"] == "candidate" and result["provenance"]["device"] == "cpu"
        assert frame.diagnostics()["cpu_fallbacks"] == 1
        assert "out of memory" in result["provenance"]["fallback_reason"].lower()


def test_gpu_load_oom_retries_single_checkpoint_on_cpu(settings, image):
    devices = []
    def factory(checkpoint, device):
        devices.append(device)
        if device.startswith("cuda"):
            raise RuntimeError("CUDA out of memory during load")
        return Engine(checkpoint, device)
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=factory,
                                  memory_probe=lambda _: {"free_mb": 2048, "total_mb": 4096})
    with service.open_frame(image, "oom") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "candidate"
    assert devices == ["cuda:0", "cpu"]


def test_prompt_and_cpu_mask_memory_budgets_are_bounded(settings, image):
    service = sam.MobileSamService(replace(settings, max_prompts_per_frame=1), predictor_factory=Engine)
    with service.open_frame(image, "budget") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "candidate"
        assert frame.predict(2, (40, 10, 60, 30))["status"] == "unavailable"
        assert frame.predict(1, (10, 10, 30, 30))["cache_hit"]
    tiny = sam.MobileSamService(replace(settings, maximum_cached_mask_bytes=100), predictor_factory=Engine)
    with tiny.open_frame(image, "memory") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "unavailable"
        assert not tiny.status()["loaded"]


def test_concurrent_requests_do_not_mix_image_embeddings(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    def process(value):
        changed = image.copy(); changed[0, 0] = value
        with service.open_frame(changed, value) as frame:
            time.sleep(.01)
            return frame.predict(value, (10, 10, 30, 30))["provenance"]["frame_pixels_digest"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        digests = list(pool.map(process, [1, 2]))
    assert len(set(digests)) == 2
    assert len(service._engine.images) == 2


def test_failed_prompt_is_cached_and_counted_as_an_attempt(settings, image):
    class Failing(Engine):
        def predict(self, *args):
            self.prompts.append(args)
            raise RuntimeError("Unavailable mask decoder")
    service = sam.MobileSamService(settings, predictor_factory=Failing)
    with service.open_frame(image, "failed") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "unavailable"
        assert frame.predict(1, (10, 10, 30, 30))["cache_hit"]
        assert len(service._engine.prompts) == 1
        assert frame.diagnostics()["decoder_attempts"] == 1


def test_different_raw_clipped_boxes_preserve_separate_provenance(settings, image):
    service = sam.MobileSamService(settings, predictor_factory=Engine)
    with service.open_frame(image, "clipped") as frame:
        first = frame.predict(1, (-5, 10, 30, 30))
        second = frame.predict(1, (-10, 10, 30, 30))
        assert first["provenance"]["original_bbox_global"] != second["provenance"]["original_bbox_global"]
        assert not second["cache_hit"]


def test_gpu_pressure_rechecked_before_embedding(settings, image):
    memories = iter([{"free_mb": 2048, "total_mb": 4096}, {"free_mb": 400, "total_mb": 4096}])
    service = sam.MobileSamService(replace(settings, device="cuda:0"), predictor_factory=Engine,
                                  memory_probe=lambda _: next(memories))
    with service.open_frame(image, "pressure") as frame:
        result = frame.predict(1, (10, 10, 30, 30))
        assert result["provenance"]["device"] == "cpu"
        assert frame.diagnostics()["cpu_fallbacks"] == 1
    assert service._engine.device == "cpu"


def test_cleanup_error_does_not_leave_active_frame_locked(settings, image):
    class CleanupError(Engine):
        def reset_image(self):
            raise RuntimeError("Test cleanup error")
    service = sam.MobileSamService(settings, predictor_factory=CleanupError)
    with service.open_frame(image, "first") as frame:
        frame.predict(1, (10, 10, 30, 30))
    with service.open_frame(image, "second") as frame:
        assert frame.predict(1, (10, 10, 30, 30))["status"] == "candidate"
    assert service.status()["cleanup_error"] == "RuntimeError"
