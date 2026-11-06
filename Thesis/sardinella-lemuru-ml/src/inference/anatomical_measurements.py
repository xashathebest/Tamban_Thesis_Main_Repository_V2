"""Orientation-aware fish measurements from one silhouette mask.

Length follows the existing centerline profile, so horizontal, vertical, and
diagonal fish use the same axis. Width is the largest cross-section inside the
owned Body. The Head-to-Body size ratio is exclusive silhouette area. Missing
regions stay unmeasured; they are never filled with a guessed number.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import cv2
import numpy as np

from src.inference.fish_geometry import FishGeometryConfig, _aligned_profile
from src.inference.head_silhouette import HeadSilhouetteConfig, analyze_silhouette_ends


def _binary(mask: np.ndarray | None) -> np.ndarray | None:
    if mask is None:
        return None
    try:
        array = np.asarray(mask)
    except (TypeError, ValueError):
        return None
    if array.ndim != 2 or array.size == 0 or array.dtype.kind not in "buif":
        return None
    if array.dtype.kind == "f" and not np.isfinite(array).all():
        return None
    return np.asarray(array >= 0.5 if array.dtype.kind == "f" else array > 0, dtype=np.uint8)


def _selected(parts: Sequence[Any], region: str, minimum_confidence: float) -> list[Any]:
    selected = []
    for part in parts:
        name = part.get("region") if isinstance(part, dict) else getattr(part, "region", None)
        if name != region:
            continue
        try:
            confidence = float(part.get("confidence") if isinstance(part, dict) else part.confidence)
        except (TypeError, ValueError):
            continue
        if math.isfinite(confidence) and confidence >= minimum_confidence:
            selected.append(part)
    return selected


def _bbox(part: Any) -> tuple[float, float, float, float] | None:
    value = part.get("bbox") if isinstance(part, dict) else getattr(part, "bbox", None)
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or not all(math.isfinite(item) for item in box) or box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box  # type: ignore[return-value]


def _region_pixels(part: Any, shape: tuple[int, int], silhouette: np.ndarray) -> np.ndarray | None:
    canvas = np.zeros(shape, np.uint8)
    polygon = part.get("mask") if isinstance(part, dict) else getattr(part, "mask", None)
    if polygon:
        try:
            points = np.asarray(polygon, dtype=np.float64)
        except (TypeError, ValueError):
            return None
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            return None
        cv2.fillPoly(canvas, [np.rint(points).astype(np.int32)], 1)
    else:
        box = _bbox(part)
        if box is None:
            return None
        x1, y1 = max(0, math.floor(box[0])), max(0, math.floor(box[1]))
        x2, y2 = min(shape[1], math.ceil(box[2])), min(shape[0], math.ceil(box[3]))
        if x2 <= x1 or y2 <= y1:
            return None
        canvas[y1:y2, x1:x2] = 1
    return (canvas > 0) & (silhouette > 0)


def _centroid(pixels: np.ndarray) -> tuple[float, float] | None:
    count = int(pixels.sum())
    if count <= 0:
        return None
    ys, xs = np.nonzero(pixels)
    return float(xs.mean()), float(ys.mean())


def measure_mask_anatomy(
    mask: np.ndarray | None,
    parts: Sequence[Any] = (),
    *,
    config: FishGeometryConfig | None = None,
    head_config: HeadSilhouetteConfig | None = None,
    minimum_part_confidence: float = 0.25,
) -> dict[str, Any]:
    """Measure one crop-local silhouette without inventing absent anatomy."""

    settings = config or FishGeometryConfig()
    result: dict[str, Any] = {
        "status": "unavailable",
        "anatomical_length_px": None,
        "max_body_width_px": None,
        "width_to_length_ratio": None,
        "head_to_body_size_ratio": None,
        "orientation_degrees": None,
        "head_pixels": None,
        "body_pixels": None,
        "tail_pixels": None,
        "anterior_extension_px": None,
        "cut_end_confirmed": False,
        "cut_end_axis": None,
        "cut_character": None,
        "geometry_decision": None,
        "orientation_reliable": False,
        "posterior_source": None,
        "tail_anterior_end": None,
        "reasons": [],
        "method": "mobilesam_orientation_centerline_v1",
        "measurement_definition": (
            "Centerline length of the silhouette, maximum cross-section inside the owned Body, "
            "and exclusive Head silhouette pixels divided by exclusive Body silhouette pixels."
        ),
        "used_for_grading": False,
        "supporting_evidence": False,
    }
    binary = _binary(mask)
    if binary is None:
        result["reasons"].append("segmentation_mask_unavailable")
        return result
    pixels = int(binary.sum())
    if pixels < settings.minimum_mask_pixels:
        result["reasons"].append("insufficient_foreground_pixels")
        return result
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    largest = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    silhouette = (labels == largest).astype(np.uint8)
    secondary = 1.0 - int(stats[largest, cv2.CC_STAT_AREA]) / pixels
    if secondary > settings.maximum_secondary_component_fraction:
        result["reasons"].append("multiple_foreground_components")
    if silhouette[0].any() or silhouette[-1].any() or silhouette[:, 0].any() or silhouette[:, -1].any():
        result["reasons"].append("silhouette_touches_frame_boundary")
    try:
        diagnostics, columns, widths, _centers, transform, lower, upper = _aligned_profile(silhouette)
    except (cv2.error, ValueError, FloatingPointError, ZeroDivisionError):
        result["reasons"].append("orientation_profile_failed")
        return result
    length = float(diagnostics["fish_length_px"])
    orientation = float(diagnostics["orientation_degrees"])
    if not math.isfinite(length) or length <= 1 or not math.isfinite(orientation):
        result["reasons"].append("orientation_profile_failed")
        return result
    axis_ratio = float(diagnostics["principal_axis_ratio"])
    result["orientation_axis_ratio"] = round(axis_ratio, 6)
    result["orientation_reliable"] = axis_ratio >= settings.minimum_axis_ratio
    if axis_ratio < settings.minimum_axis_ratio:
        result["reasons"].append("orientation_uncertain")
    result.update(
        status="measured",
        anatomical_length_px=round(length, 4),
        orientation_degrees=round(orientation % 180.0, 4),
        component_count=int(count - 1),
        secondary_component_fraction=round(secondary, 6),
    )
    axis = np.array((math.cos(math.radians(orientation)), math.sin(math.radians(orientation))))

    def project(point: tuple[float, float]) -> float:
        return float(point[0] * axis[0] + point[1] * axis[1])

    shape = silhouette.shape
    body_parts = _selected(parts, "Body", minimum_part_confidence)
    head_parts = _selected(parts, "Head", minimum_part_confidence)
    tail_parts = _selected(parts, "Tail", minimum_part_confidence)
    if len(body_parts) > 1:
        result["reasons"].append("multiple_body_associations")
    if len(head_parts) > 1:
        result["reasons"].append("multiple_head_associations")
    body = _region_pixels(body_parts[0], shape, silhouette) if len(body_parts) == 1 else None
    head = _region_pixels(head_parts[0], shape, silhouette) if len(head_parts) == 1 else None
    tail = _region_pixels(tail_parts[0], shape, silhouette) if len(tail_parts) == 1 else None
    if body is not None and int(body.sum()) >= settings.minimum_mask_pixels:
        aligned = cv2.warpAffine(
            body.astype(np.uint8), transform, tuple(reversed(diagnostics["aligned_mask_shape"])),
            flags=cv2.INTER_NEAREST,
        )
        available = aligned[:, columns].any(axis=0)
        if int(available.sum()) >= settings.minimum_body_profile_pixels:
            lower = np.argmax(aligned[:, columns] != 0, axis=0)
            upper = aligned.shape[0] - 1 - np.argmax(aligned[::-1, columns] != 0, axis=0)
            section = np.where(available, upper - lower + 1.0, 0.0)
            width = float(section[available].max())
            if math.isfinite(width) and width >= settings.minimum_transverse_pixels:
                result["max_body_width_px"] = round(width, 4)
                result["width_to_length_ratio"] = round(width / length, 6)
    elif body_parts and body is not None:
        result["reasons"].append("insufficient_body_pixels")
    elif not body_parts:
        result["reasons"].append("body_not_detected")
    head_count = int(head.sum()) if head is not None else 0
    body_count = int(body.sum()) if body is not None else 0
    tail_count = int(tail.sum()) if tail is not None else 0
    result.update(head_pixels=head_count, body_pixels=body_count, tail_pixels=tail_count)
    if head is not None and body is not None and head_count > 0 and body_count > 0:
        shared = int(np.count_nonzero(head & body))
        head_only = head_count - shared
        body_only = body_count - shared
        if head_only > 0 and body_only > 0:
            result["head_to_body_size_ratio"] = round(head_only / body_only, 6)
        else:
            result["reasons"].append("head_body_regions_not_separable")
    ends = analyze_silhouette_ends(widths, lower, upper, config=head_config)
    if ends is not None:
        result.update(
            cut_end_confirmed=ends["cut_end_confirmed"],
            cut_end_axis=ends["cut_end_axis"],
            cut_character=ends["cut_character"],
            geometry_decision=ends["geometry_decision"],
            representative_body_width_px=ends["representative_body_width_px"],
            cut_end_metrics=ends,
        )
        if ends["cut_end_confirmed"]:
            result["posterior_source"] = "silhouette_morphology"
    elif tail is None:
        result["reasons"].append("posterior_end_ambiguous")
    body_center = _centroid(body) if body is not None else None
    tail_center = _centroid(tail) if tail is not None else None
    if body_center is not None and tail_center is not None and body_count > 0:
        separation = project(tail_center) - project(body_center)
        if abs(separation) < 0.18 * length:
            result["reasons"].append("tail_body_polarity_uncertain")
        else:
            posterior = 1.0 if separation > 0 else -1.0
            ys, xs = np.nonzero(silhouette)
            anterior = -(xs * axis[0] + ys * axis[1]) * posterior
            body_ys, body_xs = np.nonzero(body)
            body_anterior = -(body_xs * axis[0] + body_ys * axis[1]) * posterior
            extension = float(anterior.max() - body_anterior.max())
            result["anterior_extension_px"] = round(extension, 4)
            result["tail_body_separation_px"] = round(abs(separation), 4)
            result["tail_anterior_end"] = "minimum_projection" if posterior > 0 else "maximum_projection"
            result["posterior_source"] = "tail_landmark" if result.get("posterior_source") != "silhouette_morphology" else "tail_landmark_and_silhouette"
            tip_limit = float(anterior.max()) - 3.0
            if tail is not None and np.any((-(xs * axis[0] + ys * axis[1]) * posterior >= tip_limit) & tail[ys, xs]):
                result["reasons"].append("tail_reaches_anterior_tip")
    elif tail_parts and body_center is not None:
        result["reasons"].append("tail_not_on_silhouette")
    measurable = result["anatomical_length_px"] is not None and not any(
        reason in result["reasons"] for reason in ("orientation_profile_failed", "insufficient_foreground_pixels")
    )
    result["supporting_evidence"] = bool(measurable and result["max_body_width_px"] is not None)
    return result
