"""Frame-scoped diagnostic reuse and original-image measurement overlays."""
from __future__ import annotations

import json
import logging
from time import perf_counter
import cv2
import numpy as np

from src.features.damage import analyze_surface_damage
from src.inference.preprocessing import CropBounds, RuntimeMaskContext


def _parent_damage(frame, bounds: CropBounds, parent_id, *, mask_context=None,
                  parent_context=None, frame_id=None):
    context = mask_context if isinstance(mask_context, RuntimeMaskContext) and mask_context.is_for_frame(frame) else RuntimeMaskContext(frame, frame_id=frame_id)
    flags = dict(parent_context or {})
    name = "surface_damage_v2:" + json.dumps(flags, sort_keys=True, separators=(",", ":"))
    def calculate():
        lookup_started = perf_counter()
        if context.backend == "mobilesam_experimental":
            mask, metadata = context.trusted_body_mask(parent_id, bounds)
            if mask is None:
                return {"status": "unavailable", "label": "No reliable evidence", "evidence_state": "No reliable evidence",
                        "reason": "A reviewed, correctly owned Body pixel mask is unavailable; MobileSAM candidates do not establish Body anatomy.",
                        "mask_validated_for_cracks": False, "used_for_grading": False, "locations": [],
                        "confidence": None, "estimated_length_px": None, "severity": "unassessed",
                        "parent_track_id": parent_id, "frame_id": frame_id, "coordinate_space": "crop_local_native_pixels",
                        "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2], "body_support": metadata}
        else:
            mask, metadata = context.get(parent_id, bounds)
        lookup_ms = round((perf_counter() - lookup_started) * 1000, 3)
        crop = frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
        color_started = perf_counter()
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        color_ms = round((perf_counter() - color_started) * 1000, 3)
        damage_started = perf_counter()
        result = analyze_surface_damage(
            rgb,
            mask if mask is not None else np.zeros(crop.shape[:2], dtype=bool),
            mask_source=str(metadata.get("source", "runtime_mask_unavailable")),
            mask_metadata=metadata, parent_context=flags,
        )
        result.update(mask_metadata=metadata, parent_track_id=parent_id, frame_id=frame_id,
                      coordinate_space="crop_local_native_pixels",
                      crop_bounds=[bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                      performance={"mask_lookup_ms": lookup_ms, "rgb_conversion_ms": color_ms,
                                   "structural_detection_ms": round((perf_counter() - damage_started) * 1000, 3),
                                   "scope": "cached factory execution; cache hits reuse this original evidence"})
        for location in result.get("locations", []):
            location["frame_bbox"] = [location["x"] + bounds.x1, location["y"] + bounds.y1,
                                      location["x"] + location["width"] + bounds.x1,
                                      location["y"] + location["height"] + bounds.y1]
        return result
    return context.cached_feature(parent_id, bounds, name, calculate)


def parent_damage(frame, bounds: CropBounds, parent_id, *, mask_context=None,
                  parent_context=None, frame_id=None):
    try:
        return _parent_damage(frame, bounds, parent_id, mask_context=mask_context,
                              parent_context=parent_context, frame_id=frame_id)
    except Exception as error:
        logging.getLogger(__name__).warning("Optional damage diagnostics failed for fish %s: %s", parent_id, error)
        return {"status": "unavailable", "label": "No reliable evidence", "evidence_state": "No reliable evidence",
                "confidence": None, "severity": "unassessed", "estimated_length_px": None, "locations": [],
                "mask_validated_for_cracks": False, "used_for_grading": False,
                "reason": "surface_diagnostics_failed", "error_type": type(error).__name__,
                "parent_track_id": parent_id, "frame_id": frame_id,
                "coordinate_space": "crop_local_native_pixels",
                "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                "overlay_mask": np.zeros((bounds.height, bounds.width), dtype=np.uint8)}


def draw_damage(frame, damage, bounds: CropBounds):
    if damage.get("status") != "suspected": return
    overlay = damage.get("overlay_mask")
    if not isinstance(overlay, np.ndarray) or overlay.ndim != 2: return
    target = frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
    if target.shape[:2] != overlay.shape: return
    selected = overlay > 0
    # Blend only the selected ROI pixels; no full-frame colour allocation.
    target[selected] = (.65 * target[selected] + .35 * np.array((0, 0, 220))).astype(np.uint8)


def draw_geometry(frame, geometry):
    visual = geometry.get("visualization", {})
    if geometry.get("status") != "measured" or visual.get("measured") is not True or visual.get("coordinate_space") != "original_frame": return
    height, width = frame.shape[:2]
    def points(key, minimum):
        array = np.asarray(visual.get(key, []), dtype=float)
        if array.ndim != 2 or array.shape[1] != 2 or len(array) < minimum or not np.isfinite(array).all(): return None
        if (array[:, 0].min() < 0 or array[:, 1].min() < 0 or array[:, 0].max() >= width or array[:, 1].max() >= height): return None
        return np.rint(array).astype(np.int32)
    for key, color in (("silhouette_boundary", (220, 170, 0)), ("body_region_boundary", (190, 160, 100))):
        vertices = points(key, 3)
        if vertices is not None: cv2.polylines(frame, [vertices], True, color, 1, cv2.LINE_AA)
    for key, color in (("principal_axis", (40, 220, 80)), ("width_axis", (0, 190, 255))):
        vertices = points(key, 2)
        if vertices is None: continue
        cv2.line(frame, tuple(vertices[0]), tuple(vertices[-1]), color, 2, cv2.LINE_AA)
        for endpoint in (vertices[0], vertices[-1]): cv2.circle(frame, tuple(endpoint), 3, color, -1)
    axis = points("principal_axis", 2)
    length, body_width = geometry.get("fish_length_px"), geometry.get("max_body_width_px")
    if axis is not None and isinstance(length, (float, int)) and isinstance(body_width, (float, int)):
        origin = (int(axis[:, 0].min()), max(14, int(axis[:, 1].min()) - 8))
        cv2.putText(frame, f"L {length:.1f}px W {body_width:.1f}px", origin,
                    cv2.FONT_HERSHEY_SIMPLEX, .4, (40, 220, 80), 1, cv2.LINE_AA)
