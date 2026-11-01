"""Conservative, rotation-aware measurements of an individual fish silhouette.

These are pixel measurements from segmentation, not anatomical ground truth.
The PCA axis locates one-pixel cross sections, rather than measuring an oriented
rectangle. A smooth silhouette centerline reaches both silhouette tips. Bent,
ambiguous, clipped, or poorly associated silhouettes are withheld. This module
never contributes to grading and never certifies a measurement as validated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np
import yaml


@dataclass(frozen=True)
class FishGeometryConfig:
    """Engineering quality gates; these are not biological class thresholds."""

    minimum_mask_pixels: int = 128
    maximum_secondary_component_fraction: float = 0.02
    maximum_hole_fraction: float = 0.03
    minimum_axis_ratio: float = 2.0
    maximum_centerline_tortuosity: float = 1.06
    maximum_centerline_deviation_width_ratio: float = 0.25
    maximum_profile_residual_width_ratio: float = 0.12
    minimum_part_confidence: float = 0.25
    minimum_part_inside_fraction: float = 0.95
    minimum_body_profile_pixels: int = 8
    minimum_transverse_pixels: int = 4

    def __post_init__(self) -> None:
        if self.minimum_mask_pixels < 16 or self.minimum_body_profile_pixels < 3:
            raise ValueError("Geometry minimum pixel counts are too small.")
        if self.minimum_transverse_pixels < 2:
            raise ValueError("minimum_transverse_pixels must be at least two.")
        for name in (
            "maximum_secondary_component_fraction", "maximum_hole_fraction",
            "maximum_centerline_deviation_width_ratio", "maximum_profile_residual_width_ratio",
            "minimum_part_confidence", "minimum_part_inside_fraction",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between zero and one.")
        if not math.isfinite(self.minimum_axis_ratio) or self.minimum_axis_ratio <= 1:
            raise ValueError("minimum_axis_ratio must exceed one.")
        if not math.isfinite(self.maximum_centerline_tortuosity) or self.maximum_centerline_tortuosity < 1:
            raise ValueError("maximum_centerline_tortuosity must be at least one.")


@dataclass(frozen=True)
class PhysicalCalibration:
    """A reviewed scale, tied to the original image resolution and source.

    Camera exposure/white-balance calibration is not a physical calibration.
    A scale must be reviewed for the same camera, acquisition geometry, and
    measurement plane; ``source_id`` identifies that fixed acquisition context.
    """

    validated: bool = False
    calibration_id: str | None = None
    pixels_per_cm: float | None = None
    reference_frame_size: tuple[int, int] | None = None
    source_id: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PhysicalCalibration":
        size = data.get("reference_frame_size")
        frame_size = (tuple(int(v) for v in size)
                      if isinstance(size, (list, tuple)) and len(size) == 2
                      and all(isinstance(v, Integral) and not isinstance(v, bool) and v > 0 for v in size)
                      else None)
        supplied_scale = data.get("pixels_per_cm")
        scale = (float(supplied_scale) if isinstance(supplied_scale, Real)
                 and not isinstance(supplied_scale, bool) and math.isfinite(supplied_scale)
                 and supplied_scale > 0 else None)
        return cls(
            validated=data.get("validated") is True,
            calibration_id=data.get("calibration_id"),
            pixels_per_cm=scale,
            reference_frame_size=frame_size,  # type: ignore[arg-type]
            source_id=data.get("source_id"),
        )


def _configuration(path: str | Path | None) -> Mapping[str, Any]:
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "configs" / "fish_geometry.yaml"
    with config_path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, Mapping):
        raise ValueError("Fish geometry configuration must be a mapping.")
    return payload


def load_fish_geometry_config(path: str | Path | None = None) -> FishGeometryConfig:
    return FishGeometryConfig(**_configuration(path).get("measurement", {}))


def load_physical_calibration(path: str | Path | None = None) -> PhysicalCalibration:
    return PhysicalCalibration.from_mapping(_configuration(path).get("physical_calibration", {}))


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if all(hasattr(value, key) for key in ("x1", "y1", "x2", "y2")):
        value = (value.x1, value.y1, value.x2, value.y2)
    try:
        values = tuple(float(v) for v in value)
        if len(values) == 4 and all(math.isfinite(v) for v in values) and values[2] > values[0] and values[3] > values[1]:
            return values  # type: ignore[return-value]
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _field(part: Any, name: str, default: Any = None) -> Any:
    return part.get(name, default) if isinstance(part, Mapping) else getattr(part, name, default)


def _inside_fraction(inner: Sequence[float], outer: Sequence[float]) -> float:
    width = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    height = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return width * height / ((inner[2] - inner[0]) * (inner[3] - inner[1]))


def _iou(first: Sequence[float], second: Sequence[float]) -> float:
    intersection = _inside_fraction(first, second) * (first[2] - first[0]) * (first[3] - first[1])
    union = (first[2] - first[0]) * (first[3] - first[1]) + (second[2] - second[0]) * (second[3] - second[1]) - intersection
    return intersection / union if union else 0.0


def _calibration_payload(
    calibration: PhysicalCalibration, frame_shape: Sequence[int] | None,
    source_context: str | Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_id = source_context.get("source_id") if isinstance(source_context, Mapping) else source_context
    result: dict[str, Any] = {
        "validated": False, "configured_validated": calibration.validated is True,
        "applied": False, "status": "Not calibrated", "reason": "physical_calibration_not_validated",
        "calibration_id": calibration.calibration_id,
        "pixels_per_cm": (float(calibration.pixels_per_cm)
                          if isinstance(calibration.pixels_per_cm, Real) and not isinstance(calibration.pixels_per_cm, bool)
                          and math.isfinite(calibration.pixels_per_cm) else None),
        "reference_frame_size": list(calibration.reference_frame_size) if calibration.reference_frame_size else None,
        "source_id": calibration.source_id,
    }
    scale = calibration.pixels_per_cm
    if calibration.validated is not True:
        return result
    if (not isinstance(scale, Real) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0
            or not isinstance(calibration.calibration_id, str) or not calibration.calibration_id.strip()
            or not isinstance(calibration.source_id, str) or not calibration.source_id.strip()
            or not isinstance(calibration.reference_frame_size, (list, tuple)) or len(calibration.reference_frame_size) != 2
            or any(not isinstance(v, Integral) or isinstance(v, bool) or v <= 0 for v in calibration.reference_frame_size)):
        result["reason"] = "physical_calibration_incomplete"
        return result
    current_size = (int(frame_shape[1]), int(frame_shape[0])) if frame_shape is not None and len(frame_shape) >= 2 else None
    if current_size != tuple(calibration.reference_frame_size) or source_id != calibration.source_id:
        result.update(status="Context mismatch", reason="physical_calibration_context_mismatch")
        return result
    result.update(validated=True, status="Available", reason=None)
    return result


def _aligned_profile(binary: np.ndarray) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return native-pixel silhouette sections, preserving a full tip-to-tip span."""
    moments = cv2.moments(binary, binaryImage=True)
    count = moments["m00"]
    covariance = np.array([[moments["mu20"], moments["mu11"]], [moments["mu11"], moments["mu02"]]]) / count
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    axis = eigenvectors[:, -1]
    if axis[0] < 0 or (abs(axis[0]) < 1e-10 and axis[1] < 0):
        axis = -axis
    normal = np.array([-axis[1], axis[0]])
    ys, xs = np.nonzero(binary)
    longitudinal = xs * axis[0] + ys * axis[1]
    transverse = xs * normal[0] + ys * normal[1]
    offset = np.array([2.0 - longitudinal.min(), 2.0 - transverse.min()])
    transform = np.array([[*axis, offset[0]], [*normal, offset[1]]], dtype=np.float64)
    size = (int(math.ceil(np.ptp(longitudinal))) + 5, int(math.ceil(np.ptp(transverse))) + 5)
    aligned = cv2.warpAffine(binary, transform, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    columns = np.flatnonzero(aligned.any(axis=0))
    lower = np.argmax(aligned[:, columns] != 0, axis=0).astype(float)
    upper = aligned.shape[0] - 1 - np.argmax(aligned[::-1, columns] != 0, axis=0).astype(float)
    widths = upper - lower + 1.0
    centers = (lower + upper) / 2.0
    normalized = (columns - columns[0]) / max(1, columns[-1] - columns[0]) * 2.0 - 1.0
    coefficients = np.polynomial.polynomial.polyfit(normalized, centers, 3, w=np.sqrt(widths))
    centerline = np.polynomial.polynomial.polyval(normalized, coefficients)
    length = float(np.hypot(np.diff(columns), np.diff(centerline)).sum() + 1.0)
    chord = float(math.hypot(columns[-1] - columns[0], centerline[-1] - centerline[0]) + 1.0)
    straight = np.interp(columns, (columns[0], columns[-1]), (centerline[0], centerline[-1]))
    coordinates = np.column_stack((columns, centerline))
    original_centers = (coordinates - offset) @ np.column_stack((axis, normal)).T
    diagnostics = {
        "fish_length_px": round(length, 4),
        "orientation_degrees": round(math.degrees(math.atan2(axis[1], axis[0])) % 180.0, 4),
        "principal_axis_ratio": round(math.sqrt(max(float(eigenvalues[-1]), 0) / max(float(eigenvalues[0]), 1e-9)), 6),
        "centerline_tortuosity": round(length / chord, 6),
        "centerline_deviation_width_ratio": round(float(np.max(np.abs(centerline - straight))) / max(float(widths.max()), 1.0), 6),
        "profile_residual_width_ratio": round(float(np.sqrt(np.mean((centers - centerline) ** 2))) / max(float(widths.max()), 1.0), 6),
        "longitudinal_gap_pixels": int(columns[-1] - columns[0] + 1 - len(columns)),
        "profile_bin_width_px": 1,
        "aligned_mask_shape": list(aligned.shape),
    }
    return diagnostics, columns, widths, original_centers, transform


def measure_fish_geometry(
    mask: np.ndarray | None,
    parts: Sequence[Any] = (),
    *,
    parent_bbox: Sequence[float] | None = None,
    crop_bounds: Any = None,
    frame_shape: Sequence[int] | None = None,
    overlapping: bool = False,
    association_reliable: bool = False,
    mask_metadata: Mapping[str, Any] | None = None,
    config: FishGeometryConfig | Mapping[str, Any] | None = None,
    physical_calibration: PhysicalCalibration | Mapping[str, Any] | None = None,
    source_context: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure a crop-local silhouette and its associated crop-local Body.

    ``parent_bbox``/``crop_bounds`` are full-frame xyxy coordinates; ``parts``
    are crop-local, matching ``mask``. Explicit parent-association evidence is
    required. Raw inputs are never modified, and failures retain candidate
    diagnostics separately from the public measured fields.
    """
    settings = config if isinstance(config, FishGeometryConfig) else FishGeometryConfig(**(config or {}))
    calibration = physical_calibration if isinstance(physical_calibration, PhysicalCalibration) else PhysicalCalibration.from_mapping(physical_calibration or {})
    metadata = dict(mask_metadata or {})
    output: dict[str, Any] = {
        "fish_length_px": None, "max_body_width_px": None, "relative_width_ratio": None,
        "fish_length_cm": None, "max_body_width_cm": None, "orientation_degrees": None,
        "reliability": "Unavailable", "status": "unavailable", "reasons": [],
        "method": "segmentation_centerline_profile_v1", "measurement_validated": False,
        "measurement_validation_status": "Not validated", "used_for_grading": False,
        "measurement_definition": "Silhouette centerline length and maximum transverse silhouette width within the associated Body region",
        "mask_source": metadata.get("source", "supplied_per_fish_mask"),
        "body_region_source": None, "candidate_measurements": {},
        "physical_calibration": _calibration_payload(calibration, frame_shape, source_context),
    }
    reasons: list[str] = output["reasons"]
    parent, bounds = _bbox(parent_bbox), _bbox(crop_bounds)
    context_reasons = metadata.get("context_reliability_reasons", [])
    if isinstance(context_reasons, (list, tuple)) and all(isinstance(reason, str) for reason in context_reasons):
        reasons.extend(reason.strip() for reason in context_reasons if reason.strip())
    else:
        reasons.append("invalid_context_reliability_metadata")
    if overlapping:
        reasons.append("overlapping_parent_fish")
    if association_reliable is not True:
        reasons.append("parent_association_uncertain")
    expected_parent_id = metadata.get("expected_parent_id")
    declared_parent_id = metadata.get("parent_track_id", metadata.get("instance_id"))
    if (expected_parent_id is not None and declared_parent_id is not None
            and str(expected_parent_id) != str(declared_parent_id)):
        reasons.append("mask_parent_mismatch")
    if metadata.get("clipped") or metadata.get("mask_clipped"):
        reasons.append("segmentation_reported_clipped")
    if metadata.get("foreground_touches_initialization_boundary"):
        reasons.append("silhouette_may_be_truncated")
    if parent is not None and frame_shape is not None and len(frame_shape) >= 2:
        if parent[0] <= 0 or parent[1] <= 0 or parent[2] >= int(frame_shape[1]) or parent[3] >= int(frame_shape[0]):
            reasons.append("parent_touches_frame_boundary")
    reasons[:] = list(dict.fromkeys(reasons))
    # Missing segmentation cannot erase already observed overlap or clipping.
    # Unknown ownership alone leaves an unavailable historical measurement.
    if any(reason != "parent_association_uncertain" for reason in reasons):
        output.update(status="unreliable", reliability="Unreliable")
    if mask is None:
        reasons.append("per_fish_segmentation_unavailable")
        return output
    try:
        array = np.asarray(mask)
        if array.ndim != 2 or not array.size or array.dtype.kind not in "buif" or not np.isfinite(array).all():
            reasons.append("invalid_segmentation_mask")
            return output
        binary = np.asarray(array >= 0.5 if array.dtype.kind == "f" else array > 0, dtype=np.uint8)
    except (TypeError, ValueError):
        reasons.append("invalid_segmentation_mask")
        return output
    pixels = int(binary.sum())
    if pixels < settings.minimum_mask_pixels:
        reasons.append("insufficient_foreground_pixels")
        return output
    output.update(status="unreliable", reliability="Unreliable")
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    largest = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    largest_pixels = int(stats[largest, cv2.CC_STAT_AREA])
    secondary_fraction = 1.0 - largest_pixels / pixels
    try:
        supplied_secondary_fraction = float(metadata.get("secondary_component_fraction", 0.0))
        raw_second_fraction = float(metadata.get("raw_second_component_fraction", 0.0))
        raw_largest_fraction = float(metadata.get("raw_largest_component_fraction", 1.0))
        if any(not math.isfinite(value) or not 0 <= value <= 1
               for value in (supplied_secondary_fraction, raw_second_fraction, raw_largest_fraction)):
            raise ValueError("Invalid component metadata fractions.")
        secondary_fraction = max(secondary_fraction, supplied_secondary_fraction, raw_second_fraction, 1.0 - raw_largest_fraction)
    except (ValueError, TypeError):
        reasons.append("invalid_component_metadata")
    if secondary_fraction > settings.maximum_secondary_component_fraction:
        reasons.append("multiple_foreground_components")
    silhouette = (labels == largest).astype(np.uint8)
    if silhouette[0].any() or silhouette[-1].any() or silhouette[:, 0].any() or silhouette[:, -1].any():
        reasons.append("silhouette_touches_crop_boundary")
    contours, _ = cv2.findContours(silhouette, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(silhouette)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    hole_fraction = float((filled - silhouette).sum()) / max(1, int(filled.sum()))
    if hole_fraction > settings.maximum_hole_fraction:
        reasons.append("segmentation_has_large_holes")
    if parent is None or bounds is None or frame_shape is None or len(frame_shape) < 2:
        reasons.append("frame_or_parent_geometry_missing")
    else:
        h, w = binary.shape
        frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
        if abs(bounds[2] - bounds[0] - w) > 1 or abs(bounds[3] - bounds[1] - h) > 1:
            reasons.append("mask_crop_dimensions_mismatch")
        if (bounds[0] < 0 or bounds[1] < 0 or bounds[2] > frame_w or bounds[3] > frame_h
                or _inside_fraction(parent, bounds) < settings.minimum_part_inside_fraction):
            reasons.append("parent_crop_context_mismatch")
        local_parent = (parent[0] - bounds[0], parent[1] - bounds[1], parent[2] - bounds[0], parent[3] - bounds[1])
        left, top = max(0, math.floor(local_parent[0])), max(0, math.floor(local_parent[1]))
        right, bottom = min(w, math.ceil(local_parent[2])), min(h, math.ceil(local_parent[3]))
        contained_pixels = int(silhouette[top:bottom, left:right].sum()) if right > left and bottom > top else 0
        if contained_pixels / max(1, largest_pixels) < settings.minimum_part_inside_fraction:
            reasons.append("foreground_outside_parent")
        silhouette_moments = cv2.moments(silhouette, binaryImage=True)
        centroid = (silhouette_moments["m10"] / largest_pixels, silhouette_moments["m01"] / largest_pixels)
        if not (local_parent[0] <= centroid[0] <= local_parent[2] and local_parent[1] <= centroid[1] <= local_parent[3]):
            reasons.append("foreground_parent_mismatch")
    diagnostics, columns, widths, centers, transform = _aligned_profile(silhouette)
    diagnostics.update(foreground_pixels=pixels, component_count=component_count - 1,
                       secondary_component_fraction=round(secondary_fraction, 6), hole_fraction=round(hole_fraction, 6),
                       raw_component_count=metadata.get("raw_component_count"),
                       initialization_border_px=metadata.get("initialization_border_px"))
    output["candidate_measurements"] = diagnostics
    if diagnostics["principal_axis_ratio"] < settings.minimum_axis_ratio:
        reasons.append("orientation_uncertain")
    if (diagnostics["centerline_tortuosity"] > settings.maximum_centerline_tortuosity
            or diagnostics["centerline_deviation_width_ratio"] > settings.maximum_centerline_deviation_width_ratio):
        reasons.append("curved_silhouette_requires_validated_centerline")
    if diagnostics["profile_residual_width_ratio"] > settings.maximum_profile_residual_width_ratio:
        reasons.append("irregular_silhouette_profile")
    if diagnostics["longitudinal_gap_pixels"]:
        reasons.append("discontinuous_longitudinal_profile")
    if float(np.median(widths)) < settings.minimum_transverse_pixels:
        reasons.append("insufficient_transverse_resolution")
    body_candidates = []
    for part in parts:
        try:
            confidence = float(_field(part, "confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        box = _bbox(_field(part, "bbox"))
        if _field(part, "region") == "Body" and box and math.isfinite(confidence) and confidence >= settings.minimum_part_confidence:
            body_candidates.append((confidence, box, part))
    body_candidates.sort(key=lambda item: item[0], reverse=True)
    if not body_candidates:
        reasons.append("associated_body_region_unavailable")
    else:
        _, body_box, body_part = body_candidates[0]
        diagnostics["body_bbox_crop_local"] = list(body_box)
        if any(_iou(body_box, candidate[1]) < 0.5 for candidate in body_candidates[1:]):
            reasons.append("multiple_body_associations")
        if parent is not None and bounds is not None:
            local_parent = (parent[0] - bounds[0], parent[1] - bounds[1], parent[2] - bounds[0], parent[3] - bounds[1])
            if _inside_fraction(body_box, local_parent) < settings.minimum_part_inside_fraction:
                reasons.append("body_outside_parent")
        body_columns = ((centers[:, 0] >= body_box[0]) & (centers[:, 0] <= body_box[2])
                        & (centers[:, 1] >= body_box[1]) & (centers[:, 1] <= body_box[3]))
        body_polygon = _field(body_part, "mask")
        output["body_region_source"] = "associated_body_bbox_longitudinal_region"
        if body_polygon is not None:
            try:
                polygon = np.asarray(body_polygon, dtype=np.float64)
                if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or not np.isfinite(polygon).all():
                    raise ValueError("Invalid Body polygon.")
                if (polygon.min() < -1 or polygon[:, 0].max() > binary.shape[1]
                        or polygon[:, 1].max() > binary.shape[0]):
                    raise ValueError("Body polygon outside crop.")
                body_mask = np.zeros_like(silhouette)
                cv2.fillPoly(body_mask, [np.rint(polygon).astype(np.int32)], 1)
                area = int(body_mask.sum())
                if area < settings.minimum_mask_pixels or float((body_mask & silhouette).sum()) / max(1, area) < settings.minimum_part_inside_fraction:
                    reasons.append("body_segmentation_not_associated_with_fish")
                aligned_body = cv2.warpAffine(body_mask & silhouette, transform,
                                             tuple(reversed(diagnostics["aligned_mask_shape"])),
                                             flags=cv2.INTER_NEAREST)
                available = aligned_body[:, columns].any(axis=0)
                lower = np.argmax(aligned_body[:, columns] != 0, axis=0)
                upper = aligned_body.shape[0] - 1 - np.argmax(aligned_body[::-1, columns] != 0, axis=0)
                widths = np.where(available, upper - lower + 1.0, 0.0)
                body_columns &= available
                output["body_region_source"] = "associated_body_segmentation"
            except (TypeError, ValueError, cv2.error):
                reasons.append("invalid_body_segmentation")
        if int(body_columns.sum()) < settings.minimum_body_profile_pixels:
            reasons.append("insufficient_associated_body_profile")
        else:
            body_width = float(widths[body_columns].max())
            diagnostics["max_body_width_px"] = round(body_width, 4)
            diagnostics["relative_width_ratio"] = round(body_width / diagnostics["fish_length_px"], 6)
            if body_width < settings.minimum_transverse_pixels:
                reasons.append("insufficient_body_width_resolution")
            if not 0 < diagnostics["relative_width_ratio"] < 1:
                reasons.append("implausible_silhouette_dimensions")
    output["reasons"] = list(dict.fromkeys(reasons))
    if output["reasons"]:
        return output
    output.update(status="measured", reliability="Reliable pixel geometry")
    for name in ("fish_length_px", "max_body_width_px", "relative_width_ratio", "orientation_degrees"):
        output[name] = diagnostics[name]
    if output["physical_calibration"]["validated"]:
        output["fish_length_cm"] = round(output["fish_length_px"] / calibration.pixels_per_cm, 6)
        output["max_body_width_cm"] = round(output["max_body_width_px"] / calibration.pixels_per_cm, 6)
        output["physical_calibration"].update(applied=True, status="Applied")
    return output
