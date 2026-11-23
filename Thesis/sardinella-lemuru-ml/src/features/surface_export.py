"""Lossless surface measurement columns; no grading or calibration on export."""
from __future__ import annotations

import json


BRIGHTNESS_FIELDS = ("mean_brightness", "median_brightness", "brightness_std",
                     "brightness_percentiles", "brightness_pixel_count", "brightness_mask_coverage")
CANDIDATE_FIELDS = {
    "crack_candidate_id": "candidate_id", "crack_candidate_type": "candidate_type",
    "crack_confidence": "confidence", "crack_length": "estimated_length_px",
    "crack_width": "median_width_px", "crack_area": "area_px", "crack_density": "crack_density",
    "crack_aspect_ratio": "aspect_ratio", "crack_skeleton_length": "skeleton_length_px",
    "crack_owner_fish_id": "owner_fish_id", "crack_validation_status": "validation_status",
    "crack_exclusion_reason": "exclusion_reason",
}
SURFACE_FIELDS = (*BRIGHTNESS_FIELDS, "brightness_distribution", "brightness_reliability",
                  *CANDIDATE_FIELDS, "crack_detection_reliability", "crack_candidates_omitted", "surface_raw_measurements", "surface_calibrated_measurements")


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def surface_export_record(event):
    analysis = event.get("analysis") or event.get("quality_analysis") or {}
    brightness, damage = analysis.get("brightness") or {}, analysis.get("surface_damage") or {}
    candidates = damage.get("candidates") or []
    record = {key: brightness.get(key) if brightness.get(key) is not None else "" for key in BRIGHTNESS_FIELDS}
    record.update(brightness_percentiles=_json(brightness.get("brightness_percentiles") or {}),
                  brightness_distribution=_json(brightness.get("distribution") or {}),
                  brightness_reliability=brightness.get("measurement_reliability") or "unavailable")
    record["crack_detection_reliability"] = damage.get("detection_reliability") or "unavailable"
    record["crack_candidates_omitted"] = damage.get("candidates_omitted", "")
    # Session CSVs remain one row per fish. Candidate arrays share the same
    # order; the dedicated candidate CSV/XLSX sheet is one row per candidate.
    record.update({column: _json([candidate.get(key) for candidate in candidates])
                   for column, key in CANDIDATE_FIELDS.items()})
    record["surface_raw_measurements"] = _json({"brightness": brightness.get("raw_measurements") or {},
        "cracks": damage.get("raw_measurements") or {}, "candidates": candidates})
    record["surface_calibrated_measurements"] = _json({"brightness": brightness.get("calibrated_measurements"),
                                                       "cracks": damage.get("calibrated_measurements")})
    return record


def surface_candidate_rows(events):
    for event in events:
        analysis = event.get("analysis") or event.get("quality_analysis") or {}
        damage, brightness = analysis.get("surface_damage") or {}, analysis.get("brightness") or {}
        base = {"fish_id": event.get("track_id", event.get("id", event.get("fish_id", ""))),
                **surface_export_record(event)}
        for candidate in damage.get("candidates") or [None]:
            candidate = candidate or {}
            yield {**base, **{column: candidate.get(key) if candidate.get(key) is not None else ""
                              for column, key in CANDIDATE_FIELDS.items()},
                "surface_raw_measurements": _json({"brightness": brightness.get("raw_measurements") or {},
                                                    "cracks": damage.get("raw_measurements") or {}}),
                "crack_candidate_evidence": _json(candidate),
                "crack_raw_measurements": _json(candidate.get("raw_measurements") or {}),
                "crack_calibrated_measurements": _json(candidate.get("calibrated_measurements")),
                "frame_id": brightness.get("frame_id", damage.get("frame_id", "")),
                "coordinate_space": damage.get("coordinate_space") or "",
                "crop_bounds": _json(damage.get("crop_bounds") or []),
                "measurement_units": "brightness percent; length/width native pixels; area native pixels squared; density fraction",
                "crack_confidence_kind": candidate.get("confidence_kind") or "heuristic_not_probability"}
