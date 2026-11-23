"""Whole-owned-silhouette diagnostics. No calibration, model, or grading changes.

Candidate types are engineering hypotheses, never expert confirmations. Pixel
length/area are image measurements, not physical damage severity. All filters
use owned fish pixels; ambiguous pixels never enter brightness or crack masks.
"""
from __future__ import annotations

import cv2
import numpy as np

from src.features.damage import _rgb_and_mask, _support_contours


def pixel_runs(mask):
    """Lossless [row, start column, length] encoding, including one-pixel lines."""
    rows, starts = np.where(np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1) == 1)
    ends = np.where(np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1) == -1)[1]
    return np.column_stack((rows, starts, ends - starts)).astype(int).tolist()


def measure_brightness(image_rgb, owned_mask, *, metadata=None):
    image, owned = _rgb_and_mask(image_rgb, owned_mask)
    metadata = dict(metadata or {})
    count = int(owned.sum())
    complete_count = metadata.get("complete_mask_pixel_count", count)
    result = {
        "status": "measured" if count else "unavailable", "method": "owned_whole_fish_hsv_v_v1",
        "units": "percent_of_255", "brightness_pixel_count": count,
        "brightness_mask_coverage": count / complete_count if complete_count else None,
        "mean_brightness": None, "median_brightness": None, "brightness_std": None,
        "brightness_percentiles": {}, "distribution": {"bin_edges": list(range(0, 101, 5)), "counts": []},
        "calibrated_measurements": None, "thresholds": None, "brightness_level": None,
        "used_for_grading": False, "measurement_reliability": "unavailable",
        "reason": metadata.get("reason") or "No usable owned whole-fish mask.",
        "mask_source": metadata.get("source"), "mask_metadata": metadata,
        "interpretation": "HSV V is image brightness; yellowing and browning are separate color measurements. No validated low/moderate/high or grading thresholds are installed.",
    }
    if not count:
        result["raw_measurements"] = {key: result[key] for key in
            ("mean_brightness", "median_brightness", "brightness_std", "brightness_percentiles", "brightness_pixel_count", "brightness_mask_coverage")}
        return result
    # V=max(R,G,B); keep the original uint8 scale before converting to percent.
    values = image.max(axis=2)[owned].astype(np.float64) * (100. / 255.)
    result.update(mean_brightness=float(values.mean()), median_brightness=float(np.median(values)),
                  brightness_std=float(values.std()),
                  brightness_percentiles={f"p{p}": float(np.percentile(values, p)) for p in (5, 25, 50, 75, 95)},
                  distribution={"bin_edges": list(range(0, 101, 5)), "counts": np.histogram(values, bins=np.arange(0, 101, 5))[0].astype(int).tolist()},
                  measurement_reliability="reviewed_mask" if metadata.get("ownership_validated") is True else "estimated_mask",
                  reason="All uniquely owned pixels of the complete visible silhouette, including tips; no Body ROI or brightness-based pixel exclusion.")
    if metadata.get("ownership_ambiguous") or count != complete_count:
        result["measurement_reliability"] = "limited_ownership"
        result["reason"] += " Shared pixels are excluded; coverage reports the retained fraction of the complete mask."
    if metadata.get("clipped"):
        result["measurement_reliability"] = "partial_visible_fish"
        result["reason"] += " Fish touches the frame edge; only its visible surface is measured."
    result["raw_measurements"] = {key: result[key] for key in
        ("mean_brightness", "median_brightness", "brightness_std", "brightness_percentiles", "brightness_pixel_count", "brightness_mask_coverage")}
    return result


def _thin(mask):
    """Zhang-Suen thinning with a finite bound; retains connected branches."""
    pixels = np.pad(mask.astype(np.uint8), 1)
    for _ in range(min(256, max(mask.shape))):
        changed = False
        for phase in (0, 1):
            p = [pixels[:-2, 1:-1], pixels[:-2, 2:], pixels[1:-1, 2:], pixels[2:, 2:],
                 pixels[2:, 1:-1], pixels[2:, :-2], pixels[1:-1, :-2], pixels[:-2, :-2]]
            neighbors = sum(p)
            transitions = sum((p[i] == 0) & (p[(i + 1) % 8] == 1) for i in range(8))
            first = p[0] * p[2] * (p[4] if phase == 0 else p[6])
            second = (p[2] if phase == 0 else p[0]) * p[4] * p[6]
            remove = (pixels[1:-1, 1:-1] == 1) & (neighbors >= 2) & (neighbors <= 6) & (transitions == 1) & (first == 0) & (second == 0)
            if remove.any():
                pixels[1:-1, 1:-1][remove] = 0
                changed = True
        if not changed:
            return pixels[1:-1, 1:-1].astype(bool), True
    return pixels[1:-1, 1:-1].astype(bool), False


def _geometry(component):
    skeleton, converged = _thin(component)
    padded = np.pad(component.astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    width = np.maximum(1., 2 * distance[skeleton] - 1)
    orthogonal = np.count_nonzero(skeleton[:, :-1] & skeleton[:, 1:]) + np.count_nonzero(skeleton[:-1] & skeleton[1:])
    # Avoid diagonal shortcuts where an orthogonal skeleton path already exists.
    diagonals = np.count_nonzero(skeleton[:-1, :-1] & skeleton[1:, 1:] & ~skeleton[:-1, 1:] & ~skeleton[1:, :-1])
    diagonals += np.count_nonzero(skeleton[:-1, 1:] & skeleton[1:, :-1] & ~skeleton[:-1, :-1] & ~skeleton[1:, 1:])
    length = max(1., float(orthogonal + np.sqrt(2) * diagonals))
    counts = cv2.filter2D(skeleton.astype(np.uint8), cv2.CV_16U, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT) - skeleton
    branch_components = cv2.connectedComponents((skeleton & (counts > 2)).astype(np.uint8), 8)[0] - 1
    _, _, stats, _ = cv2.connectedComponentsWithStats(skeleton.astype(np.uint8), 8)
    continuity = float(stats[1:, cv2.CC_STAT_AREA].max() / max(1, skeleton.sum())) if len(stats) > 1 else 0.
    return skeleton, {
        "skeleton_length_px": round(length, 3) if converged else None,
        "skeleton_status": "measured_pixel_graph" if converged else "iteration_limit",
        "skeleton_method": "zhang_suen_graph_edges_without_diagonal_shortcuts",
        "median_width_px": round(float(np.median(width)), 3) if width.size else None,
        "maximum_width_px": round(float(width.max()), 3) if width.size else None,
        "branch_pixel_count": int(np.count_nonzero(skeleton & (counts > 2))),
        "branch_point_count": int(branch_components), "endpoint_count": int(np.count_nonzero(skeleton & (counts == 1))),
        "continuity": round(continuity, 4),
    }


def _two_sided(gray, reference_mask, skeleton, offset, *, return_supported=False):
    ys, xs = np.where(skeleton)
    step = 1 if return_supported else max(1, int(np.ceil(len(xs) / 1024)))
    xs, ys = xs[::step], ys[::step]
    if np.ndim(offset):
        offset = np.asarray(offset)[::step]
    center = gray[ys, xs].astype(float)
    best = np.full(len(xs), -255.)
    for dx, dy in ((1., 0.), (0., 1.), (.707, .707), (.707, -.707)):
        ax, ay = np.rint(xs + dx * offset).astype(int), np.rint(ys + dy * offset).astype(int)
        bx, by = np.rint(xs - dx * offset).astype(int), np.rint(ys - dy * offset).astype(int)
        valid = (ax >= 0) & (bx >= 0) & (ay >= 0) & (by >= 0) & (ax < gray.shape[1]) & (bx < gray.shape[1]) & (ay < gray.shape[0]) & (by < gray.shape[0])
        ids = np.flatnonzero(valid)
        ids = ids[reference_mask[ay[ids], ax[ids]] & reference_mask[by[ids], bx[ids]]]
        best[ids] = np.maximum(best[ids], np.minimum(gray[ay[ids], ax[ids]], gray[by[ids], bx[ids]]).astype(float) - center[ids])
    valid = best > -255
    values = (float(np.mean(best >= 10)) if len(best) else 0., float(np.median(best[valid])) if valid.any() else 0.)
    if return_supported:
        supported = np.zeros_like(skeleton)
        supported[ys, xs] = best >= 10
        return (*values, supported)
    return values


def analyze_owned_surface(image_rgb, owned_mask, *, metadata=None, ambiguous_mask=None):
    image, owned = _rgb_and_mask(image_rgb, owned_mask)
    metadata = dict(metadata or {})
    ambiguous = np.zeros_like(owned) if ambiguous_mask is None else np.asarray(ambiguous_mask, dtype=bool)
    if ambiguous.shape != owned.shape or (ambiguous & owned).any():
        raise ValueError("Ambiguous pixels must be aligned and disjoint from owned pixels.")
    reference = owned | ambiguous
    result = {
        "status": "not_detected" if owned.any() else "unavailable", "label": "No reliable evidence",
        "evidence_state": "No reliable evidence", "method": "whole_owned_multiscale_surface_v1",
        "analysis_scope": "Complete visible whole-fish silhouette; no Body ROI or interior erosion.",
        "foreground_pixel_count": int(owned.sum()), "analysis_interior_pixel_count": int(owned.sum()),
        "boundary_exclusion_px": 0, "mask_source": metadata.get("source"), "mask_metadata": metadata,
        "mask_validated_for_cracks": False, "validation_status": "unvalidated", "used_for_grading": False,
        "grade_adjustment": 0., "confidence": None, "confidence_kind": "heuristic_not_probability",
        "confidence_calibrated": False, "severity": "unassessed", "estimated_length_px": None,
        "length_method": "native_skeleton_graph_extent_not_full_crack_length",
        "locations": [], "candidates": [], "overlay_mask": np.zeros(owned.shape, np.uint8),
        "coordinate_space": "crop_local_native_pixels", "raw_measurements": {}, "calibrated_measurements": None,
        "confirmed_count": 0, "suspected_count": 0, "rejected_count": 0,
        "total_crack_length_px": None, "crack_area_px": None, "crack_density": None,
        "detection_reliability": "unvalidated_detector" if owned.any() else "unavailable",
        "reason": "No retained crack-like evidence. This does not establish absence of cracks.",
        "threshold_interpretation": "Engineering candidate filters; no expert calibration, probability, severity, or automatic grade claim.",
    }
    if not reference.any():
        result["reason"] = metadata.get("reason") or "No usable owned whole-fish mask."
        return result
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    # Normalized masked convolution makes results invariant to ALL outside pixels,
    # including adjacent fish, black padding and shadows outside the silhouette.
    response = np.zeros(gray.shape, np.float32)
    extension = np.zeros_like(response)
    sampling_region = owned if owned.any() else ambiguous
    # Ambiguous neighborhoods never provide contrast references for owned ones.
    for region in (owned, ambiguous):
        if not region.any():
            continue
        weights = region.astype(np.float32)
        for sigma in (2., 5., 11.):
            denominator = cv2.GaussianBlur(weights, (0, 0), sigma)
            baseline = cv2.GaussianBlur(gray.astype(np.float32) * weights, (0, 0), sigma) / np.maximum(denominator, 1e-6)
            response[region] = np.maximum(response[region], (baseline - gray)[region])
            if sigma == 2. and region is sampling_region:
                extension = np.where(region, gray, baseline)
    sampling = owned if owned.any() else reference
    center = float(np.median(response[sampling]))
    noise = float(np.median(np.abs(response[sampling] - center))) * 1.4826
    threshold = max(10., center + 3 * noise)
    local_pixels = (response >= threshold) & reference
    median_gray = float(np.median(gray[sampling]))
    broad_pixels = (gray.astype(float) < median_gray - max(20., 3 * noise)) & reference
    result["engineering_thresholds"] = {"local_contrast_255": threshold, "two_sided_contrast_255": 10., "noise_mad_255": noise}
    candidates, supports, directions = [], [], []
    diagonal = float(np.hypot(*cv2.boundingRect(reference.astype(np.uint8))[2:]))
    minimum_length = max(8., diagonal * .025)
    maximum_width = max(8., min(owned.shape) * .08)
    gx, gy = cv2.Sobel(extension, cv2.CV_32F, 1, 0), cv2.Sobel(extension, cv2.CV_32F, 0, 1)
    gradient = cv2.magnitude(gx, gy)
    omitted = 0
    for stream, pixels in (("local", local_pixels), ("broad", broad_pixels)):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(pixels.astype(np.uint8), 8)
        for label in sorted(range(1, count), key=lambda i: int(stats[i, cv2.CC_STAT_AREA]), reverse=True):
            x, y, w, h, area = map(int, stats[label])
            if area < 3:
                continue
            if len(candidates) >= 256:
                omitted += 1
                continue
            component = labels[y:y+h, x:x+w] == label
            if stream == "broad" and any(area <= c.get("support_component_area_px", c["area_px"]) * 1.8 and
                x <= c["x"] and y <= c["y"] and x+w >= c["x"]+c["width"] and y+h >= c["y"]+c["height"] for c in candidates):
                continue
            ys, xs = np.where(component)
            points = np.column_stack((xs + x, ys + y))
            covariance = np.cov(points, rowvar=False)
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            aspect = float(np.sqrt(max(eigenvalues[-1], 0.) / max(eigenvalues[0], .25)))
            skeleton, geometry = _geometry(component)
            sample = np.zeros_like(owned)
            sample[y:y+h, x:x+w] = skeleton
            width = geometry["median_width_px"] or float(min(w, h))
            ambiguous_count = int(np.count_nonzero(component & ambiguous[y:y+h, x:x+w]))
            component_reference = reference if ambiguous_count else owned
            distances = cv2.distanceTransform(np.pad(component.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1,1:-1]
            offsets = np.maximum(3., distances[skeleton]*1.5+1.25)
            support, contrast, supported_centers = _two_sided(gray, component_reference, sample, offsets, return_supported=True)
            length = geometry["skeleton_length_px"] or 0.
            local_saturation = float(np.median(hsv[y:y+h, x:x+w, 1][component])) / 255.
            padded_component = np.pad(component.astype(np.uint8), 3)
            ring = cv2.dilate(padded_component, np.ones((7, 7), np.uint8)).astype(bool)
            ring[3:3+h, 3:3+w] &= ~component
            rx, ry = max(0, x-3), max(0, y-3)
            rr, rb = min(gray.shape[1], x+w+3), min(gray.shape[0], y+h+3)
            ring = ring[ry-(y-3):rb-(y-3), rx-(x-3):rr-(x-3)] & component_reference[ry:rb, rx:rr]
            surrounding = gray[ry:rb, rx:rr][ring]
            affected = component & owned[y:y+h, x:x+w]
            ambiguous_count = int(np.count_nonzero(component & ambiguous[y:y+h, x:x+w]))
            branching = geometry["branch_point_count"] > 0 and geometry["endpoint_count"] >= 3
            curved = geometry["endpoint_count"] >= 2 and length / max(1., width) >= 8
            line_like = length >= minimum_length and width <= maximum_width and length / max(1., width) >= 5 and (aspect >= 2.5 or branching or curved) and geometry["continuity"] >= .85
            kind, status, exclusion = "uncertain_defect", "suspected", "Insufficient geometric or surrounding-intensity evidence."
            if line_like and support >= .55:
                kind, exclusion = "crack_or_split", ""
            elif local_saturation > .28 and (width > maximum_width or aspect < 2.5):
                kind, status, exclusion = "discoloration", "rejected", "Broad chromatic patch lacks localized split geometry."
            elif support < .35 and (max(w, h) >= minimum_length or width > maximum_width):
                kind, status, exclusion = "shadow_or_lighting_artifact", "rejected", "A broad or one-sided intensity change lacks two-sided crack support."
            elif aspect < 2.5 and not branching:
                kind, status, exclusion = "dark_spot", "rejected", "Compact dark component lacks elongated or branching split geometry."
            elif length < minimum_length:
                kind, status, exclusion = "natural_fish_texture", "rejected", "Short fine structure lacks continuous split support."
            if ambiguous_count or metadata.get("ownership_ambiguous"):
                kind, status, exclusion = "uncertain_defect", "suspected", "Mask ownership is ambiguous; no fish owner or crack pixels assigned."
            component_area = int(component.sum())
            excluded_pixels = 0
            if kind == "crack_or_split":
                # A thin split can touch a broad spot. A component-level vote
                # must not paint that whole spot white. Reconstruct support
                # only around locally narrow, two-sided skeleton centers.
                centers = skeleton & supported_centers[y:y+h,x:x+w] & (2*distances-1 <= maximum_width)
                radii = np.ceil(distances).astype(np.int32)
                localized = np.zeros_like(component)
                for radius in np.unique(radii[centers]):
                    core = (centers & (radii == radius)).astype(np.uint8)
                    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*int(radius)+1,)*2)
                    localized |= cv2.dilate(core, disk).astype(bool) & component
                if localized.any():
                    excluded_pixels = int(np.count_nonzero(component & ~localized))
                    if excluded_pixels:
                        exclusion = f"{excluded_pixels} broad or unsupported pixels excluded from this split hypothesis."
                    component = localized
                    affected = component & owned[y:y+h,x:x+w]
                    skeleton, geometry = _geometry(component)
                    rows, columns = np.where(component)
                    points = np.column_stack((columns+x,rows+y))
                else:
                    kind, exclusion = "uncertain_defect", "No localized narrow support survived the per-pixel contrast and width checks."
            owner = metadata.get("parent_track_id") if not ambiguous_count and not metadata.get("ownership_ambiguous") else None
            confidence = float(np.clip(.25 + .35 * support + .15 * min(length / max(width * 12, 1), 1) + .1 * min(max(contrast, 0) / 80, 1), 0, .85))
            record = {"candidate_id": f"{metadata.get('parent_track_id', 'fish')}-C{len(candidates)+1}",
                "candidate_type": kind, "validation_status": status, "exclusion_reason": exclusion,
                "owner_fish_id": owner, "possible_owner_fish_ids": metadata.get("possible_owner_fish_ids", []),
                "confidence": round(confidence, 4), "confidence_kind": "heuristic_not_probability",
                "x": x, "y": y, "width": w, "height": h, "area_px": int(component.sum()),
                "owned_area_px": int(affected.sum()),
                "ambiguous_pixel_count": ambiguous_count, "aspect_ratio": round(aspect, 4), "elongation": round(aspect, 4),
                "support_component_area_px": component_area, "excluded_broad_or_unsupported_pixels": excluded_pixels,
                "localization_method": "two_sided_width_supported_skeleton_original_pixels",
                "estimated_length_px": geometry["skeleton_length_px"], "length_method": result["length_method"],
                "original_rgb_support_fraction": round(support, 4), "original_rgb_contrast_255": round(contrast, 3),
                "mean_intensity_255": float(gray[y:y+h, x:x+w][component].mean()),
                "surrounding_mean_intensity_255": float(surrounding.mean()) if surrounding.size else None,
                "surrounding_texture_std_255": float(surrounding.std()) if surrounding.size else None,
                "candidate_texture_std_255": float(gray[y:y+h, x:x+w][component].std()),
                "edge_strength_255": float(gradient[y:y+h, x:x+w][component].mean()),
                "median_saturation": local_saturation, "stream": stream,
                "contours": _support_contours(points),
                "pixel_runs": [[row+y, start+x, run] for row, start, run in pixel_runs(component)],
                "used_for_grading": False, "calibrated_measurements": None, **geometry}
            record["raw_measurements"] = {key: record[key] for key in
                ("area_px", "aspect_ratio", "skeleton_length_px", "median_width_px", "maximum_width_px", "continuity",
                 "original_rgb_support_fraction", "original_rgb_contrast_255", "edge_strength_255",
                 "mean_intensity_255", "surrounding_mean_intensity_255", "candidate_texture_std_255", "surrounding_texture_std_255")}
            candidates.append(record)
            supports.append((x, y, affected))
            directions.append(eigenvectors[:, -1])
    # Repeated similar parallel line structures are texture hypotheses. Retain
    # every rejected candidate and its measurements for review, rather than hide it.
    for i, candidate in enumerate(candidates):
        if candidate["candidate_type"] != "crack_or_split":
            continue
        siblings = [j for j, other in enumerate(candidates) if other["candidate_type"] == "crack_or_split"
            and abs(float(directions[i] @ directions[j])) >= .97
            and min(candidate["estimated_length_px"], other["estimated_length_px"]) / max(candidate["estimated_length_px"], other["estimated_length_px"]) >= .65]
        if len(siblings) >= 3:
            for j in siblings:
                candidates[j].update(candidate_type="natural_fish_texture", validation_status="rejected", exclusion_reason="Repeated similar parallel structure; requires review if a true split is suspected.")
    crack_mask = result["overlay_mask"]
    for candidate, (x, y, affected) in zip(candidates, supports):
        if candidate["candidate_type"] == "crack_or_split" and candidate["owner_fish_id"] is not None:
            crack_mask[y:y+affected.shape[0], x:x+affected.shape[1]][affected] = 255
        candidate["crack_density"] = (None if candidate["owner_fish_id"] is None or candidate["candidate_type"] == "uncertain_defect" else
            candidate["area_px"] / max(1, int(owned.sum())) if candidate["candidate_type"] == "crack_or_split" else 0.)
    locations = [c for c in candidates if c["candidate_type"] == "crack_or_split" and c["owner_fish_id"] is not None]
    # Measure the union once so overlapping candidate hypotheses cannot inflate
    # the fish's total length. Candidate rows retain their individual geometry.
    length = _geometry(crack_mask > 0)[1]["skeleton_length_px"] if crack_mask.any() else 0.
    result.update(candidates=candidates, locations=locations, suspected_count=sum(c["validation_status"] == "suspected" for c in candidates),
                  rejected_count=sum(c["validation_status"] == "rejected" for c in candidates),
                  total_crack_length_px=round(length, 3) if length is not None else None, crack_area_px=int(np.count_nonzero(crack_mask)),
                  crack_density=float(np.count_nonzero(crack_mask) / owned.sum()) if owned.any() else None,
                  binary_mask={"encoding": "row_runs", "shape": list(owned.shape), "runs": pixel_runs(crack_mask > 0)},
                  candidates_omitted=omitted, candidate_limit=256,
                  detection_reliability="limited_ownership" if ambiguous.any() or metadata.get("ownership_ambiguous") else "unvalidated_detector")
    result["suspected_crack_count"] = len(locations)
    result["uncertain_count"] = sum(c["candidate_type"] == "uncertain_defect" for c in candidates)
    if not owned.any():
        result["status"] = "unavailable"
        result["total_crack_length_px"] = result["crack_area_px"] = None
        result["reason"] = "No uniquely owned pixels. Unassigned candidates are visible for review; no crack pixels were attributed."
    if locations:
        result.update(status="suspected", label="Suspected Damage", evidence_state="Suspected Damage",
            confidence=max(c["confidence"] for c in locations), estimated_length_px=max(c["skeleton_length_px"] for c in locations),
            reason="Localized split-like geometry with original-image contrast; all candidates require independent review before confirmation or grading.")
    if omitted:
        result["detection_reliability"] = "candidate_limit_reached"
        result["reason"] += f" {omitted} component proposals were skipped at the {result['candidate_limit']}-candidate limit; review the original surface."
    result["raw_measurements"] = {key: result[key] for key in ("confirmed_count", "suspected_count", "rejected_count", "total_crack_length_px", "crack_area_px", "crack_density", "candidates_omitted", "candidate_limit")}
    return result
