"""Independent torso geometry when Model 2 has no accepted Body region.

This evidence belongs only to the head-integrity pathway. It never creates a
PartDetection, fills Model 2 Body pixels, or supplies normal quality grading.
Native-mask ownership, completeness and clipping remain caller requirements.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

import cv2
import numpy as np

from src.inference.anatomical_measurements import _binary, _region_pixels, _selected, measure_mask_anatomy
from src.inference.fish_geometry import FishGeometryConfig, _aligned_profile
from src.inference.head_silhouette import analyze_silhouette_ends, load_head_silhouette_config


def _longest_run(values):
    padded = np.pad(values.astype(np.int8), 1)
    changes = np.diff(padded)
    starts, stops = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    if not len(starts):
        return None
    index = int(np.argmax(stops - starts))
    return int(starts[index]), int(stops[index])


def measure_silhouette_torso_support(mask, measurements=None, *, parts=(), config=None, head_config=None):
    """Measure broad, resolved interior support opposite a confirmed head cut.

    All numerical gates reuse the existing fish-geometry and head-silhouette
    settings. Both terminal windows are excluded. A fresh profile must agree
    with the assessed anterior direction; detector absence cannot supply that
    direction. ``eligible`` is geometric support, never mask ownership approval.
    """
    settings = config or FishGeometryConfig()
    ends_settings = head_config or load_head_silhouette_config()
    result = {
        "eligible": False, "source": "silhouette_torso_geometry", "support_pixels": 0,
        "width_px": None, "span_px": None, "profile_columns": 0,
        "interior_profile_columns": 0, "broad_profile_columns": 0,
        "anterior_end": None, "terminal_exclusion_fraction": ends_settings.posterior_window_stop,
        "minimum_broad_width_ratio": ends_settings.posterior_narrow_ratio,
        "ownership_required": True, "ownership_validated": False,
        "model2_body_pixels_synthesized": False, "used_for_normal_grading": False,
        "reasons": [], "geometry_thresholds": asdict(settings),
        "definition": "Native foreground in a contiguous, broad interior cross-section run; estimated torso support, not anatomical pixel labels.",
    }

    def reason(value):
        if value not in result["reasons"]:
            result["reasons"].append(value)

    binary = _binary(mask)
    if binary is None:
        reason("segmentation_mask_unavailable")
        return result
    total = int(binary.sum())
    if total < settings.minimum_mask_pixels:
        reason("insufficient_foreground_pixels")
        return result
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    largest = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    silhouette = np.asarray(labels == largest, dtype=np.uint8)
    foreground = int(stats[largest, cv2.CC_STAT_AREA])
    secondary = 1.0 - foreground / total
    result.update(component_count=count - 1, secondary_component_fraction=round(secondary, 6))
    if secondary > settings.maximum_secondary_component_fraction:
        reason("multiple_foreground_components")
    filled = np.pad(silhouette, 1).copy()
    cv2.floodFill(filled, None, (0, 0), 1)
    holes = int(np.count_nonzero(filled == 0))
    hole_fraction = holes / max(1, foreground + holes)
    result["hole_fraction"] = round(hole_fraction, 6)
    if hole_fraction > settings.maximum_hole_fraction:
        reason("implausible_silhouette_holes")
    try:
        diagnostics, columns, widths, _, transform, lower, upper = _aligned_profile(silhouette)
    except (cv2.error, ValueError, FloatingPointError, ZeroDivisionError):
        reason("orientation_profile_failed")
        return result
    result["profile_quality"] = dict(diagnostics)
    result["profile_columns"] = len(columns)
    if len(columns) < ends_settings.minimum_profile_columns:
        reason("insufficient_terminal_profile_resolution")
    if diagnostics["principal_axis_ratio"] < settings.minimum_axis_ratio:
        reason("orientation_uncertain")
    ends = analyze_silhouette_ends(widths, lower, upper, config=ends_settings)
    if not ends or ends.get("cut_end_confirmed") is not True:
        reason("severed_anterior_end_not_confirmed")
    else:
        result["anterior_end"] = ends["cut_end_axis"]
        result["representative_width_px"] = ends["representative_body_width_px"]
        anterior = next(end for end in ends["ends"] if end["axis"] == ends["cut_end_axis"])
        if ends["cut_character"] not in {"blunt", "slanted"}:
            reason("irregular_terminal_requires_detector_body")
        # A narrow terminal extension that widens and flattens is compatible
        # with visible snout tissue. Existing cut and snout criteria can overlap;
        # without detector Body support that contradiction must abstain.
        narrow_tip = anterior["terminal_width_ratio"] <= ends_settings.posterior_narrow_ratio
        persistence = anterior.get("slope_persistence")
        snout_like = (narrow_tip and persistence is not None
                      and persistence < ends_settings.snout_max_persistence)
        result["snout_like_anterior_extension"] = snout_like
        if snout_like:
            reason("snout_like_anterior_extension")
    measured = (dict(measurements) if isinstance(measurements, Mapping)
                else measure_mask_anatomy(binary, (), config=settings, head_config=ends_settings))
    polarity = measured.get("orientation_confidence") or {}
    if (measured.get("cut_end_confirmed") is not True
            or measured.get("cut_end_axis") != result["anterior_end"]
            or measured.get("anatomical_orientation_reliable") is not True
            or not isinstance(polarity, Mapping) or polarity.get("polarity_reliable") is not True):
        reason("anterior_polarity_not_agreed")
    if any(item in (measured.get("reasons") or []) for item in (
        "tail_cut_polarity_conflict", "tail_body_polarity_uncertain", "tail_reaches_anterior_tip",
        "multiple_tail_associations", "multiple_head_associations", "multiple_body_associations",
    )):
        reason("anatomical_landmark_conflict")
    if measured.get("head_pixels", 0):
        reason("visible_head_support_present")
    if not ends:
        return result
    fraction = (columns - columns[0]) / max(1, int(columns[-1] - columns[0]))
    trim = ends_settings.posterior_window_stop
    interior = (fraction >= trim) & (fraction <= 1.0 - trim)
    result["interior_profile_columns"] = int(interior.sum())
    if int(interior.sum()) >= settings.minimum_body_profile_pixels:
        # A slanted severed face displaces the terminal centerline. Apply the
        # existing straightness checks to torso interior, not the cut surface.
        inner_columns = columns[interior]
        if np.any(np.diff(inner_columns) != 1):
            reason("longitudinal_profile_gaps")
        inner_centers = ((lower + upper) / 2.0)[interior]
        normalized = (inner_columns - inner_columns[0]) / max(1, int(inner_columns[-1] - inner_columns[0])) * 2.0 - 1.0
        fitted = np.polynomial.polynomial.polyval(normalized, np.polynomial.polynomial.polyfit(
            normalized, inner_centers, 3, w=np.sqrt(widths[interior])))
        inner_length = float(np.hypot(np.diff(inner_columns), np.diff(fitted)).sum() + 1)
        chord = float(np.hypot(inner_columns[-1] - inner_columns[0], fitted[-1] - fitted[0]) + 1)
        straight = np.interp(inner_columns, (inner_columns[0], inner_columns[-1]), (fitted[0], fitted[-1]))
        scale = max(1.0, float(widths[interior].max()))
        interior_quality = {
            "centerline_tortuosity": inner_length / chord,
            "centerline_deviation_width_ratio": float(np.max(np.abs(fitted - straight))) / scale,
            "profile_residual_width_ratio": float(np.sqrt(np.mean((inner_centers - fitted) ** 2))) / scale,
        }
        result["interior_centerline_quality"] = {key: round(value, 6) for key, value in interior_quality.items()}
        for name, limit in (
            ("centerline_tortuosity", settings.maximum_centerline_tortuosity),
            ("centerline_deviation_width_ratio", settings.maximum_centerline_deviation_width_ratio),
            ("profile_residual_width_ratio", settings.maximum_profile_residual_width_ratio),
        ):
            if interior_quality[name] > limit:
                reason(f"interior_{name}_exceeds_limit")
    broad_width = max(float(settings.minimum_transverse_pixels),
                      ends_settings.posterior_narrow_ratio * ends["representative_body_width_px"])
    broad = interior & (widths >= broad_width)
    result["broad_profile_columns"] = int(broad.sum())
    result["minimum_broad_width_px"] = round(broad_width, 4)
    run = _longest_run(broad)
    if run is None or run[1] - run[0] < settings.minimum_body_profile_pixels:
        reason("insufficient_contiguous_broad_torso_sections")
        return result
    start, stop = run
    chosen = columns[start:stop]
    result["contiguous_broad_profile_columns"] = stop - start
    result["width_px"] = round(float(np.median(widths[start:stop])), 4)
    result["span_px"] = float(chosen[-1] - chosen[0] + 1)
    result["support_length_fraction"] = [round(float(fraction[start]), 6), round(float(fraction[stop - 1]), 6)]
    ys, xs = np.nonzero(silhouette)
    projected = xs * transform[0, 0] + ys * transform[0, 1] + transform[0, 2]
    support = (projected >= chosen[0] - .5) & (projected < chosen[-1] + .5)
    result["support_pixels"] = int(support.sum())
    if result["support_pixels"] < settings.minimum_mask_pixels:
        reason("insufficient_interior_torso_pixels")
    tails = _selected(parts, "Tail", settings.minimum_part_confidence)
    tail_check = {"accepted_tail_count": len(tails), "status": "not_detected",
                  "source": "accepted_model2_tail_vs_geometric_torso",
                  "minimum_separation_length_fraction": .18,
                  "anterior_tip_window_px": 3.0}
    result["tail_polarity_check"] = tail_check
    if len(tails) > 1:
        reason("multiple_tail_associations")
        tail_check["status"] = "conflict"
    elif tails:
        tail_pixels = _region_pixels(tails[0], silhouette.shape, silhouette)
        if tail_pixels is None or not tail_pixels.any():
            reason("tail_not_on_silhouette")
            tail_check["status"] = "conflict"
        else:
            tail_ys, tail_xs = np.nonzero(tail_pixels)
            tail_projection = (tail_xs * transform[0, 0] + tail_ys * transform[0, 1] + transform[0, 2])
            separation = float(tail_projection.mean() - projected[support].mean())
            tail_check.update(tail_support_pixels=int(tail_pixels.sum()),
                              tail_torso_separation_px=round(separation, 4))
            length = float(diagnostics["fish_length_px"])
            if abs(separation) < .18 * length:
                reason("tail_body_polarity_uncertain")
            expected_sign = 1.0 if result["anterior_end"] == "minimum_projection" else -1.0
            if separation * expected_sign <= 0:
                reason("tail_cut_polarity_conflict")
            near_anterior = (tail_projection <= float(projected.min()) + 3.0
                             if expected_sign > 0 else tail_projection >= float(projected.max()) - 3.0)
            if np.any(near_anterior):
                reason("tail_reaches_anterior_tip")
            tail_check["status"] = ("conflict" if any(item in result["reasons"] for item in (
                "tail_body_polarity_uncertain", "tail_cut_polarity_conflict", "tail_reaches_anterior_tip")) else "confirmed")
    # The transformed sections must contain solid foreground. A connected
    # bridge between two fish must not turn their separated rows into width.
    aligned = cv2.warpAffine(silhouette, transform, tuple(reversed(diagnostics["aligned_mask_shape"])),
                             flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    selected_counts = np.count_nonzero(aligned[:, chosen], axis=0)
    section_gap_fraction = float(np.maximum(0, widths[start:stop] - selected_counts).sum()) / max(1, float(widths[start:stop].sum()))
    result["interior_cross_section_gap_fraction"] = round(section_gap_fraction, 6)
    if section_gap_fraction > settings.maximum_hole_fraction:
        reason("gapped_interior_cross_sections")
    result["eligible"] = not result["reasons"]
    return result
