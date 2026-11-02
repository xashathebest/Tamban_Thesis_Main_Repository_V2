"""Native-pixel feature intermediates with one-parent, one-frame lifetime.

This context owns an immutable input snapshot. It never infers anatomy, resizes
pixels, changes masks, calibrates measurements, or modifies a grade. Consumers
retain numeric summaries, not these temporary full-resolution maps.
"""
from __future__ import annotations

from hashlib import blake2b
import operator

import numpy as np

from src.features.color import (
    ColorSettings, _validate_inputs, color_summary_from_maps, rgb_to_hsv, rgb_to_lab,
)
from src.features.texture import TextureSettings, texture_features_from_gray
from src.preprocessing.scientific_image_utils import PreprocessingError


class RuntimeFeatureContext:
    """Reuse exact color/texture maps only within the captured parent crop."""

    def __init__(self, image_rgb: np.ndarray) -> None:
        image = np.asarray(image_rgb)
        if image.ndim != 3 or image.shape[2] != 3 or not image.size:
            raise PreprocessingError("Runtime features require a non-empty HxWx3 RGB crop.")
        self._source = np.array(image, copy=True, order="C")
        self._source.flags.writeable = False
        self._rgb = self._hsv = self._lightness = self._gray = None
        self._colors: dict[tuple, dict[str, object]] = {}
        self._textures: dict[tuple, dict[str, object]] = {}
        self._counts = dict.fromkeys((
            "normalization_calls", "hsv_conversions", "lab_lightness_conversions", "gray_conversions",
            "color_requests", "color_computations", "color_cache_hits",
            "texture_requests", "texture_computations", "texture_cache_hits",
        ), 0)

    def _normalized(self) -> np.ndarray:
        if self._rgb is None:
            self._rgb, _ = _validate_inputs(self._source, np.ones(self._source.shape[:2], dtype=bool))
            self._rgb.flags.writeable = False
            self._counts["normalization_calls"] += 1
        return self._rgb

    @staticmethod
    def _mask(mask: np.ndarray | None, shape: tuple[int, int]) -> tuple[np.ndarray, bytes]:
        binary = np.ones(shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
        if binary.shape != shape or not binary.any():
            raise PreprocessingError("Feature masks must match their exact native ROI and contain foreground.")
        digest = blake2b(np.ascontiguousarray(binary).tobytes(), digest_size=16).digest()
        return binary, digest

    def color_summary(
        self, bbox: tuple[int, int, int, int], mask: np.ndarray | None = None,
        settings: ColorSettings = ColorSettings(),
    ) -> dict[str, object]:
        self._counts["color_requests"] += 1
        settings.validate()
        try:
            if len(bbox) != 4 or any(isinstance(value, (bool, np.bool_)) for value in bbox):
                raise TypeError
            left, top, right, bottom = (operator.index(value) for value in bbox)
        except (TypeError, ValueError):
            raise PreprocessingError("Color summaries require integer native ROI bounds.") from None
        height, width = self._source.shape[:2]
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise PreprocessingError("Color summary ROI is outside its parent crop.")
        binary, digest = self._mask(mask, (bottom - top, right - left))
        key = (left, top, right, bottom, digest, settings)
        if key in self._colors:
            self._counts["color_cache_hits"] += 1
            return dict(self._colors[key])
        rgb = self._normalized()
        if self._hsv is None:
            self._hsv = rgb_to_hsv(rgb)
            self._hsv.flags.writeable = False
            self._counts["hsv_conversions"] += 1
        if self._lightness is None:
            self._lightness = rgb_to_lab(rgb, lightness_only=True)
            self._lightness.flags.writeable = False
            self._counts["lab_lightness_conversions"] += 1
        values, _ = color_summary_from_maps(
            self._hsv[top:bottom, left:right], self._lightness[top:bottom, left:right], binary, settings,
        )
        self._counts["color_computations"] += 1
        self._colors[key] = values
        return dict(values)

    def release_color_maps(self) -> None:
        """Release large color maps before allocating LBP/gradient arrays."""
        self._hsv = self._lightness = None

    def texture_summary(
        self, mask: np.ndarray, settings: TextureSettings = TextureSettings(),
    ) -> dict[str, object]:
        self._counts["texture_requests"] += 1
        settings.validate()
        binary, digest = self._mask(mask, self._source.shape[:2])
        key = (digest, settings)
        if key in self._textures:
            self._counts["texture_cache_hits"] += 1
            return dict(self._textures[key])
        if self._gray is None:
            rgb = self._normalized()
            # Match the existing scientific texture definition, not OpenCV's
            # different uint8 grayscale conversion used by crack candidates.
            self._gray = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
            self._gray.flags.writeable = False
            self._rgb = None
            self._counts["gray_conversions"] += 1
        values = texture_features_from_gray(self._gray, binary, settings)
        self._textures[key] = values
        self._counts["texture_computations"] += 1
        return dict(values)

    def diagnostics(self) -> dict[str, object]:
        return {
            "scope": "one_parent_crop_snapshot", "coordinate_space": "crop_local_native_pixels",
            "resized": False, "color_space": "normalized_sRGB_HSV_CIE_L_D65",
            "texture_luminance": "BT709_float64", **self._counts,
        }
