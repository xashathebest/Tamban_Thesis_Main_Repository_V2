"""One native whole-fish surface calculation shared by processing and previews.

Pixel exclusivity is an engineering constraint, not independent confirmation
that MobileSAM segmented the right anatomy. No evidence here changes a grade.
"""
from __future__ import annotations

import base64
from copy import deepcopy

import cv2
import numpy as np

from src.features.fish_surface import analyze_owned_surface, measure_brightness, pixel_runs


def measure_owned_surface(provider, parent_id):
    """Use the full native mask extent, including pixels beyond the prompt box.

    Shared pixels and pixels potentially owned by an unsegmented neighbor are
    explicitly unassigned. No distance-to-box-center ownership is invented.
    """
    current = provider.is_current()
    cache = getattr(provider, "_surface_results", {})
    if current and parent_id in cache:
        return deepcopy(cache[parent_id])
    frame = provider.frame
    candidate = provider.candidates.get(parent_id, {})
    report = provider.ownership.get(parent_id, {})
    native = candidate.get("mask")
    reviewed = provider.reviewed_instances.get(parent_id)
    reviewed_ok = bool(reviewed and provider.reviewed_ownership.get(parent_id, {}).get("engineering_checks_passed"))
    if reviewed_ok:
        native = reviewed["whole_mask"]
    valid = (current and isinstance(native, np.ndarray) and native.shape == frame.shape[:2]
             and native.dtype.kind in "buif" and np.isfinite(native).all()
             and np.isin(native, (0, 1, 255)).all() and native.any())
    reasons = report.get("reasons", [])
    fatal = {"candidate_parent_identity_mismatch", "candidate_prompt_box_mismatch",
             "candidate_native_coordinates_mismatch", "candidate_frame_identity_mismatch",
             "fragmented_or_merged_foreground_components", "implausible_silhouette_holes",
             "implausible_or_orientation_uncertain_silhouette", "insufficient_foreground_pixels",
             "insufficient_visible_parent_support", "foreground_extends_beyond_intended_parent"}
    if not reviewed_ok and (fatal.intersection(reasons) or report.get("status") == "unavailable"):
        valid = False
    if valid:
        native = native.astype(bool)
        x, y, w, h = cv2.boundingRect(native.astype(np.uint8))
        # Reject rectangle/full-frame outputs without pretending they are fish.
        valid = native.sum() < native.size and native.sum() / (w * h) < .995
    if not valid:
        native = np.zeros(frame.shape[:2], bool)
        x, y, w, h = 0, 0, 1, 1
    bounds = [x, y, x + w, y + h]
    complete = native[y:y+h, x:x+w]
    ambiguous = np.zeros_like(complete)
    possible = []
    if valid:
        for neighbor in provider.parents:
            if neighbor.track_id == parent_id:
                continue
            other = provider.candidates.get(neighbor.track_id, {}).get("mask")
            other_review = provider.reviewed_instances.get(neighbor.track_id)
            if other_review and provider.reviewed_ownership.get(neighbor.track_id, {}).get("engineering_checks_passed"):
                other = other_review["whole_mask"]
            if (isinstance(other, np.ndarray) and other.shape == native.shape
                    and other.dtype.kind in "bui" and np.isin(other, (0, 1, 255)).all() and other.any()):
                shared = complete & other[y:y+h, x:x+w].astype(bool)
            else:
                # A failed neighboring mask supplies no reliable negative pixels.
                left, top, right, bottom = neighbor.bbox
                shared = np.zeros_like(complete)
                left, top = max(x, int(np.floor(left))), max(y, int(np.floor(top)))
                right, bottom = min(x+w, int(np.ceil(right))), min(y+h, int(np.ceil(bottom)))
                if right > left and bottom > top:
                    shared[top-y:bottom-y, left-x:right-x] = complete[top-y:bottom-y, left-x:right-x]
            if shared.any():
                ambiguous |= shared
                possible.append(neighbor.track_id)
        # A mask reaching a neighbor's exclusive detection region remains
        # uncertain even if that neighbor's SAM proposal failed to claim it.
        if "candidate_contains_neighbor_anatomical_evidence" in reasons or "foreground_in_neighbor_exclusive_region" in reasons:
            ambiguous |= complete
            possible = sorted(set(possible).union(report.get("conflicting_parent_ids", [])) - {parent_id})
    owned = complete & ~ambiguous
    metadata = {
        "source": "reviewed_native_instance_mask" if reviewed_ok else "mobilesam_whole_fish_owned_mask",
        "parent_track_id": parent_id, "frame_id": provider.frame_id, "frame_key": provider.frame_key,
        "complete_mask_pixel_count": int(complete.sum()), "owned_mask_pixel_count": int(owned.sum()),
        "ambiguous_pixel_count": int(ambiguous.sum()), "ownership_validated": reviewed_ok,
        "possible_owner_fish_ids": [parent_id, *possible], "ownership_checks": report,
        "clipped": bool(valid and (native[0].any() or native[-1].any() or native[:, 0].any() or native[:, -1].any())),
        "reason": ("Complete native silhouette; shared pixels withheld." if valid else
                   "Whole-fish mask unavailable, stale, or failed identity/silhouette checks: " + "; ".join(reasons)),
    }
    if valid and not owned.any():
        metadata["reason"] = "Whole-fish ownership is ambiguous; all pixels were withheld. " + "; ".join(reasons)
    rgb = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)
    brightness = measure_brightness(rgb, owned, metadata=metadata)
    try:
        damage = analyze_owned_surface(rgb, owned, metadata=metadata, ambiguous_mask=ambiguous)
    except Exception as error:
        # Optional crack processing must not discard a valid brightness value
        # or turn a processing failure into a negative defect measurement.
        damage = {"status": "unavailable", "validation_status": "unvalidated",
            "locations": [], "candidates": [], "overlay_mask": np.zeros(owned.shape,np.uint8),
            "binary_mask": {"encoding": "row_runs", "shape": list(owned.shape), "runs": []},
            "mask_validated_for_cracks": False, "used_for_grading": False,
            "confirmed_count": 0, "suspected_count": 0, "rejected_count": 0,
            "total_crack_length_px": None, "crack_area_px": None, "crack_density": None,
            "detection_reliability": "unavailable", "raw_measurements": {}, "calibrated_measurements": None,
            "reason": "surface_diagnostics_failed", "error_type": type(error).__name__}
    provenance = {"frame_id": provider.frame_id, "parent_track_id": parent_id,
                  "frame_width_px": frame.shape[1], "frame_height_px": frame.shape[0],
                  "frame_key": provider.frame_key, "coordinate_space": "crop_local_native_pixels",
                  "crop_bounds": bounds, "used_for_grading": False}
    brightness.update(provenance)
    damage.update(provenance)
    brightness["owned_mask"] = {"encoding": "row_runs", "shape": [h, w], "runs": pixel_runs(owned)}
    if owned.any():
        value = np.where(owned, rgb.max(axis=2), 0).astype(np.uint8)
        rgba = np.dstack((value, value, value, owned.astype(np.uint8) * 255))
        ok, encoded = cv2.imencode(".png", rgba)
        if ok:
            brightness["grayscale_image"] = "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")
    for item in damage.get("candidates", []):
        item["frame_bbox"] = [item["x"]+x, item["y"]+y, item["x"]+item["width"]+x, item["y"]+item["height"]+y]
        item["frame_contours"] = [[[px+x, py+y] for px, py in contour] for contour in item.get("contours", [])]
    result = {"brightness": brightness, "surface_damage": damage}
    if current:
        if not hasattr(provider, "_surface_results"):
            provider._surface_results = {}
        provider._surface_results[parent_id] = deepcopy(result)
    return result
