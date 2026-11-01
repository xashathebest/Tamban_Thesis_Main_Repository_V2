"""Complete serialized inspection evidence without rerunning models or pixels.

Older inspection workers emitted real ROI measurements but omitted the derived
width and geometric-stage payloads. This boundary adapter consumes those saved
measurements. Recorded grades remain authoritative unless an explicitly valid
calibration permits the existing shared geometric stage to contribute.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import math
from typing import Iterable, Mapping, Sequence

from src.inference.body_width import BodyWidthConfig, analyze_body_width, boxes_overlap, load_body_width_config
from src.inference.fish_geometry import measure_fish_geometry
from src.inference.geometric_support import integrate_geometric_support
from src.inference.grading_policy import FishPolicyVerdict, GRADE_NAMES, PART_NAMES, GradingPolicy
from src.inference.part_types import PartDetection


def _mapping(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _box(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    numbers = tuple(_number(item) for item in value)
    if any(item is None for item in numbers) or numbers[2] <= numbers[0] or numbers[3] <= numbers[1]:
        return None
    return numbers


def resolve_inspection_timestamp(event: Mapping, source_metadata: object = None) -> str | None:
    """Use an existing recorded timestamp; never substitute the export time."""
    analysis = _mapping(event.get("analysis"))
    sources = [event, analysis, _mapping(analysis.get("inspection_source")),
               _mapping(event.get("source_metadata")), _mapping(analysis.get("source_metadata")),
               _mapping(event.get("metadata")), _mapping(analysis.get("metadata")),
               _mapping(source_metadata)]
    for source in sources:
        for key in ("timestamp", "analyzed_at", "analysis_timestamp", "captured_at"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _region_rois(analysis: Mapping, region: str) -> list[dict]:
    supporting = _mapping(analysis.get("supporting_image_measurements"))
    reading = _mapping(_mapping(supporting.get("regions")).get(region))
    return [item for item in reading.get("frame_rois", ()) if isinstance(item, dict) and _box(item.get("crop_local_bbox"))]


def _roi_pair(analysis: Mapping) -> tuple[dict | None, dict | None]:
    whole, body = _region_rois(analysis, "Whole Fish"), _region_rois(analysis, "Body")
    for first in reversed(whole):
        for second in reversed(body):
            if first.get("frame_id") == second.get("frame_id"):
                return first, second
    return (whole[-1] if whole else None), None


def _parts(event: Mapping, analysis: Mapping, bounds: tuple | None) -> tuple[list[PartDetection], str]:
    """The API's event.parts are frame coordinates; debug selections are local."""
    values = event.get("parts")
    coordinate = "original_frame"
    if not isinstance(values, list) or not values:
        debug = _mapping(analysis.get("model2_debug"))
        values = debug.get("selected_detections", ())
        coordinate = "crop_local" if bounds is not None else "unverified"
    selected: list[PartDetection] = []
    for value in values if isinstance(values, (list, tuple)) else ():
        if not isinstance(value, Mapping):
            continue
        box = _box(value.get("bbox"))
        region, grade = value.get("region", value.get("part")), value.get("grade")
        confidence = _number(value.get("confidence", value.get("evidence_score")))
        if box is None or region not in PART_NAMES or grade not in GRADE_NAMES or confidence is None or not 0 <= confidence <= 1:
            continue
        if coordinate == "crop_local":
            box = (box[0] + bounds[0], box[1] + bounds[1], box[2] + bounds[0], box[3] + bounds[1])
        # Preserve exact saved semantics; no class confidence is invented.
        selected.append(PartDetection(int(value.get("source_class_id", -1)), str(value.get("source_class_name", "Recorded Model 2 part")), str(region), str(grade), confidence, box))
    return selected, coordinate


def _frame_shape(analysis: Mapping, supplied: Sequence[int] | None) -> tuple[int, int] | None:
    if supplied is not None and len(supplied) >= 2 and _number(supplied[0]) and _number(supplied[1]):
        return int(supplied[0]), int(supplied[1])
    latest = _mapping(_mapping(analysis.get("frame_quality")).get("latest"))
    source = _mapping(analysis.get("inspection_source"))
    height = _number(latest.get("frame_height", source.get("frame_height_px")))
    width = _number(latest.get("frame_width", source.get("frame_width_px")))
    return (int(height), int(width)) if height and width else None


def _configuration(analysis: Mapping, explicit: BodyWidthConfig | None) -> tuple[BodyWidthConfig, str]:
    if explicit is not None:
        return explicit, "explicit_configuration"
    recorded = _mapping(_mapping(analysis.get("body_width")).get("threshold_configuration"))
    if recorded:
        return BodyWidthConfig.from_mapping(recorded), "recorded_width_configuration"
    recorded = _mapping(_mapping(analysis.get("grading_config")).get("body_width"))
    if recorded:
        return BodyWidthConfig.from_mapping(recorded), "recorded_grading_config"
    # Current settings are useful export provenance but cannot retrospectively
    # certify legacy measurements or silently activate a historical grade.
    current = load_body_width_config()
    return replace(current, calibration_validated=False, scoring_enabled=False), "current_configuration_unvalidated_reconstruction"


def _scores(analysis: Mapping) -> dict[str, dict[str, float]]:
    parts = _mapping(analysis.get("part_results"))
    return {region: {grade: _number(_mapping(_mapping(parts.get(region)).get("grade_evidence")).get(grade)) or 0.0 for grade in GRADE_NAMES} for region in PART_NAMES}


def _recorded_decision(event: Mapping, analysis: Mapping) -> FishPolicyVerdict:
    scores = _mapping(analysis.get("weighted_scores"))
    weighted = {grade: _number(scores.get(grade)) or 0.0 for grade in GRADE_NAMES}
    observed = tuple(region for region in analysis.get("observed_regions", ()) if region in PART_NAMES)
    parts = _mapping(analysis.get("part_results"))
    if not observed:
        observed = tuple(region for region in PART_NAMES if _mapping(parts.get(region)).get("present") is True)
    weights = _mapping(analysis.get("effective_weights"))
    effective = {region: _number(weights.get(region)) or 0.0 for region in PART_NAMES}
    raw = _scores(analysis)
    contributions = {region: {grade: raw[region][grade] * effective[region] for grade in GRADE_NAMES} for region in PART_NAMES}
    original = event.get("quality", analysis.get("final_grade"))
    final_grade = original if original in GRADE_NAMES else None
    top = analysis.get("provisional_grade", analysis.get("best_evidence_class"))
    top = top if top in GRADE_NAMES else None
    second = analysis.get("second_grade")
    reasons = analysis.get("reason_codes", ())
    if not isinstance(reasons, (list, tuple)):
        reasons = [analysis.get("verdict_reason_code")] if analysis.get("verdict_reason_code") else []
    return FishPolicyVerdict(
        weighted, observed, _number(analysis.get("original_weight_coverage")) or 0.0,
        effective, contributions, top,
        _number(analysis.get("provisional_score", analysis.get("best_evidence_score"))),
        second if second in GRADE_NAMES else None, _number(analysis.get("second_support")),
        _number(analysis.get("grade_margin")), final_grade,
        _number(analysis.get("final_score", event.get("quality_confidence"))),
        tuple(str(reason) for reason in reasons if reason), _mapping(analysis.get("override")) or None,
    )


def _policy(analysis: Mapping) -> GradingPolicy:
    saved = _mapping(analysis.get("grading_config"))
    values = {name: saved[name] for name in GradingPolicy.__dataclass_fields__ if name in saved}
    weights = _mapping(saved.get("part_weights"))
    for region in PART_NAMES:
        if region in weights:
            values[f"{region.lower()}_weight"] = weights[region]
    return GradingPolicy(**values)


def normalize_inspection_result(
    event: Mapping, *, source_metadata: object = None, frame_shape: Sequence[int] | None = None,
    body_width_config: BodyWidthConfig | None = None, neighboring_events: Iterable[Mapping] = (),
) -> dict:
    """Fill disconnected evidence while keeping recorded weighted results intact."""
    result = deepcopy(dict(event))
    analysis = _mapping(result.get("analysis"))
    result["analysis"] = analysis
    timestamp = resolve_inspection_timestamp(result, source_metadata)
    if timestamp:
        result["timestamp"] = timestamp
    quality = _mapping(analysis.get("frame_quality"))
    latest = _mapping(quality.get("latest"))
    inference = _mapping(analysis.get("quality_inference"))
    bounds = _box(inference.get("crop_bounds"))
    model1 = _mapping(analysis.get("model1_detection"))
    whole = _box(latest.get("bbox")) or _box(model1.get("bbox")) or _box(result.get("bbox"))
    original_parts, coordinate = _parts(result, analysis, bounds)
    whole_roi, body_roi = _roi_pair(analysis)
    # A bare historical classification contains no derivable measurement.
    if whole is None and whole_roi is None:
        return result
    if not _mapping(analysis.get("fish_geometry")):
        # A saved ROI size or detector box cannot reconstruct a silhouette.
        # Report the missing source pixels instead of inventing mask geometry.
        pixel_geometry = measure_fish_geometry(None, parent_bbox=whole, frame_shape=_frame_shape(analysis, frame_shape))
        pixel_geometry["reasons"] = list(dict.fromkeys([
            *pixel_geometry.get("reasons", []), "historical_image_unavailable",
        ]))
        analysis["fish_geometry"] = pixel_geometry
    saved_width = _mapping(analysis.get("body_width"))
    saved_geometry = _mapping(analysis.get("geometric_support"))
    complete_geometry = "original_grade" in saved_geometry and "final_grade" in saved_geometry
    body = max((part for part in original_parts if part.region == "Body"), key=lambda item: item.confidence, default=None)
    inconsistent = bool(body is not None and (saved_width.get("measurement_status") == "Missing Detection" or saved_width.get("body_width_px") is None))
    needs_width = not saved_width or inconsistent or not _mapping(saved_width.get("threshold_configuration"))
    if not needs_width and complete_geometry:
        # A complete saved result is authoritative. Do not reinterpret its
        # calibration using current settings just to add ROI export metadata.
        config = None
        config_source = saved_width.get("threshold_configuration_source", "recorded_width_configuration")
    else:
        config, config_source = _configuration(analysis, body_width_config)
    width = dict(saved_width)
    if needs_width:
        association = _mapping(inference.get("association")) or _mapping(latest.get("association"))
        ambiguous = bool(association.get("ambiguous") or latest.get("association_ambiguous") or quality.get("association_status") == "ambiguous")
        ownership_known = coordinate != "unverified" and (bool(association) or inference.get("mode") == "crop")
        current_frame = latest.get("frame_id", whole_roi.get("frame_id") if whole_roi else None)
        metadata = _mapping(source_metadata)
        shared_photo = str(metadata.get("source_name", "")).lower().endswith((".jpg", ".jpeg", ".png", ".webp"))

        def same_capture(other: Mapping) -> bool:
            if event.get("session_id") and other.get("session_id") and event["session_id"] != other["session_id"]:
                return False
            other_analysis = _mapping(other.get("analysis"))
            other_latest = _mapping(_mapping(other_analysis.get("frame_quality")).get("latest"))
            other_frame = other_latest.get("frame_id")
            # Crop-mode still-image IDs can be per-fish within one photograph.
            # Explicitly different video/live frames cannot establish overlap.
            if not shared_photo and current_frame is not None and other_frame is not None:
                return current_frame == other_frame
            return True

        overlapping = any(other is not event and same_capture(other) and _box(other.get("bbox")) and boxes_overlap(whole, other.get("bbox")) for other in neighboring_events)
        body_crop_clipped = bool(body is not None and bounds is not None and (body.bbox[0] <= bounds[0] or body.bbox[1] <= bounds[1] or body.bbox[2] >= bounds[2] or body.bbox[3] >= bounds[3]))
        width = analyze_body_width(
            whole, original_parts, config=config,
            detection_confidence=_number(model1.get("confidence", result.get("detector_confidence", latest.get("model1_detection_confidence")))),
            frame_shape=_frame_shape(analysis, frame_shape),
            parent_usable=bool(quality.get("parent_usable", True)) and bool(latest.get("usable", True)),
            association_reliable=ownership_known and not ambiguous,
            association_status="ambiguous" if ambiguous else quality.get("association_status"),
            clipped=bool(latest.get("frame_clipped") or quality.get("out_of_frame") or body_crop_clipped),
            overlapping=overlapping,
            minimum_part_confidence=_number(_mapping(analysis.get("grading_config")).get("minimum_part_confidence")) or .25,
        )
        width.update(coordinate_space="original_frame" if coordinate != "unverified" else "unverified",
                     frame_id=whole_roi.get("frame_id") if whole_roi else latest.get("frame_id"),
                     threshold_configuration_source=config_source)
    # Preserve both the detector's fractional box and the actual integer ROI.
    if whole:
        width.setdefault("detector_whole_fish_width_px", whole[2] - whole[0])
        width.setdefault("detector_whole_fish_height_px", whole[3] - whole[1])
    if body:
        width.setdefault("detector_body_width_px", body.bbox[2] - body.bbox[0])
        width.setdefault("detector_body_height_px", body.bbox[3] - body.bbox[1])
    if whole and body:
        width.setdefault("bbox_relative_width_proxy", min(body.bbox[2] - body.bbox[0], body.bbox[3] - body.bbox[1]) / max(whole[2] - whole[0], whole[3] - whole[1]))
    for prefix, reading in (("whole_fish", whole_roi), ("body", body_roi)):
        if reading:
            box = _box(reading["crop_local_bbox"])
            width[f"{prefix}_roi_width_px"], width[f"{prefix}_roi_height_px"] = box[2] - box[0], box[3] - box[1]
    if whole_roi and body_roi:
        proxy = min(width["body_roi_width_px"], width["body_roi_height_px"]) / max(width["whole_fish_roi_width_px"], width["whole_fish_roi_height_px"])
        width["roi_relative_width_proxy"] = proxy
        width["roi_measurement_context"] = {"Whole Fish": deepcopy(whole_roi), "Body": deepcopy(body_roi)}
        if needs_width:
            width.update(relative_width_proxy=proxy, initial_relative_width_proxy=proxy,
                         relative_width_proxy_source="existing_ROI_measurements",
                         measurement_method="existing_rectangular_roi_pixel_proxy")
            if body is None:
                width.update(status="measured", measurement_available=True, measurement_status="Unreliable",
                             reliability="Unreliable", reliable_for_scoring=False, width_abnormality="Unreliable")
                width["reliability_reasons"] = list(dict.fromkeys([*width.get("reliability_reasons", []), "detector_body_geometry_unavailable"]))
            # A calibration established for detector boxes cannot be silently
            # reused for a reconstructed integer-pixel ROI ratio.
            if config.calibration_validated:
                width.update(reliable_for_scoring=False, measurement_status="Unreliable", reliability="Unreliable",
                             class_c_supporting_points=None, score_status="Unavailable")
                width["reliability_reasons"] = list(dict.fromkeys([*width.get("reliability_reasons", []), "roi_proxy_calibration_not_validated"]))
    width.setdefault("relative_width_proxy_source", "detector_bounding_boxes")
    analysis["body_width"] = width
    if not complete_geometry or needs_width:
        decision = _recorded_decision(result, analysis)
        final, width, geometry = integrate_geometric_support(decision, width, config, _policy(analysis), part_scores=_scores(analysis))
        if not isinstance(analysis.get("weighted_scores"), Mapping):
            # A legacy high-level grade does not reveal its weighted vector.
            # Retain that grade without fabricating missing class support.
            recorded_grade = result.get("quality") or analysis.get("final_grade") or "Ungraded"
            geometry.update(original_grade=recorded_grade, final_grade=recorded_grade,
                            original_scores={}, final_scores={}, normalized_original_scores={})
        analysis["body_width"], analysis["geometric_support"] = width, geometry
        if geometry.get("contribution_applied"):
            result.update(quality=final.final_grade, quality_confidence=final.final_support)
            analysis.update(final_grade=final.final_grade, final_score=final.final_support,
                            final_support=final.final_support, weighted_scores=dict(final.weighted_scores))
    grading = _mapping(analysis.get("grading_config"))
    grading.setdefault("body_width", config.to_dict() if config is not None else deepcopy(width["threshold_configuration"]))
    analysis["grading_config"] = grading
    analysis.setdefault("result_normalization", {"algorithm_version": "serialized_inspection_width_v1", "width_configuration_source": config_source})
    return result


def normalize_inspection_results(
    events: Iterable[Mapping], *, source_metadata: object = None,
    frame_shape: Sequence[int] | None = None, body_width_config: BodyWidthConfig | None = None,
) -> list[dict]:
    """Normalize a complete batch so visible neighbors remain ownership risks."""
    rows = list(events)
    return [normalize_inspection_result(event, source_metadata=source_metadata,
            frame_shape=frame_shape, body_width_config=body_width_config,
            neighboring_events=[other for other in rows if other is not event]) for event in rows]
