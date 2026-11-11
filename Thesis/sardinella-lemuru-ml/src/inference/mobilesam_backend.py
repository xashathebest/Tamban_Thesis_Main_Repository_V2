"""Optional FP32 MobileSAM candidates; no detector, grading, or ownership policy.

The supported Ultralytics SAM predictor owns prompt scaling and native-mask
postprocessing. Its image embedding is shared across a locked frame session.
Importing this module never imports Torch, loads weights, or initializes CUDA.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import subprocess
from threading import Lock, RLock
from time import perf_counter
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_CHECKPOINT_SHA256 = "6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f"
OFFICIAL_CHECKPOINT_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/mobile_sam.pt"


@dataclass(frozen=True)
class MobileSamSettings:
    checkpoint: Path = ROOT / "models/experimental/mobilesam/mobile_sam.pt"
    device: str = "cpu"
    minimum_free_gpu_mb: int = 1024
    gpu_budget_mb: int = 1024
    max_prompts_per_frame: int = 32
    maximum_cached_mask_bytes: int = 128 * 1024 * 1024
    expected_sha256: str | None = OFFICIAL_CHECKPOINT_SHA256

    def __post_init__(self):
        object.__setattr__(self, "checkpoint", Path(self.checkpoint).expanduser().resolve())
        if self.device not in {"cpu", "auto", "cuda"} and not (
            self.device.startswith("cuda:") and self.device[5:].isdigit()
        ):
            raise ValueError("MobileSAM device must be cpu, auto, cuda or cuda:N.")
        for name in ("minimum_free_gpu_mb", "gpu_budget_mb", "max_prompts_per_frame", "maximum_cached_mask_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if self.expected_sha256 is not None and (
            len(self.expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.expected_sha256.lower())
        ):
            raise ValueError("MobileSAM checkpoint SHA-256 must contain 64 hexadecimal characters.")
        if self.expected_sha256 is not None:
            object.__setattr__(self, "expected_sha256", self.expected_sha256.lower())

    @classmethod
    def from_environment(cls):
        return cls(checkpoint=Path(os.getenv("MOBILESAM_CHECKPOINT", str(cls.checkpoint))),
                   device=os.getenv("MOBILESAM_DEVICE", "cpu").strip().lower(),
                   minimum_free_gpu_mb=int(os.getenv("MOBILESAM_MIN_FREE_GPU_MB", "1024")),
                   gpu_budget_mb=int(os.getenv("MOBILESAM_GPU_BUDGET_MB", "1024")),
                   max_prompts_per_frame=int(os.getenv("MOBILESAM_MAX_PROMPTS", "32")))


def _gpu_free_memory(index):
    """NVML CLI preflight does not initialize a new Torch CUDA context."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        rows = [tuple(float(value.strip()) for value in line.split(",")) for line in result.stdout.splitlines() if line.strip()]
        total, free = rows[index]
        return {"total_mb": total, "free_mb": free, "source": "nvidia-smi device-wide preflight"}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


class _UltralyticsEngine:
    def __init__(self, checkpoint, device):
        import torch
        from ultralytics.models.sam.build import build_mobile_sam
        from ultralytics.models.sam.predict import Predictor
        self.torch = torch
        self.device = device
        self.predictor = Predictor(overrides={"model": str(checkpoint), "device": device,
            "task": "segment", "mode": "predict", "imgsz": 1024,
            "verbose": False, "save": False, "conf": 0.0})
        model = build_mobile_sam(str(checkpoint))
        self.predictor.setup_model(model=model, verbose=False)
        if getattr(self.predictor.model, "fp16", False):
            raise RuntimeError("MobileSAM FP16 is not approved for this experimental backend.")
        self.encoder_forward_calls = 0
        def count_encoder(*_args):
            self.encoder_forward_calls += 1
        self._encoder_hook = self.predictor.model.image_encoder.register_forward_pre_hook(count_encoder)

    def inference_mode(self):
        return self.torch.inference_mode()

    def set_image(self, image):
        self.predictor.set_image(image)
        # set_image computes features but does not retain the normalized input.
        # Cache that tensor once too; all prompt calls reuse both objects.
        self.predictor.im = self.predictor.preprocess([image])

    def predict(self, image, box, points, labels):
        shared_features = self.predictor.features
        if shared_features is None:
            raise RuntimeError("MobileSAM's shared image embedding is unavailable.")
        encoder_before = self.encoder_forward_calls
        # Passing source=image here would call SAM.setup_source and discard
        # set_image's embedding. source=None intentionally reuses that source.
        results = self.predictor(source=None, bboxes=np.asarray([box], dtype=np.float32),
            points=None if points is None else np.asarray([points], dtype=np.float32),
            labels=None if labels is None else np.asarray([labels], dtype=np.int32),
            multimask_output=False, stream=False)
        try:
            if self.encoder_forward_calls != encoder_before or self.predictor.features is not shared_features:
                raise RuntimeError("Installed SAM predictor invalidated the shared embedding; this API version is not supported.")
            if not results or results[0].masks is None or len(results[0].masks.data) != 1:
                return None, None
            mask = results[0].masks.data[0].detach().cpu().numpy().astype(bool, copy=True)
            score = float(results[0].boxes.conf[0].detach().cpu())
            return mask, score
        finally:
            del results

    def reset_image(self):
        self.predictor.reset_image()

    def to_cpu(self):
        previous_device = self.device
        self.reset_image()
        # TinyViT eval-time attention caches must be rebuilt on the new device.
        model = self.predictor.model
        model.train(True)
        model = model.to("cpu").float()
        self.predictor.args.device = "cpu"
        self.predictor.setup_model(model=model, verbose=False)
        self.device = "cpu"
        if previous_device.startswith("cuda") and self.torch.cuda.is_initialized():
            # Exceptional pressure fallback only: release unused allocator
            # blocks after our tensors moved. Other models' live tensors stay.
            self.torch.cuda.empty_cache()

    def memory(self):
        cuda = self.torch.cuda
        if self.device.startswith("cuda") and cuda.is_initialized():
            index = int(self.device.split(":")[-1])
            return {"status": "available", "allocated_bytes": int(cuda.memory_allocated(index)),
                    "reserved_bytes": int(cuda.memory_reserved(index)),
                    "peak_allocated_bytes": int(cuda.max_memory_allocated(index)),
                    "scope": "this_process_allocator; peak is process-lifetime and includes other loaded models"}
        return {"status": "not_measured", "reason": "MobileSAM is running on CPU."}


class MobileSamService:
    """One lazily loaded predictor, serialized frame access and explicit fallback."""
    def __init__(self, settings=None, *, predictor_factory: Callable | None = None, memory_probe=None):
        self.settings = settings or MobileSamSettings.from_environment()
        self._factory = predictor_factory or _UltralyticsEngine
        self._memory_probe = memory_probe or _gpu_free_memory
        self._custom_factory = predictor_factory is not None
        self._lock = RLock()
        self._engine = None
        self._device = None
        self._checkpoint_sha256 = None
        self._fallback_reason = None
        self._load_ms = None
        self._embedding_count = 0
        self._frame_count = 0
        self._active_session = False
        self._cleanup_error = None

    def status(self):
        dependencies = self._custom_factory or all(importlib.util.find_spec(name) is not None for name in ("torch", "ultralytics"))
        return {"backend": "mobilesam_experimental", "default_enabled": False,
                "checkpoint_available": self.settings.checkpoint.is_file(),
                "dependencies_available": dependencies, "loaded": self._engine is not None,
                "requested_device": self.settings.device, "device": self._device,
                "minimum_free_gpu_mb": self.settings.minimum_free_gpu_mb,
                "gpu_budget_mb": self.settings.gpu_budget_mb,
                "gpu_budget_scope": "Preflight free-device-memory requirement; not a global allocator limit for other models.",
                "precision": "FP32", "checkpoint": str(self.settings.checkpoint),
                "checkpoint_sha256": self._checkpoint_sha256, "fallback_reason": self._fallback_reason,
                "checkpoint_integrity": "not_checked" if self._checkpoint_sha256 is None else
                    "unverified_override" if self.settings.expected_sha256 is None else
                    "verified" if self._checkpoint_sha256 == self.settings.expected_sha256 else "mismatch",
                "embedding_count": self._embedding_count, "frame_count": self._frame_count,
                "cleanup_error": self._cleanup_error,
                "ownership_validated": False, "approved_for_grading": False}

    def _select_device(self):
        if self.settings.device == "cpu":
            return "cpu"
        index = int(self.settings.device.split(":")[-1]) if ":" in self.settings.device else 0
        memory = self._memory_probe(index)
        if memory is None or memory["free_mb"] < max(self.settings.minimum_free_gpu_mb, self.settings.gpu_budget_mb):
            self._fallback_reason = "GPU memory preflight is unavailable or below the configured free-memory budget."
            return "cpu"
        if not self._custom_factory:
            import torch
            if not torch.cuda.is_available() or index >= torch.cuda.device_count():
                self._fallback_reason = "Requested CUDA device is unavailable to the installed Torch runtime."
                return "cpu"
        return f"cuda:{index}"

    def _load(self):
        if self._engine is not None:
            return
        if not self.settings.checkpoint.is_file():
            raise RuntimeError("MobileSAM checkpoint is unavailable; run the documented optional setup first.")
        self._checkpoint_sha256 = hashlib.sha256(self.settings.checkpoint.read_bytes()).hexdigest()
        if self.settings.expected_sha256 and self._checkpoint_sha256 != self.settings.expected_sha256:
            raise RuntimeError("MobileSAM checkpoint SHA-256 does not match the configured official artifact.")
        started = perf_counter()
        self._device = self._select_device()
        retry_cpu = False
        try:
            self._engine = self._factory(self.settings.checkpoint, self._device)
        except Exception as error:
            retry_cpu = self._device.startswith("cuda") and "out of memory" in str(error).lower()
            if not retry_cpu:
                raise
            self._fallback_reason = "CUDA out of memory while loading MobileSAM; retrying the same checkpoint on CPU."
        if retry_cpu:
            self._device = "cpu"
            self._engine = self._factory(self.settings.checkpoint, "cpu")
        self._load_ms = round((perf_counter() - started) * 1000, 3)

    @contextmanager
    def open_frame(self, image_bgr, frame_key):
        if not isinstance(image_bgr, np.ndarray) or image_bgr.ndim != 3 or image_bgr.shape[2] != 3 or image_bgr.dtype != np.uint8 or image_bgr.size == 0:
            raise ValueError("MobileSAM requires a nonempty native HWC uint8 BGR image.")
        if image_bgr.shape[0] * image_bgr.shape[1] > 16_777_216:
            raise ValueError("MobileSAM experimental image exceeds the bounded pixel budget.")
        started = perf_counter()
        with self._lock:
            if self._active_session:
                raise RuntimeError("Nested MobileSAM frame sessions cannot overwrite another frame's embedding.")
            session = MobileSamFrame(self, image_bgr, frame_key, (perf_counter() - started) * 1000)
            self._active_session = True
            self._frame_count += 1
            try:
                yield session
            finally:
                try:
                    session.close()
                finally:
                    self._active_session = False


class MobileSamFrame:
    def __init__(self, service, image, frame_key, lock_wait_ms):
        self.service = service
        self.image = np.array(image, copy=True, order="C")
        self.image.flags.writeable = False
        self.frame_key = str(frame_key)
        self.digest = hashlib.blake2b(self.image, digest_size=16).hexdigest()
        self._cache = {}
        self._embedded = False
        self._closed = False
        self._embedding_ms = 0.0
        self._embedding_calls = 0
        self._prompt_ms = 0.0
        self._prompt_calls = 0
        self._cache_hits = 0
        self._fallbacks = 0
        self._request_count = 0
        self._decoder_attempts = 0
        self._cached_bytes = 0
        self._backend_error = None
        self._lock_wait_ms = round(lock_wait_ms, 3)
        self._encoder_start = getattr(self.service._engine, "encoder_forward_calls", 0)

    def _unavailable(self, parent_id, reason):
        return {"status": "unavailable", "parent_id": parent_id, "mask": None, "score": None,
                "reason": reason, "embedding_ms": self._embedding_ms, "prompt_ms": 0.0,
                "provenance": self._provenance(parent_id)}

    def _provenance(self, parent_id):
        return {"backend": "mobilesam_experimental", "source": "mobilesam_box_prompt_candidate",
                "frame_key": self.frame_key, "frame_pixels_digest": self.digest,
                "parent_id": parent_id, "coordinate_space": "original_frame",
                "mask_shape": list(self.image.shape[:2]), "device": self.service._device,
                "precision": "FP32", "checkpoint_sha256": self.service._checkpoint_sha256,
                "ownership_validated": False, "measurement_validated": False,
                "approved_for_grading": False, "mask_score_kind": "SAM predicted mask quality; not fish ownership probability",
                "fallback_reason": self.service._fallback_reason}

    def _ensure_embedding(self):
        if self._embedded:
            return
        self.service._load()
        engine = self.service._engine
        if str(self.service._device).startswith("cuda"):
            index = int(self.service._device.split(":")[-1])
            memory = self.service._memory_probe(index)
            if memory is None or memory["free_mb"] < max(self.service.settings.minimum_free_gpu_mb, self.service.settings.gpu_budget_mb):
                engine.to_cpu()
                self.service._device = "cpu"
                self.service._fallback_reason = "GPU memory budget no longer available; MobileSAM moved to CPU before encoding."
                self._fallbacks += 1
        started = perf_counter()
        self._embedding_calls += 1
        self.service._embedding_count += 1
        try:
            with engine.inference_mode() if hasattr(engine, "inference_mode") else nullcontext():
                engine.set_image(self.image)
        finally:
            self._embedding_ms += (perf_counter() - started) * 1000
        self._embedded = True

    def _fallback_cpu(self, error):
        if not str(self.service._device).startswith("cuda") or "out of memory" not in str(error).lower():
            return False
        try:
            self.service._engine.to_cpu()
        except Exception as fallback_error:
            self.service._fallback_reason = f"CUDA inference and CPU fallback failed ({type(fallback_error).__name__})."
            return False
        self.service._device = "cpu"
        self.service._fallback_reason = "CUDA out of memory during MobileSAM inference; same-frame prompts retried on CPU."
        self._embedded = False
        self._fallbacks += 1
        return True

    @staticmethod
    def _read_candidate(candidate):
        result = {**candidate, "provenance": deepcopy(candidate["provenance"])}
        if candidate.get("mask") is not None:
            result["mask"] = candidate["mask"].view()
            result["mask"].flags.writeable = False
        return result

    def predict(self, parent_id, bbox_global, *, point_coords=None, point_labels=None, detection_version=0,
                point_prompt_source=None):
        if self._closed:
            raise RuntimeError("MobileSAM frame session is closed; stale frame reuse is prohibited.")
        if isinstance(parent_id, bool) or not isinstance(parent_id, (str, int)):
            raise ValueError("MobileSAM parent ID must be a string or integer.")
        try:
            if (isinstance(bbox_global, (tuple, list)) and any(isinstance(value, (bool, np.bool_)) for value in bbox_global)) or (isinstance(bbox_global, np.ndarray) and bbox_global.dtype == np.bool_):
                return self._unavailable(parent_id, "Invalid boolean box coordinates.")
            original_box = np.asarray(bbox_global, dtype=np.float64)
            if original_box.shape != (4,) or not np.isfinite(original_box).all() or original_box[2] <= original_box[0] or original_box[3] <= original_box[1]:
                return self._unavailable(parent_id, "Invalid original-frame box prompt.")
            height, width = self.image.shape[:2]
            box = np.clip(original_box, [0, 0, 0, 0], [width, height, width, height])
            if box[2] <= box[0] or box[3] <= box[1]:
                return self._unavailable(parent_id, "Box prompt is outside the original image.")
            points = labels = None
            if point_coords is not None or point_labels is not None:
                points = np.asarray(point_coords, dtype=np.float64)
                labels = np.asarray(point_labels)
                if points.ndim != 2 or points.shape[1] != 2 or len(points) > 32 or labels.shape != (len(points),) or not np.isfinite(points).all() or not np.isin(labels, [0, 1]).all():
                    return self._unavailable(parent_id, "Invalid vetted anatomical point prompts.")
                if ((points < 0).any() or (points[:, 0] >= width).any() or (points[:, 1] >= height).any()):
                    return self._unavailable(parent_id, "Anatomical point prompt is outside the original image.")
            if point_prompt_source is not None and (not isinstance(point_prompt_source, str) or not point_prompt_source.strip()):
                return self._unavailable(parent_id, "Point-prompt provenance must be a nonempty string.")
            key = (parent_id, str(detection_version), tuple(original_box), None if points is None else points.tobytes(),
                   None if labels is None else labels.tobytes(), point_prompt_source)
            if key in self._cache:
                self._cache_hits += 1
                return {**self._read_candidate(self._cache[key]), "cache_hit": True, "prompt_ms": 0.0}
            if self._backend_error:
                return self._unavailable(parent_id, self._backend_error)
            if self._request_count >= self.service.settings.max_prompts_per_frame or self._cached_bytes + height * width > self.service.settings.maximum_cached_mask_bytes:
                return self._unavailable(parent_id, "Experimental per-frame prompt/mask-memory budget exhausted.")
            self._request_count += 1
            request_prompt_before = self._prompt_ms
            for attempt in range(2):
                try:
                    self._ensure_embedding()
                    engine = self.service._engine
                    started = perf_counter()
                    self._decoder_attempts += 1
                    try:
                        with engine.inference_mode() if hasattr(engine, "inference_mode") else nullcontext():
                            mask, score = engine.predict(self.image, box, points, labels)
                    finally:
                        self._prompt_ms += (perf_counter() - started) * 1000
                    elapsed = self._prompt_ms - request_prompt_before
                    self._prompt_calls += 1
                    break
                except Exception as error:
                    if attempt == 0 and self._fallback_cpu(error):
                        continue
                    failed = self._unavailable(parent_id, f"MobileSAM candidate generation failed ({type(error).__name__}): {error}")
                    self._cache[key] = failed
                    if self.service._engine is None:
                        self._backend_error = failed["reason"]
                    return self._read_candidate(failed)
            if mask is None:
                return self._unavailable(parent_id, "MobileSAM did not return a candidate mask.")
            mask = np.asarray(mask)
            if mask.shape != (height, width) or mask.dtype != np.bool_:
                return self._unavailable(parent_id, "MobileSAM result has an invalid native-image shape.")
            if score is not None and not np.isfinite(score):
                score = None
            mask = np.array(mask, dtype=bool, copy=True)
            mask.flags.writeable = False
            provenance = self._provenance(parent_id)
            provenance.update(prompt_bbox_global=box.tolist(), original_bbox_global=original_box.tolist(),
                prompt_clipped=not np.array_equal(box, original_box), detection_version=str(detection_version),
                parent_touches_frame_boundary=bool(box[0] <= 0 or box[1] <= 0 or box[2] >= width or box[3] >= height),
                point_prompt_count=0 if points is None else len(points),
                point_prompt_source=("none; no anatomical points supplied" if points is None else
                                     point_prompt_source or "caller-supplied vetted anatomical evidence"))
            candidate = {"status": "candidate", "parent_id": parent_id, "mask": mask, "score": score,
                         "provenance": provenance, "reason": "Candidate mask; ownership validation is required.",
                         "embedding_ms": round(self._embedding_ms, 3), "prompt_ms": round(elapsed, 3), "cache_hit": False}
            self._cache[key] = candidate
            self._cached_bytes += mask.nbytes
            return self._read_candidate(candidate)
        except (TypeError, ValueError, OverflowError) as error:
            return self._unavailable(parent_id, f"Invalid MobileSAM prompt: {error}")

    def diagnostics(self):
        engine = self.service._engine
        memory = engine.memory() if engine is not None and hasattr(engine, "memory") else {"status": "not_measured"}
        return {"backend": "mobilesam_experimental", "frame_key": self.frame_key,
                "embedding_calls": self._embedding_calls, "embedding_ms": round(self._embedding_ms, 3),
                "actual_encoder_forward_calls": max(0, engine.encoder_forward_calls - self._encoder_start)
                if engine is not None and hasattr(engine, "encoder_forward_calls") else None,
                "prompt_calls": self._prompt_calls, "prompt_ms": round(self._prompt_ms, 3),
                "prompt_cache_hits": self._cache_hits, "cpu_fallbacks": self._fallbacks,
                "prompt_requests": self._request_count, "decoder_attempts": self._decoder_attempts,
                "cached_mask_bytes": self._cached_bytes,
                "lock_wait_ms": self._lock_wait_ms, "model_load_ms": self.service._load_ms,
                "device": self.service._device, "gpu_memory": memory,
                "scope": "shared image embedding plus sequential candidate prompts; child timings are not per-fish totals"}

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                if self.service._engine is not None:
                    self.service._engine.reset_image()
            except Exception as error:
                self.service._cleanup_error = type(error).__name__
            finally:
                self._cache.clear()
                self.image = None


_SERVICE = None
_SERVICE_LOCK = Lock()


def get_mobilesam_service(settings=None):
    """Process singleton: changing device/checkpoint requires an explicit restart."""
    global _SERVICE
    settings = settings or MobileSamSettings.from_environment()
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = MobileSamService(settings)
        elif _SERVICE.settings != settings:
            raise RuntimeError("MobileSAM is already configured; restart before changing its checkpoint or device.")
        return _SERVICE
