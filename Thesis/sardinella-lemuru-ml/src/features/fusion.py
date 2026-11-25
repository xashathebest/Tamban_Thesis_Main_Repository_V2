"""Native, whole-owned-fish measurements with explicit validation attestations.

Extraction success is not validation. Reviews and validated capture profiles
are supplied separately and never inferred from detector or SAM confidence.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import cv2

from src.features.color import ColorSettings, extract_color_features
from src.features.damage import analyze_surface_damage
from src.features.texture import TextureSettings, extract_texture_features
from src.inference.decision_fusion import (
    EXTRACTOR_VERSION, FAMILIES, FEATURE_KEYS, REQUIRED_CHECKS, finite, source_matches,
)


def _size_geometry_checks(geometry, mask, metadata):
    """Check owned anatomical endpoints, local normal widths and ratio identity.

    The 0.1 cosine tolerance is an engineering alignment check, not a fish
    quality cutoff. Anatomical identity still requires explicit review below.
    """
    checks = dict.fromkeys(("anatomical_endpoints", "perpendicular_widths", "proportions"), False)
    if mask is None:
        return checks
    drawing = geometry.get("visualization", {})
    drawing = drawing if isinstance(drawing, Mapping) else {}
    bounds = metadata.get("crop_bounds")
    try:
        path = np.asarray(drawing.get("length_path"), dtype=float)
        width = np.asarray(drawing.get("width_axis"), dtype=float)
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                or path.ndim != 2 or path.shape[1] != 2 or len(path) < 2
                or width.shape != (2, 2) or not np.isfinite(path).all() or not np.isfinite(width).all()):
            return checks
        origin = np.asarray(bounds[:2], dtype=float)
        def owned(points):
            local = np.rint(points - origin).astype(int)
            if (local[:, 0] < 0).any() or (local[:, 1] < 0).any() or (local[:, 0] >= mask.shape[1]).any() or (local[:, 1] >= mask.shape[0]).any():
                return False
            return bool(mask[local[:, 1], local[:, 0]].all())
        checks["anatomical_endpoints"] = owned(path[[0, -1]]) and float(np.linalg.norm(path[-1] - path[0])) > 0
        midpoints = (path[1:] + path[:-1]) / 2
        tangent = np.diff(path, axis=0)[int(np.argmin(np.linalg.norm(midpoints - width.mean(axis=0), axis=1)))]
        normal = width[1] - width[0]
        denominator = float(np.linalg.norm(tangent) * np.linalg.norm(normal))
        count = max(2, min(4096, int(np.ceil(np.linalg.norm(normal))) + 1))
        checks["perpendicular_widths"] = (denominator > 0 and abs(float(tangent @ normal)) / denominator <= .1
                                          and owned(np.linspace(width[0], width[1], count)))
        length, body_length, body_width = (finite(geometry.get(k)) for k in ("fish_length_px", "body_profile_length_px", "max_body_width_px"))
        relative, body_ratio = (finite(geometry.get(k)) for k in ("relative_width_ratio", "body_width_to_length_ratio"))
        checks["proportions"] = bool(length and body_length and body_width and length > 0 and body_length > 0 and body_width > 0
            and relative is not None and body_ratio is not None and np.isclose(relative, body_width / length, atol=1e-5)
            and np.isclose(body_ratio, body_width / body_length, atol=1e-5))
    except (ValueError, TypeError, IndexError, OverflowError):
        return checks
    return checks


def extract_fusion_measurements(image_rgb, whole_mask, *, fish_id, frame_id, source=None,
                                geometry=None, validation=None, mask_metadata=None, texture_values=None):
    source = source if isinstance(source, Mapping) else {}
    geometry = geometry if isinstance(geometry, Mapping) else {}
    validation = validation if isinstance(validation, Mapping) else {}
    metadata = mask_metadata if isinstance(mask_metadata, Mapping) else {}
    image = np.asarray(image_rgb)
    mask = np.asarray(whole_mask) if whole_mask is not None else None
    usable = (image.dtype == np.uint8 and image.ndim == 3 and image.shape[2] == 3
              and mask is not None and mask.shape == image.shape[:2] and mask.dtype.kind in "buif"
              and np.isfinite(mask).all() and np.isin(mask, [0, 1, 255]).all() and mask.any())
    owned = mask.astype(bool) if usable else None
    bound = source_matches(validation, fish_id=fish_id, frame_id=frame_id, source=source)
    provenance = validation.get("validation_provenance", {})
    provenance = provenance if isinstance(provenance, Mapping) else {}
    reviewed = (bound and validation.get("reviewed") is True
                and all(isinstance(provenance.get(k), str) and provenance[k].strip()
                        for k in ("reviewer", "review_id", "reference_set_id")))
    common = {
        "complete_mask": usable and reviewed and validation.get("complete_mask") is True,
        "ownership": usable and reviewed and validation.get("ownership_validated") is True,
        "measurement": reviewed and validation.get("measurement_validated") is True,
    }
    if any(metadata.get(key) is True for key in ("ownership_ambiguous", "clipped", "partial_silhouette", "overlapping")):
        common.update(complete_mask=False, ownership=False)
    sampling = metadata.get("sampling", {})
    sampling = sampling if isinstance(sampling, Mapping) else {}
    if metadata.get("parent_isolation_reliable") is False or sampling.get("estimated") is True:
        common["ownership"] = False
    complete_count = finite(metadata.get("full_frame_foreground_pixels"))
    if usable and complete_count is not None and int(owned.sum()) != complete_count:
        common["complete_mask"] = False
    result = {"extractor_version": EXTRACTOR_VERSION, "reference_unit": "whole_fish",
              "fish_id": fish_id, "frame_id": frame_id,
              "source_id": source.get("source_id"), "frame_pixels_sha256": source.get("frame_pixels_sha256"),
              "capture_profile_id": validation.get("capture_profile_id"), "features": {},
              "owned_pixel_count": int(owned.sum()) if usable else 0,
              "source_review_valid": reviewed, "validation_provenance": dict(provenance)}
    values = {family: {} for family in FAMILIES}
    values["size"] = {key: geometry.get(key) for key in FEATURE_KEYS["size"]}
    size_geometry_checks = _size_geometry_checks(geometry, owned, metadata)
    result["size_geometry_checks"] = size_geometry_checks
    errors = {}
    if usable:
        try:
            original = extract_color_features(image, owned, ColorSettings(), summary_only=True)
            color = original
            lighting = validation.get("lighting", {})
            lighting = lighting if isinstance(lighting, Mapping) else {}
            gains, offsets = lighting.get("rgb_gains"), lighting.get("rgb_offsets")
            corrected = (reviewed and lighting.get("validated") is True
                         and lighting.get("profile_id") == result["capture_profile_id"]
                         and isinstance(gains, list) and isinstance(offsets, list)
                         and len(gains) == len(offsets) == 3
                         and all(finite(v) is not None for v in gains + offsets)
                         and all(0 < v <= 4 for v in gains) and all(-255 <= v <= 255 for v in offsets))
            if corrected:
                adjusted = image.astype(float) * gains + offsets
                color = extract_color_features(np.clip(np.rint(adjusted), 0, 255).astype(np.uint8), owned, ColorSettings(), summary_only=True)
                result["lighting_clipped_fraction"] = float(np.any((adjusted < 0) | (adjusted > 255), axis=2)[owned].mean())
            result["lighting_correction_applied"] = bool(corrected)
            result["original_color_measurements"] = {key: original.get(key) for key in FEATURE_KEYS["color"]}
            values["color"] = {key: color.get(key) for key in FEATURE_KEYS["color"]}
        except (ValueError, TypeError, KeyError, cv2.error) as error:
            errors["color"] = str(error)
        try:
            texture = texture_values if isinstance(texture_values, Mapping) else extract_texture_features(image, owned, TextureSettings())
            values["texture"] = {key: texture.get(key) for key in FEATURE_KEYS["texture"]}
            result["texture_sample_counts"] = {key: texture.get(key) for key in ("glcm_valid_pair_count", "lbp_valid_pixel_count")}
        except (ValueError, TypeError, KeyError, cv2.error) as error:
            errors["texture"] = str(error)
        try:
            # Original-RGB contrast, elongation and repeated-line rejection
            # distinguish candidates from spots, one-sided shadows and scales.
            # This detector's lack of candidates is not proof of an intact fish.
            damage = analyze_surface_damage(image, owned, mask_metadata=metadata)
            locations = damage.get("locations", [])
            length = sum(location.get("skeleton_length_px") or 0. for location in locations)
            fish_length = finite(geometry.get("fish_length_px"))
            values["cracks"] = {"crack_area_fraction": float(np.count_nonzero(damage["overlay_mask"]) / owned.sum()),
                                "crack_length_to_fish_length": length / fish_length if fish_length and fish_length > 0 else None}
            result["crack_candidate_count"] = len(locations)
            result["crack_measurement_scope"] = damage.get("analysis_scope")
        except (ValueError, TypeError, KeyError, cv2.error) as error:
            errors["cracks"] = str(error)
    for family in FAMILIES:
        approval = validation.get(family, {})
        approval = approval if isinstance(approval, Mapping) else {}
        checks = {key: bool(common.get(key, reviewed and approval.get(key) is True)) for key in REQUIRED_CHECKS[family]}
        if family == "size":
            for key, passed in size_geometry_checks.items():
                checks[key] = checks[key] and passed
            checks["measurement"] = checks["measurement"] and geometry.get("measurement_validated") is True
            checks["proportions"] = checks["proportions"] and geometry.get("body_region_validated") is True
        if family == "color":
            checks["lighting_calibrated"] = checks["lighting_calibrated"] and result.get("lighting_correction_applied") is True
        if family == "texture":
            counts = result.get("texture_sample_counts", {})
            pairs = finite(counts.get("glcm_valid_pair_count"))
            centers = finite(counts.get("lbp_valid_pixel_count"))
            checks["glcm_valid"] = checks["glcm_valid"] and pairs is not None and pairs > 0 and pairs.is_integer()
            checks["lbp_valid"] = checks["lbp_valid"] and centers is not None and centers > 0 and centers.is_integer()
        # A reviewed full crack measurement can cover defects outside the
        # candidate detector's documented scope, including reviewed negatives.
        if family == "cracks" and reviewed and approval.get("measurement_source") == "reviewed_structural_measurement":
            supplied = approval.get("values", {})
            if isinstance(supplied, Mapping) and all(finite(supplied.get(k)) is not None and supplied[k] >= 0 for k in FEATURE_KEYS[family]):
                values[family] = dict(supplied)
                errors.pop(family, None)
            else:
                checks["measurement"] = False
        quality = finite(approval.get("measurement_reliability", 1.))
        quality = quality if quality is not None and 0 < quality <= 1 and all(checks.values()) else 0.
        if family == "color":
            quality *= 1 - result.get("lighting_clipped_fraction", 0.)
        result["features"][family] = {"values": {key: finite(values[family].get(key)) for key in FEATURE_KEYS[family]},
                                      "checks": checks, "measurement_reliability": quality,
                                      "measurement_error": errors.get(family)}
    return result
