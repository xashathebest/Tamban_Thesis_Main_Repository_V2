"""Read-only dashboard summaries of unique, persisted inspection results.

No prediction or grading runs here. Missing telemetry remains unavailable, and
part candidates are described as saved fish snapshots rather than frame totals.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
from typing import Mapping


GRADES = ("Class A", "Class B", "Class C", "Rejected", "Ungraded")
REGIONS = ("Head", "Body", "Tail")
GRANULARITIES = ("hour", "day", "week", "month")


def mapping(value):
    return value if isinstance(value, Mapping) else {}


def finite(value, *, maximum=None):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 and (maximum is None or number <= maximum) else None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def final_grade(event):
    analysis = mapping(event.get("analysis"))
    fusion = mapping(analysis.get("feature_fusion"))
    if fusion.get("schema_version") == "feature_fusion_v1":
        grade = fusion.get("final_grade")
    else:
        grade = next((value for value in (event.get("ai_final_grade"), analysis.get("ai_final_grade"),
                                          event.get("final_grade"), analysis.get("final_grade"),
                                          event.get("quality"), event.get("grade")) if value not in (None, "")), None)
    return grade if grade in GRADES else "Ungraded"


def bucket_for(value, granularity):
    parsed = timestamp(value)
    if parsed is None:
        return None
    if granularity == "hour":
        # Retain the recorded UTC offset so repeated DST hours stay distinct.
        return parsed.replace(minute=0, second=0, microsecond=0).isoformat()
    if granularity == "week":
        return (parsed.date() - timedelta(days=parsed.weekday())).isoformat()
    if granularity == "month":
        return parsed.date().replace(day=1).isoformat()
    return parsed.date().isoformat()


def mean(values):
    return round(sum(values) / len(values), 3) if values else None


def histogram(values):
    return [{"label": f"{start}–{start + 20}%", "min": start, "max": start + 20,
             "count": sum(start <= value < start + 20 or (start == 80 and value == 100) for value in values)}
            for start in range(0, 100, 20)]


def _first_number(sources, names, *, maximum=None):
    for source in sources:
        for name in names:
            number = finite(source.get(name), maximum=maximum)
            if number is not None:
                return number
    return None


def _region(part):
    item = mapping(part)
    region = item.get("region") or item.get("part_name")
    if region in REGIONS:
        return region
    name = str(item.get("source_class_name") or item.get("class_name") or "")
    return next((region for region in REGIONS if name.endswith("_" + region)), None)


def build_dashboard(events, sessions, *, scope, granularity="day"):
    """Aggregate one consistent saved-record snapshot; each row is one fish."""
    if granularity not in GRANULARITIES:
        raise ValueError("Analytics granularity must be hour, day, week, or month.")
    distribution = Counter({grade: 0 for grade in GRADES})
    counts_by_session = defaultdict(Counter)
    activity = {}
    reasons = Counter()
    anatomy = {region: {"raw_count": 0, "assigned_count": 0, "raw_candidate_count": 0,
                        "assigned_candidate_count": 0, "raw_fish_samples": 0,
                        "assigned_fish_samples": 0, "present_fish_count": 0} for region in REGIONS}
    detection, supports, fish_times, image_times = [], [], [], []
    stages = defaultdict(list)
    fps = {"ai_fps": [], "camera_fps": []}
    seen_rates = {"ai_fps": set(), "camera_fps": set()}
    seen_images = set()
    missing_timestamps = 0
    total = 0
    for event in events:
        total += 1
        analysis = mapping(event.get("analysis"))
        grade = final_grade(event)
        session_id = event.get("session_id")
        distribution[grade] += 1
        counts_by_session[session_id][grade] += 1
        bucket = bucket_for(event.get("timestamp"), granularity)
        if bucket:
            point = activity.setdefault(bucket, {"bucket": bucket, "fish_count": 0,
                                                "grade_distribution": {grade: 0 for grade in GRADES}, "session_ids": set()})
            point["fish_count"] += 1
            point["grade_distribution"][grade] += 1
            if session_id:
                point["session_ids"].add(session_id)
        else:
            missing_timestamps += 1
        if grade == "Ungraded":
            recorded = analysis.get("reason_codes") or event.get("reason_codes")
            codes = {code.strip() for code in recorded if isinstance(code, str) and code.strip()} if isinstance(recorded, (list, tuple)) else set()
            if not codes:
                code = analysis.get("verdict_reason_code") or event.get("verdict_reason_code")
                if isinstance(code, str) and code.strip():
                    codes.add(code.strip())
            reasons.update(codes or {"Not recorded"})
        debug = mapping(analysis.get("model2_debug"))
        raw = debug.get("raw_detections")
        assigned = debug.get("selected_detections")
        raw_counts = Counter(_region(part) for part in raw) if isinstance(raw, list) else None
        assigned_counts = Counter(_region(part) for part in assigned) if isinstance(assigned, list) else None
        part_results = mapping(analysis.get("part_results"))
        for region, summary in anatomy.items():
            summary["present_fish_count"] += int(mapping(part_results.get(region)).get("present") is True)
            if raw_counts is not None:
                summary["raw_fish_samples"] += 1
                summary["raw_count"] += int(raw_counts[region] > 0)
                summary["raw_candidate_count"] += raw_counts[region]
            if assigned_counts is not None:
                summary["assigned_fish_samples"] += 1
                summary["assigned_count"] += int(assigned_counts[region] > 0)
                summary["assigned_candidate_count"] += assigned_counts[region]
        confidence = finite(mapping(analysis.get("model1_detection")).get("confidence"), maximum=1)
        if confidence is None:
            confidence = _first_number([event], ["detector_confidence", "final_confidence", "model1_detection_confidence"], maximum=1)
        if confidence is not None:
            detection.append(confidence * 100)
        fusion = mapping(analysis.get("feature_fusion"))
        support = _first_number([fusion, analysis, event], ["final_support", "final_score"], maximum=1)
        if support is not None:
            supports.append(support * 100)
        fish_time = finite(event.get("processing_time_ms"))
        if fish_time is not None:
            fish_times.append(fish_time)
        performance = mapping(analysis.get("performance"))
        frame_performance = mapping(analysis.get("frame_performance"))
        sources = [mapping(event.get("performance")), performance, frame_performance, event, analysis]
        for key in {key for source in sources[:3] for key in source if key.endswith("_ms")}:
            value = _first_number(sources[:3], [key])
            if value is not None:
                stages[key].append(value)
        image_time = _first_number(sources, ["image_processing_time_ms", "image_analysis_time_ms"])
        image_id = (session_id, event.get("image_id") or analysis.get("image_id") or event.get("timestamp"), image_time)
        if image_time is not None and image_id not in seen_images:
            seen_images.add(image_id)
            image_times.append(image_time)
        for name, aliases in (("ai_fps", ["processing_fps", "ai_processing_fps"]),
                              ("camera_fps", ["capture_fps", "camera_preview_fps"])):
            value = _first_number(sources, aliases)
            identity = (session_id, frame_performance.get("frame_id") or event.get("timestamp"), value)
            if value is not None and identity not in seen_rates[name]:
                seen_rates[name].add(identity)
                fps[name].append({"timestamp": event.get("timestamp"), "session_id": session_id, "value": value})
    comparisons = []
    selected_sessions = set(counts_by_session)
    custom = scope.get("range") in {"custom", "today"}
    for session in sessions:
        identifier = session["session_id"]
        session_date = str(session.get("started_at") or "")[:10]
        in_dates = (not scope.get("start_date") or session_date >= scope["start_date"]) and (not scope.get("end_date") or session_date <= scope["end_date"])
        if scope.get("session_id") and identifier != scope["session_id"]:
            continue
        if custom and not in_dates and identifier not in selected_sessions:
            continue
        if scope.get("range") == "current_session" and not scope.get("session_id"):
            continue
        grades = {grade: counts_by_session[identifier][grade] for grade in GRADES}
        fish_count = sum(grades.values())
        complete_count = int(session.get("fish_count") or 0)
        start, end = timestamp(session.get("started_at")), timestamp(session.get("ended_at"))
        try:
            duration = (end - start).total_seconds() if start and end and end >= start else None
        except TypeError:
            duration = None
        active = finite(session.get("active_seconds"))
        partial = custom and (fish_count != complete_count or not in_dates or bool(end and scope.get("end_date") and end.date().isoformat() > scope["end_date"]))
        rate = round(fish_count * 60 / active, 3) if active and not partial else None
        comparisons.append({"session_id": identifier, "started_at": session.get("started_at"),
                            "ended_at": session.get("ended_at"), "fish_count": fish_count,
                            "complete_fish_count": complete_count, "grade_distribution": grades,
                            "duration_seconds": duration, "active_seconds": active,
                            "fish_per_minute": rate, "partial_scope": partial,
                            "duration_basis": "whole_saved_session", "rate_basis": "recorded_active_seconds"})
    for point in activity.values():
        point["session_ids"] = sorted(point["session_ids"])
    for summary in anatomy.values():
        for kind in ("raw", "assigned"):
            if not summary[f"{kind}_fish_samples"]:
                summary[f"{kind}_count"] = summary[f"{kind}_candidate_count"] = None
        summary["basis"] = "Unique fish records with recorded part candidates; candidate totals are per-fish snapshots and can share source-frame detections."
    active_seconds = sum(row["active_seconds"] or 0 for row in comparisons)
    whole_measured_scope = comparisons and all(
        row["active_seconds"] is not None and (row["fish_count"] == 0 or row["active_seconds"] > 0)
        and not row["partial_scope"] for row in comparisons
    )
    throughput = round(total * 60 / active_seconds, 3) if whole_measured_scope and active_seconds > 0 else None
    ungraded, rejected = distribution["Ungraded"], distribution["Rejected"]
    unavailable = []
    if not fps["ai_fps"]:
        unavailable.append("AI processing FPS was not recorded; capture FPS and processing durations are not substituted.")
    if not fps["camera_fps"]:
        unavailable.append("Camera preview/capture FPS was not recorded; configured hardware FPS is not measured throughput.")
    if not image_times:
        unavailable.append("Image processing duration was not recorded separately from per-fish processing time.")
    if throughput is None:
        unavailable.append("Fish per minute requires a complete scope and recorded positive active inspection time.")
    return {
        "schema_version": "saved_analytics_v2", "scope": dict(scope),
        "kpis": {"total_inspected": total, "session_count": len(comparisons), "graded_count": total - ungraded,
                 "graded_rate_percent": round((total - ungraded) / total * 100, 2) if total else None,
                 "ungraded_count": ungraded, "ungraded_rate_percent": round(ungraded / total * 100, 2) if total else None,
                 "accepted_count": total - ungraded - rejected, "rejected_count": rejected,
                 "grade_distribution": dict(distribution), "active_seconds": active_seconds if whole_measured_scope else None,
                 "duration_seconds": sum(row["duration_seconds"] for row in comparisons) if comparisons and all(row["duration_seconds"] is not None for row in comparisons) else None},
        "coverage": {"classified": total - ungraded - rejected, "rejected": rejected, "ungraded": ungraded,
                     "basis": "Mutually exclusive original final grade buckets; legacy graded_count includes Rejected."},
        "activity": {"granularity": granularity, "items": [activity[key] for key in sorted(activity)],
                     "available_granularities": list(GRANULARITIES), "missing_timestamp_count": missing_timestamps,
                     "date_basis": "recorded_fish_timestamp_local_offset"},
        "session_comparison": comparisons, "anatomical_association": anatomy, "ungraded_reasons": dict(reasons),
        "performance": {**fps, "stage_ms": {key: mean(values) for key, values in sorted(stages.items())},
                        "stage_basis": "Mean of recorded per-fish evidence snapshots; shared frame stage timings can be repeated across fish.",
                        "average_image_processing_time_ms": mean(image_times), "image_processing_samples": len(image_times),
                        "average_fish_processing_time_ms": mean(fish_times), "fish_processing_samples": len(fish_times),
                        "fish_per_minute": throughput, "fish_per_minute_basis": "unique fish / recorded active inspection minutes",
                        "distributions": {"detection_confidence": histogram(detection), "final_support": histogram(supports)},
                        "distribution_samples": {"detection_confidence": len(detection), "final_support": len(supports)},
                        "unavailable": unavailable},
    }
