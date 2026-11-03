"""Small, deterministic image-boundary helpers for the local RF-DETR adapters.

Application code owns OpenCV-style ``uint8`` BGR frames.  These helpers never
resize or normalize a model input: RF-DETR's public ``predict`` API owns that
model-specific work.  They only validate source pixels, convert the color order
at the adapter boundary, and keep crop/frame coordinates explicit.
"""

from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass, field
from hashlib import blake2b
from numbers import Integral
import os
from threading import RLock
from time import perf_counter
from typing import Any, Callable, Literal, Mapping

import numpy as np


ColorOrder = Literal["bgr", "rgb", "bgra", "rgba"]


class PreprocessingError(ValueError):
    """Raised before malformed image data can reach OpenCV or RF-DETR."""


@dataclass(frozen=True)
class CropBounds:
    """Integer, end-exclusive crop bounds in the original BGR frame."""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def origin(self) -> tuple[int, int]:
        return self.x1, self.y1

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


@dataclass(frozen=True)
class RuntimeMaskSettings:
    """CPU foreground sampling limits, separate from every model's inputs.

    A zero maximum dimension explicitly selects the original native algorithm.
    Resampling is never anatomical validation or physical calibration.
    """

    maximum_dimension: int = 640
    maximum_pixels: int = 200_000
    configuration_warnings: tuple[str, ...] = field(default=(), compare=False, hash=False)

    def __post_init__(self) -> None:
        for value, minimum, name in (
            (self.maximum_dimension, 24, "maximum_dimension"),
            (self.maximum_pixels, 576, "maximum_pixels"),
        ):
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 0 or 0 < value < minimum:
                raise PreprocessingError(f"{name} must be zero or an integer of at least {minimum}.")
        if not isinstance(self.configuration_warnings, tuple) or not all(isinstance(item, str) for item in self.configuration_warnings):
            raise PreprocessingError("Runtime mask configuration warnings must be immutable strings.")
        if self.maximum_dimension == 0:
            object.__setattr__(self, "maximum_pixels", 0)

    @classmethod
    def native(cls) -> "RuntimeMaskSettings":
        return cls(maximum_dimension=0, maximum_pixels=0)

    @classmethod
    def from_environment(cls) -> "RuntimeMaskSettings":
        values, warnings = {}, []
        for name, field, default, minimum in (
            ("FISH_MASK_MAX_DIMENSION", "maximum_dimension", 640, 24),
            ("FISH_MASK_MAX_PIXELS", "maximum_pixels", 200_000, 576),
        ):
            raw = os.getenv(name)
            try:
                value = default if raw is None else int(raw)
                if value < 0 or 0 < value < minimum:
                    raise ValueError
            except (ValueError, TypeError):
                value = default
                warnings.append(f"{name} invalid; using {default}.")
            values[field] = value
        return cls(**values, configuration_warnings=tuple(warnings))

    def to_dict(self) -> dict[str, object]:
        return {"maximum_dimension": int(self.maximum_dimension), "maximum_pixels": int(self.maximum_pixels),
                "configuration_warnings": list(self.configuration_warnings)}


_ACTIVE_RUNTIME_MASK_SETTINGS: ContextVar[RuntimeMaskSettings | None] = ContextVar("runtime_mask_settings", default=None)
_ACTIVE_GRABCUT_INVOCATIONS: ContextVar[list[int] | None] = ContextVar("runtime_grabcut_invocations", default=None)


class RuntimeMaskContext:
    """Reuse masks and diagnostic features for exact ROIs in one source frame.

    Parent IDs and integer, end-exclusive native-pixel bounds are part of every
    key. A pixel digest also invalidates an entry if the source is edited in
    place. A padded measurement mask can only support a smaller ROI through
    an explicit, validated native-pixel projection. Contexts belong to one
    inspection frame, not a model or track, and must be discarded before
    processing the next frame.
    """

    def __init__(self, frame: Any, *, frame_id: int | str | None = None, settings: RuntimeMaskSettings | None = None, backend: str | None = None) -> None:
        self._frame = validate_image(frame, name="Runtime mask source")
        if settings is not None and not isinstance(settings, RuntimeMaskSettings):
            raise PreprocessingError("Runtime masks require RuntimeMaskSettings.")
        self._settings = settings or RuntimeMaskSettings.from_environment()
        from src.inference.experimental_segmentation import segmentation_backend, ExperimentalFrameSegmentation
        self.backend = segmentation_backend(backend)
        self._experimental = ExperimentalFrameSegmentation(self._frame, frame_id) if self.backend == "mobilesam_experimental" else None
        self.frame_id = frame_id
        self._masks: dict[tuple, tuple[np.ndarray | None, dict[str, object]]] = {}
        self._mask_dependencies: dict[tuple, tuple] = {}
        self._features: dict[tuple, Any] = {}
        self._lock = RLock()
        self._segmentation_calls = 0
        self._cache_hits = 0
        self._segmentation_seconds = 0.0
        self._lookup_seconds = 0.0
        self._feature_calls = 0
        self._feature_cache_hits = 0
        self._feature_seconds = 0.0
        self._projection_calls = 0
        self._projection_fallbacks = 0
        self._projection_seconds = 0.0
        self._stage_ms: dict[str, float] = {}
        self._native_pixels = self._working_pixels = self._downsized_calls = 0
        self._generation_failures = self._segmentation_rejections = self._settings_fallbacks = 0
        self._grabcut_executions = 0

    def is_for_frame(self, frame: Any) -> bool:
        """Require the exact original frame object, not just matching sizes."""
        return frame is self._frame

    def prepare_instances(self, parents, parts=(), associations=None, *, trusted_parts=(), reviewed_instances=None):
        if self._experimental is not None:
            with self._lock:
                self._experimental.prepare(parents, parts, associations, trusted_parts=trusted_parts, reviewed_instances=reviewed_instances)
                self._masks.clear()
                self._features.clear()
                self._mask_dependencies.clear()

    def segmentation_report(self, parent_id):
        return self._experimental.report(parent_id) if self._experimental is not None else None

    def trusted_body_mask(self, parent_id, bounds):
        return self._experimental.body_mask(parent_id, bounds) if self._experimental is not None else (None, {})

    def _roi_key(self, parent_id: int | str, bounds: CropBounds, *, settings: RuntimeMaskSettings | None = None) -> tuple[tuple, np.ndarray]:
        if isinstance(parent_id, bool) or not isinstance(parent_id, (Integral, str)):
            raise PreprocessingError("Runtime mask parent ID must be an integer or string.")
        if isinstance(parent_id, Integral):
            parent_id = int(parent_id)
        if not isinstance(bounds, CropBounds) or any(
            isinstance(value, bool) or not isinstance(value, Integral)
            for value in (bounds.x1, bounds.y1, bounds.x2, bounds.y2)
        ):
            raise PreprocessingError("Runtime masks require exact integer CropBounds.")
        frame = validate_image(self._frame, name="Runtime mask source")
        height, width = frame.shape[:2]
        if not (0 <= bounds.x1 < bounds.x2 <= width and 0 <= bounds.y1 < bounds.y2 <= height):
            raise PreprocessingError("Runtime mask bounds must lie inside their original frame.")
        crop = frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
        digest = blake2b(np.ascontiguousarray(crop), digest_size=16).digest()
        return (parent_id, bounds, digest, settings or self._settings), crop

    @staticmethod
    def _freeze(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            frozen = value.copy()
            frozen.setflags(write=False)
            return frozen
        if isinstance(value, dict):
            return {key: RuntimeMaskContext._freeze(item) for key, item in value.items()}
        if isinstance(value, list):
            return [RuntimeMaskContext._freeze(item) for item in value]
        if isinstance(value, tuple):
            return tuple(RuntimeMaskContext._freeze(item) for item in value)
        return deepcopy(value)

    @staticmethod
    def _read(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            # A view cannot re-enable writing while its cached base is frozen.
            view = value.view()
            view.setflags(write=False)
            return view
        if isinstance(value, dict):
            return {key: RuntimeMaskContext._read(item) for key, item in value.items()}
        if isinstance(value, list):
            return [RuntimeMaskContext._read(item) for item in value]
        if isinstance(value, tuple):
            return tuple(RuntimeMaskContext._read(item) for item in value)
        return deepcopy(value)

    def _has_current_mask(self, key: tuple) -> bool:
        dependency = self._mask_dependencies.get(key)
        if dependency is not None:
            current_source_key, _ = self._roi_key(dependency[0], dependency[1], settings=dependency[3])
            if current_source_key != dependency:
                # Padding changes can alter GrabCut even when all target
                # pixels stay unchanged. Its derived diagnostic must expire.
                self._masks.pop(key, None)
                self._mask_dependencies.pop(key, None)
                self._discard_mask_features(key)
        return key in self._masks

    def _discard_mask_features(self, key: tuple) -> None:
        self._features = {
            feature_key: value for feature_key, value in self._features.items()
            if feature_key[:len(key)] != key
        }

    def get(self, parent_id: int | str, bounds: CropBounds, *, settings: RuntimeMaskSettings | None = None) -> tuple[np.ndarray | None, dict[str, object]]:
        """Return the validated foreground mask, caching unavailable results too."""
        started = perf_counter()
        if settings is not None and not isinstance(settings, RuntimeMaskSettings):
            raise PreprocessingError("Runtime masks require RuntimeMaskSettings.")
        active_settings = settings or self._settings
        with self._lock:
            key, crop = self._roi_key(parent_id, bounds, settings=active_settings)
            if self.backend != "grabcut":
                if self._experimental is not None and not self._experimental.is_current():
                    self._masks.clear()
                    self._features.clear()
                    self._mask_dependencies.clear()
                hit = key in self._masks
                if hit:
                    self._cache_hits += 1
                else:
                    if self._experimental is not None:
                        mask, metadata = self._experimental.get(parent_id, bounds)
                    else:
                        mask, metadata = None, {"status": "unavailable", "reason": "Additional segmentation is disabled for this frame.",
                                                "backend": "geometry_only", "measurement_validated": False}
                    metadata.update(frame_id=self.frame_id, parent_track_id=parent_id,
                                    crop_bounds=[bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                                    coordinate_space="crop_local_native_pixels", grabcut_invocations=0)
                    self._masks[key] = (self._freeze(mask), self._freeze(metadata))
                mask, metadata = self._masks[key]
                result = self._read(metadata)
                result["cache_hit"] = hit
                self._lookup_seconds += max(0.0, perf_counter() - started)
                return self._read(mask), result
            hit = self._has_current_mask(key)
            segmentation_seconds = 0.0
            if hit:
                self._cache_hits += 1
            else:
                segmentation_started = perf_counter()
                token = _ACTIVE_RUNTIME_MASK_SETTINGS.set(active_settings)
                invocations: list[int] = []
                invocation_token = _ACTIVE_GRABCUT_INVOCATIONS.set(invocations)
                try:
                    mask, metadata = generate_runtime_fish_mask(crop)
                    metadata = dict(metadata)
                    if mask is not None:
                        if mask.shape != crop.shape[:2]:
                            raise PreprocessingError("Runtime foreground mask does not match its exact ROI.")
                        mask = np.asarray(mask, dtype=bool)
                except Exception as error:
                    # Caller/frame/ROI validation above remains strict. Once
                    # that scope is established, foreground extraction is an
                    # optional diagnostic: a failed algorithm must not prevent
                    # either crop-mode caller from running Model 2 grading.
                    # Cache the failure just like an ordinary rejected mask.
                    mask = None
                    self._generation_failures += 1
                    metadata = {
                        "status": "unavailable",
                        "reason": "Runtime foreground mask processing failed.",
                        "error_type": type(error).__name__,
                    }
                finally:
                    _ACTIVE_RUNTIME_MASK_SETTINGS.reset(token)
                    _ACTIVE_GRABCUT_INVOCATIONS.reset(invocation_token)
                segmentation_seconds = perf_counter() - segmentation_started
                metadata = {
                    **metadata,
                    "frame_id": self.frame_id,
                    "parent_track_id": key[0],
                    "crop_bounds": [int(bounds.x1), int(bounds.y1), int(bounds.x2), int(bounds.y2)],
                    "coordinate_space": "crop_local_native_pixels",
                    "scope": "current_parent_crop",
                    "mask_algorithm": metadata.get("mask_algorithm", "grabcut_rect3_close5_open3_largest_v1"),
                    "segmentation_settings": active_settings.to_dict(),
                    "grabcut_invocations": len(invocations),
                    "measurement_validated": False,
                    "mask_validated_for_cracks": False,
                    "segmentation_ms": round(segmentation_seconds * 1000, 3),
                }
                self._masks[key] = (self._freeze(mask), self._freeze(metadata))
                self._segmentation_calls += 1
                self._segmentation_seconds += segmentation_seconds
                self._grabcut_executions += len(invocations)
                timings = metadata.get("stage_timings_ms")
                for stage, value in timings.items() if isinstance(timings, Mapping) else ():
                    if stage != "total" and isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value) and value >= 0:
                        self._stage_ms[str(stage)] = self._stage_ms.get(str(stage), 0.0) + float(value)
                for name, target in (("native_pixel_count", "_native_pixels"), ("working_pixel_count", "_working_pixels")):
                    value = metadata.get(name)
                    if isinstance(value, Integral) and not isinstance(value, bool) and value >= 0:
                        setattr(self, target, getattr(self, target) + int(value))
                sampling = metadata.get("sampling")
                self._downsized_calls += int(isinstance(sampling, Mapping) and bool(sampling.get("estimated")))
                self._segmentation_rejections += int(mask is None)
                self._settings_fallbacks += int(bool(active_settings.configuration_warnings))
            cached_mask, cached_metadata = self._masks[key]
            result_metadata = self._read(cached_metadata)
            result_metadata["cache_hit"] = hit
            self._lookup_seconds += max(0.0, perf_counter() - started - segmentation_seconds)
            return self._read(cached_mask), result_metadata

    def get_projected(
        self, parent_id: int | str, source_bounds: CropBounds, target_bounds: CropBounds,
        *, frame: np.ndarray, target_crop: np.ndarray,
        maximum_secondary_component_fraction: float = .02,
        minimum_source_retained_fraction: float = .95,
    ) -> tuple[np.ndarray | None, dict[str, object]]:
        """Crop one parent's padded mask into an independently validated ROI.

        This changes no image pixels, resizes no mask, and never overwrites an
        existing target entry, including a cached segmentation failure. The
        source is obtained within this context for the same parent and frame.
        Rejected projections fall back to segmentation of the exact target.
        """
        with self._lock:
            if not all(np.isfinite(value) and 0 <= value <= 1 for value in (
                maximum_secondary_component_fraction, minimum_source_retained_fraction,
            )):
                raise PreprocessingError("Projection validation fractions must be finite values in [0, 1].")
            if not self.is_for_frame(frame):
                raise PreprocessingError("Projected masks require their original source frame.")
            target_key, target_pixels = self._roi_key(parent_id, target_bounds)
            if not np.array_equal(target_crop, target_pixels):
                raise PreprocessingError("Projected mask target pixels differ from their source ROI.")
            if self._has_current_mask(target_key):
                return self.get(parent_id, target_bounds)
            if source_bounds == target_bounds:
                return self.get(parent_id, target_bounds)

            started = perf_counter()
            source_lookup_seconds = 0.0

            def fallback(reason):
                self._projection_fallbacks += 1
                self._projection_seconds += max(0.0, perf_counter() - started - source_lookup_seconds)
                mask, metadata = self.get(parent_id, target_bounds)
                metadata["projection_rejection_reason"] = reason
                return mask, metadata

            source_key, _ = self._roi_key(parent_id, source_bounds)
            if not (
                source_bounds.x1 <= target_bounds.x1 and source_bounds.y1 <= target_bounds.y1
                and source_bounds.x2 >= target_bounds.x2 and source_bounds.y2 >= target_bounds.y2
            ):
                return fallback("target_roi_not_contained_in_source_roi")
            try:
                source_started = perf_counter()
                source_mask, source_metadata = self.get(parent_id, source_bounds)
            except Exception:
                source_lookup_seconds = perf_counter() - source_started
                return fallback("source_mask_processing_failed")
            source_lookup_seconds = perf_counter() - source_started
            if source_mask is None or source_metadata.get("status") != "validated_for_features":
                return fallback("source_mask_unavailable_or_not_feature_validated")
            if source_metadata.get("projection") is not None:
                return fallback("source_mask_already_derived")
            if source_metadata.get("foreground_touches_initialization_boundary"):
                return fallback("source_foreground_touches_initialization_boundary")
            try:
                fractions = (
                    float(source_metadata.get("raw_second_component_fraction", 0.0)),
                    float(source_metadata.get("raw_largest_component_fraction", 1.0)),
                )
            except (TypeError, ValueError):
                return fallback("source_component_metadata_invalid")
            if not all(np.isfinite(value) and 0 <= value <= 1 for value in fractions):
                return fallback("source_component_metadata_invalid")
            if max(fractions[0], 1.0 - fractions[1]) > maximum_secondary_component_fraction:
                return fallback("source_mask_has_multiple_foreground_components")
            x = target_bounds.x1 - source_bounds.x1
            y = target_bounds.y1 - source_bounds.y1
            projected = source_mask[y:y + target_bounds.height, x:x + target_bounds.width]
            pixels = int(projected.sum())
            fraction = pixels / float(target_bounds.width * target_bounds.height)
            retained_fraction = pixels / max(1, int(source_mask.sum()))
            if pixels < 64 or not .05 <= fraction <= .98:
                return fallback("projected_mask_failed_area_validation")
            if retained_fraction < minimum_source_retained_fraction:
                return fallback("projected_mask_loses_parent_foreground")
            import cv2

            components, _, _, _ = cv2.connectedComponentsWithStats(projected.astype(np.uint8), 8)
            if components != 2:
                return fallback("projected_mask_has_multiple_foreground_components")
            # Check again after segmentation; a concurrent edit outside the
            # context lock must never produce stale source provenance.
            if self._roi_key(parent_id, source_bounds)[0] != source_key:
                return fallback("source_pixels_changed_during_projection")
            projection_seconds = max(0.0, perf_counter() - started - source_lookup_seconds)
            metadata = {
                "status": "validated_for_features",
                "source": "runtime_grabcut_padded_projection",
                "frame_id": self.frame_id, "parent_track_id": target_key[0],
                "crop_bounds": [int(target_bounds.x1), int(target_bounds.y1), int(target_bounds.x2), int(target_bounds.y2)],
                "coordinate_space": "crop_local_native_pixels", "scope": "current_parent_crop",
                "mask_algorithm": "native_roi_crop_of_grabcut_v1",
                "measurement_validated": False, "mask_validated_for_cracks": False,
                "foreground_pixels": pixels, "foreground_fraction": round(fraction, 6),
                "component_count": 1, "segmentation_ms": 0.0,
                "projection_ms": round(projection_seconds * 1000, 3),
                "projection": {
                    "method": "native_integer_roi_crop", "resized": False,
                    "source_crop_bounds": [int(source_bounds.x1), int(source_bounds.y1), int(source_bounds.x2), int(source_bounds.y2)],
                    "source_origin": [int(source_bounds.x1), int(source_bounds.y1)],
                    "target_offset_in_source": [int(x), int(y)],
                    "source_pixels_digest": source_key[2].hex(),
                    "target_pixels_digest": target_key[2].hex(),
                    "source_retained_fraction": round(retained_fraction, 6),
                    "area_validation_passed": True, "single_component_validation_passed": True,
                },
                "source_mask_metadata": source_metadata,
                "sampling": {**self._read(source_metadata.get("sampling", {})),
                             "native_output_shape": [int(target_bounds.height), int(target_bounds.width)]},
                "segmentation_settings": self._read(source_metadata.get("segmentation_settings", self._settings.to_dict())),
            }
            self._masks[target_key] = (self._freeze(projected), self._freeze(metadata))
            self._mask_dependencies[target_key] = source_key
            self._discard_mask_features(target_key)
            self._projection_calls += 1
            self._projection_seconds += projection_seconds
            result = self._read(metadata)
            result["cache_hit"] = False
            return self._read(self._masks[target_key][0]), result

    def cached_feature(
        self, parent_id: int | str, bounds: CropBounds,
        feature_name: str, factory: Callable[[], Any],
    ) -> Any:
        """Reuse a diagnostic only for the same parent, pixels, ROI and settings.

        ``feature_name`` must identify the algorithm and any settings affecting
        its result. Factories read this context's original ROI and must not
        mutate it. Failed factories are retried rather than cached.
        """
        if not isinstance(feature_name, str) or not feature_name:
            raise PreprocessingError("A cached feature requires an algorithm/settings name.")
        with self._lock:
            key, _ = self._roi_key(parent_id, bounds)
            if self._experimental is not None and not self._experimental.is_current():
                self._masks.clear()
                self._features.clear()
                self._mask_dependencies.clear()
            self._has_current_mask(key)
            feature_key = (*key, feature_name)
            if feature_key in self._features:
                self._feature_cache_hits += 1
            else:
                started = perf_counter()
                value = factory()
                self._feature_seconds += perf_counter() - started
                self._feature_calls += 1
                self._features[feature_key] = self._freeze(value)
            return self._read(self._features[feature_key])

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return {
                "scope": "one_original_frame",
                "frame_id": self.frame_id,
                "segmentation_calls": self._segmentation_calls,
                "cache_misses": self._segmentation_calls,
                "grabcut_executions": self._grabcut_executions,
                "cache_hits": self._cache_hits,
                "cache_entries": len(self._masks),
                "segmentation_ms": round(self._segmentation_seconds * 1000, 3) + (self._experimental.diagnostics().get("segmentation_ms", 0) if self._experimental else 0),
                "lookup_ms": round(self._lookup_seconds * 1000, 3),
                "feature_calls": self._feature_calls,
                "feature_cache_hits": self._feature_cache_hits,
                "feature_ms": round(self._feature_seconds * 1000, 3),
                "projection_calls": self._projection_calls,
                "projection_fallbacks": self._projection_fallbacks,
                "projection_ms": round(self._projection_seconds * 1000, 3),
                "segmentation_backend": "opencv_cpu_grabcut" if self.backend == "grabcut" else self.backend,
                "experimental_segmentation": self._experimental.diagnostics() if self._experimental else {},
                "segmentation_stage_ms": {stage: round(value, 3) for stage, value in self._stage_ms.items()},
                "native_pixels_processed": self._native_pixels,
                "working_pixels_processed": self._working_pixels,
                "downsized_calls": self._downsized_calls,
                "generation_failures": self._generation_failures,
                "segmentation_rejections": self._segmentation_rejections,
                "settings_fallbacks": self._settings_fallbacks,
                "segmentation_settings": self._settings.to_dict(),
            }


def ensure_uint8(image: Any, *, name: str = "Image") -> np.ndarray:
    """Return explicit, lossless-or-defined conversion to canonical ``uint8``.

    Float input may be in either [0, 1] or [0, 255].  Wider integer inputs are
    accepted only when their actual values already fit in [0, 255]; implicitly
    dividing arbitrary 16-bit images would silently change appearance.
    """

    if not isinstance(image, np.ndarray):
        raise PreprocessingError(f"{name} must be a NumPy array.")
    if image.size == 0:
        raise PreprocessingError(f"{name} must not be empty.")
    is_bool = np.issubdtype(image.dtype, np.bool_)
    if not np.issubdtype(image.dtype, np.number) and not is_bool:
        raise PreprocessingError(f"{name} must use a numeric pixel dtype, got {image.dtype}.")
    if np.issubdtype(image.dtype, np.complexfloating):
        raise PreprocessingError(f"{name} cannot use a complex pixel dtype.")
    if not np.isfinite(image).all():
        raise PreprocessingError(f"{name} contains NaN or infinite pixel values.")
    if image.dtype == np.uint8:
        return image
    if is_bool:
        return image.astype(np.uint8) * 255

    minimum = float(np.min(image))
    maximum = float(np.max(image))
    if minimum < 0.0 or maximum > 255.0:
        raise PreprocessingError(
            f"{name} pixel values must be in [0, 1] or [0, 255] before conversion to uint8; "
            f"received [{minimum:g}, {maximum:g}]."
        )
    if np.issubdtype(image.dtype, np.floating) and maximum <= 1.0:
        return np.rint(image * 255.0).astype(np.uint8)
    return np.rint(image).astype(np.uint8)


def normalize_image_channels(
    image: np.ndarray,
    *,
    source_color_order: ColorOrder = "bgr",
    name: str = "Image",
) -> np.ndarray:
    """Normalize grayscale/RGB(A) inputs into the application's H x W x 3 BGR form."""

    if image.ndim == 2:
        import cv2

        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3 or image.shape[0] == 0 or image.shape[1] == 0:
        raise PreprocessingError(f"{name} must be a non-empty H x W or H x W x C image.")
    channels = image.shape[2]
    if channels == 1:
        import cv2

        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if channels == 3:
        if source_color_order == "bgr":
            return image
        if source_color_order == "rgb":
            import cv2

            return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        raise PreprocessingError(f"{name} has 3 channels but source_color_order={source_color_order!r} requires 4.")
    if channels == 4:
        import cv2

        if source_color_order == "bgra":
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if source_color_order == "rgba":
            return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        raise PreprocessingError(f"{name} has 4 channels; specify source_color_order='bgra' or 'rgba'.")
    raise PreprocessingError(f"{name} has unsupported channel count {channels}; expected 1, 3, or 4.")


def validate_image(image: Any, *, name: str = "Image") -> np.ndarray:
    """Validate a canonical OpenCV BGR frame without copying or mutating it."""

    if image is None:
        raise PreprocessingError(f"{name} is None.")
    if not isinstance(image, np.ndarray):
        raise PreprocessingError(f"{name} must be an OpenCV NumPy array.")
    if image.size == 0 or image.ndim != 3 or image.shape[0] == 0 or image.shape[1] == 0:
        raise PreprocessingError(f"{name} must be a non-empty H x W x 3 BGR image.")
    if image.shape[2] != 3:
        raise PreprocessingError(f"{name} must have exactly 3 BGR channels, got {image.shape[2]}.")
    if image.dtype != np.uint8:
        raise PreprocessingError(f"{name} must use uint8 pixels, got {image.dtype}.")
    return image


def canonicalize_image(
    image: Any,
    *,
    source_color_order: ColorOrder = "bgr",
    name: str = "Image",
) -> np.ndarray:
    """Produce a canonical uint8 BGR image for application-level processing."""

    if image is None:
        raise PreprocessingError(f"{name} is None.")
    uint8 = ensure_uint8(image, name=name)
    normalized = normalize_image_channels(uint8, source_color_order=source_color_order, name=name)
    return validate_image(normalized, name=name)


def bgr_to_rgb(image: Any, *, name: str = "Image") -> np.ndarray:
    """Make the one color conversion required immediately before RF-DETR."""

    frame = validate_image(image, name=name)
    try:
        import cv2

        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except Exception as exc:  # pragma: no cover - only reached for broken OpenCV installs
        raise PreprocessingError(f"Unable to convert {name} from BGR to RGB: {exc}") from exc


def clamp_bbox(
    bbox: tuple[float, float, float, float] | list[float] | np.ndarray,
    frame_width: int,
    frame_height: int,
) -> tuple[float, float, float, float] | None:
    """Clamp an ``xyxy`` box to frame bounds and reject invalid/empty geometry."""

    if frame_width <= 0 or frame_height <= 0:
        return None
    values = np.asarray(bbox, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all():
        return None
    left, top, right, bottom = values.tolist()
    left = min(max(left, 0.0), float(frame_width))
    top = min(max(top, 0.0), float(frame_height))
    right = min(max(right, 0.0), float(frame_width))
    bottom = min(max(bottom, 0.0), float(frame_height))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def crop_fish(
    frame: Any,
    bbox: tuple[float, float, float, float] | list[float] | np.ndarray,
    *,
    padding: int = 0,
) -> tuple[np.ndarray, CropBounds]:
    """Extract a clean original-frame fish crop with floor/ceil-safe bounds."""

    source = validate_image(frame, name="Fish ROI source")
    if isinstance(padding, bool) or not isinstance(padding, Integral) or padding < 0:
        raise PreprocessingError("FISH_SEGMENTATION_ROI_PADDING must be a non-negative integer.")
    height, width = source.shape[:2]
    bounded = clamp_bbox(bbox, width, height)
    if bounded is None:
        raise PreprocessingError("Fish detection box is empty, malformed, or outside the source frame.")
    left, top, right, bottom = bounded
    x1 = max(0, int(np.floor(left)) - int(padding))
    y1 = max(0, int(np.floor(top)) - int(padding))
    x2 = min(width, int(np.ceil(right)) + int(padding))
    y2 = min(height, int(np.ceil(bottom)) + int(padding))
    if x2 <= x1 or y2 <= y1:
        raise PreprocessingError("Fish detection box produced an empty ROI.")
    bounds = CropBounds(x1, y1, x2, y2)
    crop = source[y1:y2, x1:x2]
    validate_image(crop, name="Fish ROI")
    return crop, bounds


def measurement_roi_padding(bbox: Any) -> int:
    """Keep the existing measurement background margin in native pixels."""
    values = np.asarray(bbox, dtype=np.float64)
    if values.shape != (4,) or not np.isfinite(values).all() or values[2] <= values[0] or values[3] <= values[1]:
        raise PreprocessingError("Measurement padding requires a valid parent detection box.")
    return max(8, int(np.ceil(.06 * max(values[2] - values[0], values[3] - values[1]))))


def crop_assigned_evidence(
    frame: Any,
    parent_bbox: Any,
    owned_bboxes: Any = (),
    *,
    padding: int = 0,
) -> tuple[np.ndarray, CropBounds]:
    """Keep already-associated native parts intact without changing ownership.

    Association accepts some boxes extending beyond a detector parent. A
    parent-only crop used to truncate those accepted pixels. Extend the ROI
    around that evidence and reuse the measurement margin for context only
    when extension is necessary. No extra detection is selected from the
    expanded pixels, and the Model 1 anchor remains unchanged.
    """
    source = validate_image(frame, name="Assigned evidence source")
    height, width = source.shape[:2]
    parent = clamp_bbox(parent_bbox, width, height)
    if parent is None:
        raise PreprocessingError("Assigned evidence requires a visible parent box.")
    envelope = list(parent)
    for box in owned_bboxes:
        bounded = clamp_bbox(box, width, height)
        if bounded is not None:
            envelope = [min(envelope[0], bounded[0]), min(envelope[1], bounded[1]),
                        max(envelope[2], bounded[2]), max(envelope[3], bounded[3])]
    # Validate the configured padding even if the adaptive margin is larger.
    if isinstance(padding, bool) or not isinstance(padding, Integral) or padding < 0:
        raise PreprocessingError("FISH_SEGMENTATION_ROI_PADDING must be a non-negative integer.")
    contextual_padding = max(padding, measurement_roi_padding(parent)) if envelope != list(parent) else padding
    return crop_fish(source, envelope, padding=contextual_padding)


def measurement_crop_bounds(frame: Any, bbox: Any) -> CropBounds:
    """Return the one shared padded ROI for measurement and mask projection."""
    _, bounds = crop_fish(frame, bbox, padding=measurement_roi_padding(bbox))
    return bounds


def translate_bbox_to_frame(
    bbox: tuple[float, float, float, float] | list[float] | np.ndarray,
    crop_bounds: CropBounds,
    frame_width: int,
    frame_height: int,
) -> tuple[float, float, float, float] | None:
    """Translate a crop-local box into bounded original-frame coordinates."""

    local = clamp_bbox(bbox, crop_bounds.width, crop_bounds.height)
    if local is None:
        return None
    left, top, right, bottom = local
    return clamp_bbox(
        (left + crop_bounds.x1, top + crop_bounds.y1, right + crop_bounds.x1, bottom + crop_bounds.y1),
        frame_width,
        frame_height,
    )


def resize_mask_to_crop(mask: Any, crop_bounds: CropBounds) -> np.ndarray:
    """Map a native RF-DETR mask to its crop size with nearest-neighbor sampling."""

    array = np.asarray(mask)
    if array.ndim != 2 or array.size == 0:
        raise PreprocessingError("Segmentation mask must be a non-empty 2-D array.")
    if not np.issubdtype(array.dtype, np.number) and not np.issubdtype(array.dtype, np.bool_):
        raise PreprocessingError("Segmentation mask must use a numeric or boolean dtype.")
    if not np.isfinite(array).all():
        raise PreprocessingError("Segmentation mask contains NaN or infinite values.")
    if array.shape != (crop_bounds.height, crop_bounds.width):
        import cv2

        array = cv2.resize(
            array.astype(np.float32),
            (crop_bounds.width, crop_bounds.height),
            interpolation=cv2.INTER_NEAREST,
        )
    return np.asarray(array > 0.5, dtype=bool)


def translate_mask_to_frame(
    mask: Any,
    crop_bounds: CropBounds,
    frame_width: int,
    frame_height: int,
) -> np.ndarray:
    """Place a crop-local binary mask into a bounded original-frame mask."""

    if frame_width <= 0 or frame_height <= 0:
        raise PreprocessingError("Frame dimensions must be positive for mask translation.")
    local = resize_mask_to_crop(mask, crop_bounds)
    output = np.zeros((frame_height, frame_width), dtype=bool)
    x1, y1 = max(0, crop_bounds.x1), max(0, crop_bounds.y1)
    x2, y2 = min(frame_width, crop_bounds.x2), min(frame_height, crop_bounds.y2)
    if x2 <= x1 or y2 <= y1:
        return output
    local_x1, local_y1 = x1 - crop_bounds.x1, y1 - crop_bounds.y1
    output[y1:y2, x1:x2] = local[local_y1 : local_y1 + (y2 - y1), local_x1 : local_x1 + (x2 - x1)]
    return output


def generate_runtime_fish_mask(
    image: Any, *, settings: RuntimeMaskSettings | None = None,
) -> tuple[np.ndarray | None, dict[str, object]]:
    """Estimate one crop's foreground using a bounded CPU working grid.

    Small crops follow the existing native algorithm. Larger masks are lifted
    back to the exact native crop shape, with their sampling footprint and
    estimated boundary recorded explicitly. This is neither anatomical mask
    validation nor physical calibration. Set the maximum dimension to zero
    to request the original full-resolution algorithm deliberately.
    """
    started = perf_counter()
    source = validate_image(image, name="Runtime fish crop")
    active = settings if settings is not None else _ACTIVE_RUNTIME_MASK_SETTINGS.get() or RuntimeMaskSettings.from_environment()
    if not isinstance(active, RuntimeMaskSettings):
        raise PreprocessingError("Runtime masks require RuntimeMaskSettings.")
    native_height, native_width = source.shape[:2]
    timings = {name: 0.0 for name in ("source_resize", "grabcut", "raw_components", "morphology", "final_components", "native_lift")}
    evidence: dict[str, object] = {
        "source": "runtime_grabcut_detector_crop", "segmentation_backend": "opencv_cpu_grabcut",
        "mask_algorithm": "grabcut_rect3_close5_open3_largest_v1",
        "segmentation_settings": active.to_dict(), "measurement_validated": False,
        "mask_validated_for_cracks": False, "native_pixel_count": native_height * native_width,
        "working_pixel_count": 0,
        "grabcut_invocations": 0,
    }

    def result(mask, **extra):
        return mask, {**evidence, **extra, "stage_timings_ms": {
            **{name: round(value, 3) for name, value in timings.items()},
            "total": round((perf_counter() - started) * 1000, 3),
        }}

    if native_height < 24 or native_width < 24:
        return result(None, status="unavailable", reason="Runtime fish crop is too small.")
    import cv2

    scale = 1.0
    if active.maximum_dimension:
        scale = min(scale, active.maximum_dimension / max(native_height, native_width))
        if active.maximum_pixels:
            scale = min(scale, np.sqrt(active.maximum_pixels / float(native_height * native_width)))
    height, width = max(1, int(native_height * scale)), max(1, int(native_width * scale))
    estimated = (height, width) != (native_height, native_width)
    sx, sy = native_width / width, native_height / height
    evidence["sampling"] = {
        "mode": "bounded_working_grid" if estimated else "native",
        "estimated": estimated, "native_shape": [native_height, native_width], "working_shape": [height, width],
        "native_output_shape": [native_height, native_width],
        "scale_to_native": [sx, sy], "mask_reconstruction": "nearest_neighbor" if estimated else "none",
        "boundary_sampling_footprint_native_px": [sx, sy], "native_boundary_validated": False,
        "uncertainty_interpretation": "Working-grid sampling footprint; not a validated anatomical error bound",
    }
    evidence["working_pixel_count"] = height * width
    if estimated:
        evidence["mask_algorithm"] = "bounded_grabcut_rect3_close5_open3_native_lift_v1"
        if min(height, width) < 12:
            evidence["working_pixel_count"] = 0
            return result(None, status="unavailable", reason="Bounded working grid has insufficient transverse resolution.")
        stage = perf_counter()
        source = cv2.resize(source, (width, height), interpolation=cv2.INTER_AREA)
        timings["source_resize"] = (perf_counter() - stage) * 1000
    border = max(1, min(height, width) // 24)
    background = np.zeros((1, 65), dtype=np.float64)
    foreground = np.zeros((1, 65), dtype=np.float64)
    stage = perf_counter()
    try:
        initial = np.zeros((height, width), dtype=np.uint8)
        evidence["grabcut_invocations"] = 1
        active_invocations = _ACTIVE_GRABCUT_INVOCATIONS.get()
        if active_invocations is not None:
            active_invocations.append(1)
        cv2.grabCut(source, initial, (border, border, width - 2 * border, height - 2 * border),
                    background, foreground, 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error as error:
        timings["grabcut"] = (perf_counter() - stage) * 1000
        return result(None, status="unavailable", reason=f"Foreground mask inference failed: {error}")
    timings["grabcut"] = (perf_counter() - stage) * 1000
    stage = perf_counter()
    mask = np.logical_or(initial == cv2.GC_FGD, initial == cv2.GC_PR_FGD).astype(np.uint8)
    # Boundary strips provide the same native-path contact test without two
    # potentially huge foreground-coordinate arrays.
    raw_contact = bool(mask[:border + 2].any() or mask[height - border - 2:].any()
                       or mask[:, :border + 2].any() or mask[:, width - border - 2:].any())
    _, _, raw_stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    raw_areas = sorted((int(value) for value in raw_stats[1:, cv2.CC_STAT_AREA]), reverse=True)
    timings["raw_components"] = (perf_counter() - stage) * 1000
    foreground_total = sum(raw_areas)
    evidence.update(
        raw_component_count=len(raw_areas),
        raw_largest_component_fraction=raw_areas[0] / foreground_total if foreground_total else 0.0,
        raw_second_component_fraction=raw_areas[1] / foreground_total if len(raw_areas) > 1 else 0.0,
        initialization_border_px=int(np.ceil(border * max(sx, sy))),
        initialization_border_working_px=border,
        foreground_touches_initialization_boundary=raw_contact,
        component_evidence_resolution="working_grid" if estimated else "native",
    )
    stage = perf_counter()
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    timings["morphology"] = (perf_counter() - stage) * 1000
    stage = perf_counter()
    components, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    timings["final_components"] = (perf_counter() - stage) * 1000
    if components <= 1:
        return result(None, status="unavailable", reason="Foreground mask has no connected component.")
    largest = int(np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1)
    mask = labels == largest
    working_pixels = int(mask.sum())
    fraction = working_pixels / float(height * width)
    if working_pixels < 64 or not .05 <= fraction <= .98:
        return result(None, status="unavailable", reason="Foreground mask failed area validation.",
                      foreground_pixels=working_pixels, foreground_fraction=round(fraction, 6),
                      foreground_pixel_count_space="working_grid" if estimated else "native")
    if estimated:
        stage = perf_counter()
        mask = cv2.resize(mask.astype(np.uint8), (native_width, native_height), interpolation=cv2.INTER_NEAREST).astype(bool)
        timings["native_lift"] = (perf_counter() - stage) * 1000
    pixels = int(mask.sum())
    return result(mask, status="validated_for_features", foreground_pixels=pixels,
                  foreground_fraction=round(pixels / float(native_height * native_width), 6),
                  foreground_pixel_count_space="native")
