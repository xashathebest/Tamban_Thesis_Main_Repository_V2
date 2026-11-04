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


def _review_provenance(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip())) or (isinstance(value, Mapping) and bool(value))


def _complete_native_silhouette(metadata, bounds, frame_shape, pixels=None):
    """Distinguish a tight ROI from real truncation using the native source."""
    provenance = metadata.get("candidate_provenance", {})
    foreground = _bbox(metadata.get("full_frame_foreground_bbox"))
    if (not isinstance(provenance, Mapping) or provenance.get("coordinate_space") != "original_frame"
            or frame_shape is None or len(frame_shape) < 2 or bounds is None or foreground is None
            or provenance.get("mask_shape") != list(frame_shape[:2])):
        return False
    height, width = frame_shape[:2]
    if not (0 < foreground[0] and 0 < foreground[1] and foreground[2] < width and foreground[3] < height
            and bounds[0] <= foreground[0] and bounds[1] <= foreground[1]
            and bounds[2] >= foreground[2] and bounds[3] >= foreground[3]):
        return False
    retained = metadata.get("full_frame_foreground_pixels")
    return pixels is None or (isinstance(retained, Integral) and not isinstance(retained, bool) and retained == pixels)


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


def _aligned_profile(binary: np.ndarray):
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
    return diagnostics, columns, widths, original_centers, transform, lower, upper


def _geometry_visualization(
    *, bounds, frame_shape, metadata, reasons, centers, columns, widths,
    transform, lower, upper, body_columns, diagnostics, contours,
    body_box=None, body_part=None, body_pixels=None,
):
    """Expose observed profile coordinates without promoting rejected metrics.

    A sampled/unreviewed native-coordinate silhouette can be inspected as an
    estimate. Failed ownership, association, shape, or placement checks do not
    establish a corresponding fish and therefore do not supply display lines.
    """
    permitted_estimate_reasons = {
        "resampled_foreground_requires_native_validation",
        "experimental_mask_requires_ownership_validation",
        "body_pixel_support_unvalidated",
    }
    ownership = metadata.get("ownership", {})
    provenance = metadata.get("candidate_provenance", {})
    parent_id = metadata.get("expected_parent_id", metadata.get("parent_track_id"))
    native_shape = list(frame_shape[:2]) if frame_shape is not None and len(frame_shape) >= 2 else None
    isolated_native_candidate = (
        metadata.get("source") == "mobilesam_experimental_candidate"
        and metadata.get("backend") == "mobilesam_experimental"
        and metadata.get("experimental") is True
        and metadata.get("parent_isolation_reliable") is True
        and parent_id is not None
        and isinstance(ownership, Mapping) and isinstance(provenance, Mapping)
        and ownership.get("status") == "checks_passed_unvalidated"
        and ownership.get("engineering_checks_passed") is True
        and ownership.get("mask_geometry_checks_passed") is True
        and ownership.get("reasons") == [] and ownership.get("conflicting_parent_ids") == []
        and ownership.get("coordinate_space") == "original_frame"
        and ownership.get("frame_shape") == native_shape
        and provenance.get("coordinate_space") == "original_frame"
        and provenance.get("mask_shape") == native_shape
        and str(ownership.get("parent_id")) == str(parent_id)
        and str(provenance.get("parent_id")) == str(parent_id)
    )
    if isolated_native_candidate:
        # Detector rectangles can overlap while the native instance-mask
        # ownership checks still pass. Permit their existing computed axes for
        # inspection only; the scalar reliability/grade gates below stay intact.
        permitted_estimate_reasons.add("overlapping_parent_fish")
    body_only_reasons = {
        "associated_body_region_unavailable", "multiple_body_associations", "body_outside_parent",
        "invalid_body_segmentation", "body_mask_parent_mismatch", "body_pixel_support_unvalidated",
        "body_segmentation_not_associated_with_fish", "fragmented_body_pixel_support",
        "insufficient_associated_body_profile", "insufficient_body_width_resolution",
    }
    result = {
        "coordinate_space": "original_frame", "status": "unavailable", "measured": False,
        "frame_id": metadata.get("frame_id"),
        "parent_track_id": metadata.get("expected_parent_id", metadata.get("parent_track_id", metadata.get("instance_id"))),
        "frame_width_px": int(frame_shape[1]) if frame_shape is not None and len(frame_shape) >= 2 else None,
        "frame_height_px": int(frame_shape[0]) if frame_shape is not None and len(frame_shape) >= 2 else None,
        "reasons": list(reasons), "used_for_grading": False,
        "measurement_validated": False,
        "bbox_overlap_display_only": bool(isolated_native_candidate and "overlapping_parent_fish" in reasons),
    }
    if (bounds is None or frame_shape is None or len(frame_shape) < 2
            or any(reason not in permitted_estimate_reasons | body_only_reasons for reason in reasons)):
        return result
    offset = np.array((bounds[0], bounds[1]))
    inverse = cv2.invertAffineTransform(transform)

    def to_frame(points):
        local = np.asarray(points, dtype=np.float64)
        original = local @ inverse[:, :2].T + inverse[:, 2] + offset
        return np.round(original, 3).tolist()

    # Preserve both actual centerline endpoints and its estimated path. Width
    # sections remain perpendicular to the same PCA coordinate system.
    path_indices = np.unique(np.linspace(0, len(centers) - 1, min(512, len(centers))).astype(int))
    result.update(
        status="estimated", measured=not bool(reasons), crop_bounds=list(bounds),
        principal_axis=np.round(np.array((centers[0], centers[-1])) + offset, 3).tolist(),
        length_path=np.round(centers[path_indices] + offset, 3).tolist(),
        length_method="native_silhouette_polynomial_centerline",
        pixel_extent_convention="Pixel-center spans; reported lengths and section widths include one pixel of support.",
    )
    body_indices = np.flatnonzero(body_columns)
    body_blockers = [reason for reason in reasons if reason in body_only_reasons - permitted_estimate_reasons]
    result["body_width_status"] = "unavailable" if body_blockers else "estimated"
    result["body_width_reasons"] = body_blockers
    if not body_blockers and len(body_indices) and diagnostics.get("max_body_width_px") is not None:
        widest = int(body_indices[np.argmax(widths[body_indices])])
        result["width_axis"] = to_frame(((columns[widest], lower[widest]), (columns[widest], upper[widest])))
        middle = body_indices[len(body_indices) // 4:len(body_indices) - len(body_indices) // 4]
        # A median of an even number of sections need not itself be an observed
        # width. Draw a real section, and disclose its value independently.
        difference = np.abs(widths[middle] - diagnostics["representative_body_width_px"])
        nearest = middle[np.isclose(difference, difference.min())]
        representative = int(nearest[np.argmin(np.abs(nearest - np.median(middle)))])
        result["representative_width_axis"] = to_frame(
            ((columns[representative], lower[representative]), (columns[representative], upper[representative])))
        result["representative_width_axis_value_px"] = round(float(widths[representative]), 4)
        result["representative_width_axis_method"] = "Observed central Body section nearest the median central-section width."
    contour = max(contours, key=cv2.contourArea)
    boundary = cv2.approxPolyDP(contour, 1., True).reshape(-1, 2).astype(float) + offset
    result["silhouette_boundary"] = np.round(boundary, 3).tolist()
    if body_blockers:
        return result
    polygon = _field(body_part, "mask") if body_part is not None else None
    if body_pixels is not None:
        body_contours, _ = cv2.findContours(body_pixels, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if body_contours:
            polygon = cv2.approxPolyDP(max(body_contours, key=cv2.contourArea), 1., True).reshape(-1, 2)
    if polygon is not None or body_box is not None:
        body_boundary = (np.asarray(polygon, dtype=float) if polygon is not None else
                         np.array(((body_box[0], body_box[1]), (body_box[2], body_box[1]),
                                   (body_box[2], body_box[3]), (body_box[0], body_box[3])))) + offset
        result.update(body_region_boundary=np.round(body_boundary, 3).tolist(),
                      body_boundary_kind="segmentation" if polygon is not None else "detection_box_approximation")
    return result


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
    body_mask: np.ndarray | None = None,
    body_mask_metadata: Mapping[str, Any] | None = None,
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
    body_metadata = dict(body_mask_metadata or {})
    output: dict[str, Any] = {
        "fish_length_px": None, "max_body_width_px": None, "relative_width_ratio": None,
        "fish_length_cm": None, "max_body_width_cm": None, "orientation_degrees": None,
        "reliability": "Unavailable", "status": "unavailable", "reasons": [],
        "method": "segmentation_centerline_profile_v1", "measurement_validated": False,
        "measurement_validation_status": "Not validated", "used_for_grading": False,
        "measurement_definition": "Silhouette centerline length and maximum transverse silhouette width within the associated Body region",
        "mask_source": metadata.get("source", "supplied_per_fish_mask"),
        "body_region_source": None, "candidate_measurements": {},
        "representative_body_width_px": None, "whole_fish_max_width_px": None,
        "whole_fish_length_to_width_ratio": None, "body_profile_length_px": None,
        "body_width_to_length_ratio": None, "body_width_profile_cv": None,
        "ownership_validated": False, "body_region_validated": False,
        "validation_provenance": None,
        "units": {"length": "px", "width": "px", "ratios": "dimensionless"},
        "measurement_source_id": source_context.get("source_id") if isinstance(source_context, Mapping) else source_context,
        "physical_calibration": _calibration_payload(calibration, frame_shape, source_context),
        "sampling": dict(metadata["sampling"]) if isinstance(metadata.get("sampling"), Mapping) else {},
    }
    reasons: list[str] = output["reasons"]
    if output["sampling"].get("estimated") is True:
        candidate_reason = "experimental_mask_requires_ownership_validation" if metadata.get("experimental") is True else "resampled_foreground_requires_native_validation"
        reasons.append(candidate_reason)
        if output["physical_calibration"]["validated"]:
            output["physical_calibration"].update(applied=False, status="Not applied",
                                                  reason=candidate_reason)
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
        if ((parent[0] <= 0 or parent[1] <= 0 or parent[2] >= int(frame_shape[1]) or parent[3] >= int(frame_shape[0]))
                and not _complete_native_silhouette(metadata, bounds, frame_shape)):
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
    if ((silhouette[0].any() or silhouette[-1].any() or silhouette[:, 0].any() or silhouette[:, -1].any())
            and not _complete_native_silhouette(metadata, bounds, frame_shape, pixels)):
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
    diagnostics, columns, widths, centers, transform, lower, upper = _aligned_profile(silhouette)
    diagnostics["whole_fish_max_width_px"] = round(float(widths.max()), 4)
    diagnostics["whole_fish_length_to_width_ratio"] = round(diagnostics["fish_length_px"] / float(widths.max()), 6)
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
    body_columns = np.zeros(len(columns), dtype=bool)
    body_box, body_part, body_pixels = None, None, None
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
        body_pixels = None
        if body_mask is not None:
            if (not isinstance(body_mask, np.ndarray) or body_mask.dtype != np.bool_
                    or body_mask.shape != silhouette.shape or not body_mask.any()):
                reasons.append("invalid_body_segmentation")
            else:
                body_pixels = body_mask.astype(np.uint8)
                body_owner = body_metadata.get("parent_track_id")
                if (expected_parent_id is not None and body_owner is not None
                        and str(expected_parent_id) != str(body_owner)):
                    reasons.append("body_mask_parent_mismatch")
                if (body_metadata.get("validated") is not True
                        or not _review_provenance(body_metadata.get("validation_provenance"))):
                    reasons.append("body_pixel_support_unvalidated")
                output["body_region_source"] = "reviewed_body_pixel_support"
        elif body_polygon is not None:
            try:
                polygon = np.asarray(body_polygon, dtype=np.float64)
                if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or not np.isfinite(polygon).all():
                    raise ValueError("Invalid Body polygon.")
                if (polygon.min() < -1 or polygon[:, 0].max() > binary.shape[1]
                        or polygon[:, 1].max() > binary.shape[0]):
                    raise ValueError("Body polygon outside crop.")
                body_pixels = np.zeros_like(silhouette)
                cv2.fillPoly(body_pixels, [np.rint(polygon).astype(np.int32)], 1)
                output["body_region_source"] = "associated_body_segmentation"
            except (TypeError, ValueError, cv2.error):
                reasons.append("invalid_body_segmentation")
        if body_pixels is not None:
            area = int(body_pixels.sum())
            retained_body = body_pixels & silhouette
            if area < settings.minimum_mask_pixels or float(retained_body.sum()) / max(1, area) < settings.minimum_part_inside_fraction:
                reasons.append("body_segmentation_not_associated_with_fish")
            components, _, body_stats, _ = cv2.connectedComponentsWithStats(retained_body, 8)
            if components > 2:
                areas = sorted((int(a) for a in body_stats[1:, cv2.CC_STAT_AREA]), reverse=True)
                if sum(areas[1:]) / max(1, sum(areas)) > settings.maximum_secondary_component_fraction:
                    reasons.append("fragmented_body_pixel_support")
            aligned_body = cv2.warpAffine(retained_body, transform,
                                         tuple(reversed(diagnostics["aligned_mask_shape"])), flags=cv2.INTER_NEAREST)
            available = aligned_body[:, columns].any(axis=0)
            lower = np.argmax(aligned_body[:, columns] != 0, axis=0)
            upper = aligned_body.shape[0] - 1 - np.argmax(aligned_body[::-1, columns] != 0, axis=0)
            widths = np.where(available, upper - lower + 1.0, 0.0)
            body_columns &= available
        if int(body_columns.sum()) < settings.minimum_body_profile_pixels:
            reasons.append("insufficient_associated_body_profile")
        else:
            body_width = float(widths[body_columns].max())
            diagnostics["max_body_width_px"] = round(body_width, 4)
            diagnostics["relative_width_ratio"] = round(body_width / diagnostics["fish_length_px"], 6)
            indices = np.flatnonzero(body_columns)
            middle = indices[len(indices) // 4:len(indices) - len(indices) // 4]
            representative = float(np.median(widths[middle]))
            body_length = float(np.linalg.norm(np.diff(centers[indices], axis=0), axis=1).sum() + 1.)
            profile_mean = float(np.mean(widths[indices]))
            diagnostics.update(representative_body_width_px=round(representative, 4),
                               representative_body_width_method="median_middle_50_percent_of_body_sections",
                               body_profile_length_px=round(body_length, 4),
                               body_width_to_length_ratio=round(body_width / body_length, 6),
                               body_width_profile_cv=round(float(np.std(widths[indices])) / max(profile_mean, 1.), 6))
            if body_width < settings.minimum_transverse_pixels:
                reasons.append("insufficient_body_width_resolution")
            if not 0 < diagnostics["relative_width_ratio"] < 1:
                reasons.append("implausible_silhouette_dimensions")
    output["reasons"] = list(dict.fromkeys(reasons))
    output["candidate_visualization"] = _geometry_visualization(
        bounds=bounds, frame_shape=frame_shape, metadata=metadata, reasons=output["reasons"],
        centers=centers, columns=columns, widths=widths, transform=transform, lower=lower, upper=upper,
        body_columns=body_columns, diagnostics=diagnostics, contours=contours,
        body_box=body_box, body_part=body_part, body_pixels=body_pixels,
    )
    if output["reasons"]:
        if any(reason in output["reasons"] for reason in ("resampled_foreground_requires_native_validation", "experimental_mask_requires_ownership_validation")):
            output["reliability"] = "Estimated pixel geometry; native boundary not validated"
        return output
    output.update(status="measured", reliability="Reliable pixel geometry")
    for name in ("fish_length_px", "max_body_width_px", "relative_width_ratio", "orientation_degrees",
                 "representative_body_width_px", "whole_fish_max_width_px", "whole_fish_length_to_width_ratio",
                 "body_profile_length_px", "body_width_to_length_ratio", "body_width_profile_cv"):
        output[name] = diagnostics[name]
    output["representative_body_width_method"] = diagnostics["representative_body_width_method"]
    reviewed = (metadata.get("measurement_validated") is True and metadata.get("ownership_validated") is True
                and _review_provenance(metadata.get("validation_provenance")) and body_mask is not None
                and body_metadata.get("validated") is True
                and body_metadata.get("body_region_validated") is True
                and _review_provenance(body_metadata.get("validation_provenance")))
    if reviewed:
        output.update(measurement_validated=True, ownership_validated=True, body_region_validated=True,
                      measurement_validation_status="Reviewed native silhouette and Body pixel support",
                      validation_provenance={"whole_fish": metadata["validation_provenance"],
                                             "body": body_metadata["validation_provenance"]})
    # Accepted geometry retains the legacy overlay field. Estimated candidate
    # coordinates are separate and never change measured fields or grading.
    output["visualization"] = {
        **output["candidate_visualization"], "measured": True,
        "status": "validated" if reviewed else "estimated", "measurement_validated": reviewed,
        "body_width_status": "validated" if reviewed else "estimated",
    }
    if output["physical_calibration"]["validated"]:
        output["fish_length_cm"] = round(output["fish_length_px"] / calibration.pixels_per_cm, 6)
        output["max_body_width_cm"] = round(output["max_body_width_px"] / calibration.pixels_per_cm, 6)
        output["physical_calibration"].update(applied=True, status="Applied")
    return output
