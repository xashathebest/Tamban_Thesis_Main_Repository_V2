"""Unvalidated surface-discontinuity evidence localized on original RGB.

This feature finds review candidates, never diagnoses fractures, assesses
biological severity, validates damage, or modifies grades. No candidate does
not establish that a fish is undamaged.
"""

from __future__ import annotations

from collections.abc import Mapping

import cv2
import numpy as np

from src.preprocessing.scientific_image_utils import PreprocessingError


def _rgb_and_mask(image_rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    image, raw_mask = np.asarray(image_rgb), np.asarray(mask)
    if (
        image.ndim != 3 or image.shape[2] != 3 or raw_mask.ndim != 2
        or image.shape[:2] != raw_mask.shape or not image.size
    ):
        raise PreprocessingError("Surface damage analysis requires an aligned RGB image and mask.")
    if raw_mask.dtype.kind not in "buif" or not np.isfinite(raw_mask).all():
        raise PreprocessingError("Surface damage mask must contain finite binary foreground values.")
    if image.dtype != np.uint8:
        if image.dtype.kind != "f" or not np.isfinite(image).all() or image.min() < 0 or image.max() > 1:
            raise PreprocessingError("Surface damage RGB input must be uint8 or finite floats in [0, 1].")
        image = np.rint(image * 255.0).astype(np.uint8)
    return image, raw_mask.astype(bool)


def _withholding_reasons(metadata: Mapping[str, object], context: Mapping[str, object]) -> list[str]:
    reasons = []
    if metadata.get("validation_passed") is False or metadata.get("valid") is False or metadata.get("status") in {
        "invalid", "unavailable", "rejected",
    }:
        reasons.append("The runtime foreground mask did not pass its validation checks.")
    for flag, explanation in (
        ("overlapping", "Overlapping parent fish prevent reliable attribution of surface evidence."),
        ("ambiguous", "The parent fish or its foreground mask is ambiguous."),
        ("clipped", "The parent fish is clipped by the image boundary."),
        ("partially_visible", "The parent fish is only partially visible."),
    ):
        if context.get(flag) is True:
            reasons.append(explanation)
    return reasons


def _line_geometry(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    center = points.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(points, rowvar=False))
    direction = eigenvectors[:, -1]
    projected = (points - center) @ direction
    length = float(np.ptp(projected) + 1.0)
    elongation = float(np.sqrt(max(eigenvalues[-1], 0.0) / max(eigenvalues[0], 0.01)))
    return direction, projected, length, elongation


def analyze_surface_damage(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    *,
    mask_source: str = "feature_mask",
    mask_metadata: Mapping[str, object] | None = None,
    parent_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return bounded review candidates with input-crop pixel coordinates.

    ``mask`` must be a foreground segmentation rather than an edge/texture map.
    Known rejected masks or overlapping/clipped parents abstain. Confidence is
    an uncalibrated evidence-strength heuristic, not a probability.
    """
    image, binary = _rgb_and_mask(image_rgb, mask)
    metadata, context = dict(mask_metadata or {}), dict(parent_context or {})
    result: dict[str, object] = {
        "status": "not_detected", "label": "No reliable evidence",
        "evidence_state": "No reliable evidence", "validation_status": "unvalidated",
        "confidence": None, "confidence_kind": "heuristic_not_probability", "confidence_calibrated": False,
        "severity": "unassessed", "severity_reason": "Damage severity requires expert labels and reference measurements.",
        "estimated_length_px": None, "length_method": "straight_line_support_extent_not_full_crack_length",
        "locations": [], "coordinate_space": "crop_local_pixels", "mask_source": mask_source,
        "mask_validated_for_cracks": False, "grade_adjustment": 0.0,
        "analysis_scope": "Narrow interior dark-line evidence only; boundary tears, broad fractures, and line cause require expert review.",
        "foreground_pixel_count": int(binary.sum()), "overlay_mask": np.zeros(binary.shape, dtype=np.uint8),
    }
    if metadata:
        result["mask_metadata"] = metadata
    if context:
        result["parent_context"] = context
    reasons = _withholding_reasons(metadata, context)
    if not binary.any():
        reasons.append("The fish foreground mask is empty or unavailable.")
    if reasons:
        result.update(status="unavailable", reason=" ".join(reasons), reasons=reasons)
        return result

    # Never close/open/enlarge the supplied mask. The interior margin excludes
    # segmentation boundaries, thin fins, and background from local filtering.
    kernel_size = max(9, min(21, int(round(min(binary.shape) * 0.1)) | 1))
    margin = kernel_size // 2 + 2
    sampling = metadata.get("sampling", {})
    if isinstance(sampling, Mapping) and sampling.get("estimated") is True:
        footprint = sampling.get("boundary_sampling_footprint_native_px", [])
        if isinstance(footprint, (tuple, list)) and footprint:
            valid = [float(value) for value in footprint if isinstance(value, (int, float))
                     and not isinstance(value, bool) and np.isfinite(value) and value > 0]
            if len(valid) == len(footprint):
                margin += int(np.ceil(min(max(valid), max(binary.shape))))
        result.update(foreground_estimated=True, foreground_support_reliability="Estimated foreground support",
                      sampling_note="Boundary exclusion includes the working-grid sampling footprint; it is not a validated segmentation error bound.")
    padded = cv2.copyMakeBorder(binary.astype(np.uint8), 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    interior = distance > margin
    result.update(analysis_interior_pixel_count=int(interior.sum()), boundary_exclusion_px=margin)
    if int(interior.sum()) < 64:
        reason = "The foreground has too little interior support after excluding boundaries and thin features."
        result.update(status="unavailable", reason=reason, reasons=[reason])
        return result

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    response = cv2.morphologyEx(
        denoised, cv2.MORPH_BLACKHAT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
    )
    values = response[interior].astype(np.float32)
    median = float(np.median(values))
    noise = float(np.median(np.abs(values - median))) * 1.4826
    threshold = max(12.0, median + 3.0 * noise)
    candidates = (response >= threshold) & interior
    result["local_dark_response_threshold"] = round(threshold, 3)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), 8)
    rejection_counts = {"short_or_nonlinear": 0, "broad_feature": 0, "no_two_sided_rgb_support": 0, "repeated_parallel_texture": 0}
    minimum_length = max(12.0, float(np.hypot(*binary.shape)) * 0.05)
    accepted: list[tuple[dict[str, object], np.ndarray, np.ndarray]] = []
    for index in range(1, component_count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area < 8 or max(width, height) < minimum_length:
            rejection_counts["short_or_nonlinear"] += 1
            continue
        # Limit component work to its bounds, avoiding a full-frame comparison
        # for every small scale/noise component.
        rows, columns = np.where(labels[y:y + height, x:x + width] == index)
        points = np.column_stack((columns + x, rows + y)).astype(np.float64)
        direction, _, length, elongation = _line_geometry(points)
        if length < minimum_length or elongation < 4.0:
            rejection_counts["short_or_nonlinear"] += 1
            continue
        thickness = area / length
        if thickness > kernel_size * 0.9:
            rejection_counts["broad_feature"] += 1
            continue

        # Both sides must be brighter in ORIGINAL RGB luminance. A single
        # illumination step cannot pass merely because it produces a long edge.
        normal = np.array([-direction[1], direction[0]])
        offset = max(3, int(np.ceil(thickness)) + 2)
        side_a = np.rint(points + normal * offset).astype(np.int32)
        side_b = np.rint(points - normal * offset).astype(np.int32)
        valid = (
            (side_a[:, 0] >= 0) & (side_a[:, 0] < binary.shape[1])
            & (side_a[:, 1] >= 0) & (side_a[:, 1] < binary.shape[0])
            & (side_b[:, 0] >= 0) & (side_b[:, 0] < binary.shape[1])
            & (side_b[:, 1] >= 0) & (side_b[:, 1] < binary.shape[0])
        )
        valid_indices = np.flatnonzero(valid)
        valid[valid_indices] &= (
            binary[side_a[valid_indices, 1], side_a[valid_indices, 0]]
            & binary[side_b[valid_indices, 1], side_b[valid_indices, 0]]
        )
        indices = np.flatnonzero(valid)
        if len(indices) < 8:
            rejection_counts["no_two_sided_rgb_support"] += 1
            continue
        centers = points[indices].astype(np.int32)
        a, b = side_a[indices], side_b[indices]
        center_values = gray[centers[:, 1], centers[:, 0]].astype(np.float32)
        contrast = np.minimum(
            gray[a[:, 1], a[:, 0]].astype(np.float32) - center_values,
            gray[b[:, 1], b[:, 0]].astype(np.float32) - center_values,
        )
        supported = contrast >= 12.0
        support_fraction = float(supported.sum() / area)
        if support_fraction < 0.6 or int(supported.sum()) < 8:
            rejection_counts["no_two_sided_rgb_support"] += 1
            continue
        support_points = points[indices[supported]]
        direction, projected, length, elongation = _line_geometry(support_points)
        if length < minimum_length or elongation < 4.0:
            rejection_counts["short_or_nonlinear"] += 1
            continue
        original_contrast = float(np.median(contrast[supported]))
        confidence = round(min(0.89, 0.55 + 0.2 * support_fraction + 0.1 * min(1.0, original_contrast / 80.0) + 0.05 * min(1.0, (elongation - 4.0) / 8.0)), 3)
        left, top = support_points.min(axis=0).astype(int)
        right, bottom = support_points.max(axis=0).astype(int)
        endpoints = support_points[[int(np.argmin(projected)), int(np.argmax(projected))]].astype(int).tolist()
        location: dict[str, object] = {
            "x": int(left), "y": int(top), "width": int(right - left + 1), "height": int(bottom - top + 1),
            "endpoints": endpoints, "estimated_length_px": round(length, 2),
            "length_method": "straight_line_support_extent_not_full_crack_length", "area_px": int(len(support_points)),
            "confidence": confidence, "confidence_kind": "heuristic_not_probability",
            "original_rgb_contrast_255": round(original_contrast, 2), "original_rgb_support_fraction": round(support_fraction, 3),
            "elongation": round(elongation, 3), "damage_type": "unclassified_surface_discontinuity",
        }
        accepted.append((location, support_points.astype(np.int32), direction))

    # Repeated aligned bands are common surface/anatomical texture. Two lines
    # can remain review candidates; three similar aligned lines are withheld.
    # This conservative filter does not establish anatomical identity.
    retained = []
    for location, points, direction in accepted:
        siblings = sum(
            abs(float(direction @ other_direction)) >= 0.97
            and min(float(location["estimated_length_px"]), float(other["estimated_length_px"]))
            / max(float(location["estimated_length_px"]), float(other["estimated_length_px"])) >= 0.65
            for other, _, other_direction in accepted
        )
        if siblings >= 3:
            rejection_counts["repeated_parallel_texture"] += 1
        else:
            retained.append((location, points))
    retained.sort(key=lambda item: (float(item[0]["confidence"]), float(item[0]["estimated_length_px"])), reverse=True)
    result["rejection_counts"] = rejection_counts
    result["candidate_count_before_limit"] = len(retained)
    retained = retained[:12]
    locations = [location for location, _ in retained]
    if locations:
        overlay = result["overlay_mask"]
        for _, points in retained:
            overlay[points[:, 1], points[:, 0]] = 255
        result.update(
            status="suspected", label="Suspected Damage", evidence_state="Suspected Damage",
            confidence=max(float(item["confidence"]) for item in locations),
            estimated_length_px=max(float(item["estimated_length_px"]) for item in locations), locations=locations,
            reason="Localized dark-line evidence has support in the original RGB image. Its cause and severity are unvalidated; expert review is required.",
        )
    else:
        result["reason"] = "No reliable interior crack-like evidence survived the geometry, boundary, texture, and original-RGB support checks. This does not establish absence of damage."
    return result
