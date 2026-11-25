"""Secondary anatomy evidence, activated only by missing Model 2 Head/Body.

Silhouette measurements are observations, not a calibrated absence classifier.
Only independent, same-source reviewed anatomical evidence may establish
PRESENT/MISSING when the primary detector misses a region. Quality scores are
never synthesized from presence evidence.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

from src.inference.decision_fusion import source_matches


REQUIRED = ("Head", "Body")
VERSION = "1"
MINIMUM_REVIEW_CONFIDENCE = .95  # Review assertion gate, never a calibrated accuracy.
VISIBILITY_HAZARDS = ("clipped", "occluded", "overlapping", "ownership_ambiguous",
                      "partial_silhouette", "incomplete_visibility", "frame_clipped",
                      "parent_frame_clipped", "parent_crop_clipped", "out_of_frame")


def _visibility_issues(record, *, strict=False):
    """Malformed flags withhold confirmation, rather than becoming false."""
    issues = [key for key in VISIBILITY_HAZARDS if key in record and record[key] is not False and (strict or record[key] is not None)]
    issues += [key for key in ("visibility_validated", "complete_visibility", "complete_mask")
               if key in record and record[key] is not True]
    return issues


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def load_anatomical_evidence(*, fish_id, frame_id, source):
    """Read an optional local review catalog; never infer or approve a record.

    A catalog is evidence supplied by its reviewer, not authenticated identity.
    The verdict path rechecks every identity, visibility and provenance field.
    No catalog is required for normal inspection.
    """
    configured = os.getenv("FISH_ANATOMICAL_EVIDENCE_PATH", "").strip()
    if not configured:
        return [], {"status": "not_configured"}
    try:
        path = Path(configured).expanduser()
        if path.stat().st_size > 1_048_576:
            raise ValueError("Anatomical evidence catalog exceeds 1 MiB.")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(catalog, dict) or catalog.get("schema_version") != "anatomical_evidence_v1"
                or not isinstance(catalog.get("records"), list) or len(catalog["records"]) > 1000):
            raise ValueError("Expected at most 1000 anatomical_evidence_v1 records.")
        records = [row for row in catalog["records"] if source_matches(row, fish_id=fish_id, frame_id=frame_id, source=source)]
        return records, {"status": "loaded", "matching_records": len(records)}
    except (OSError, ValueError, TypeError) as error:
        return [], {"status": "unavailable", "reason": str(error)}


def inspect_silhouette(mask, metadata, parts=(), *, fish_id=None, frame_id=None):
    """Bounded CPU geometry using only this parent's native instance pixels.

    The axis is directional only with an owned Head/Tail anchor. Flat ends and
    gaps remain candidates: a SAM error, occlusion or foreshortening can produce
    the same outline as a cut. No diagnostic here authorizes rejection.
    """
    metadata = metadata if isinstance(metadata, Mapping) else {}
    report = {"status": "unavailable", "validated_for_absence": False,
              "orientation": "UNCERTAIN", "reason": metadata.get("reason", "Individual fish mask unavailable."),
              "mask_source": metadata.get("source", "unavailable"),
              "fish_id": fish_id, "frame_id": frame_id}
    if ((fish_id is not None and (metadata.get("parent_track_id") != fish_id or isinstance(metadata.get("parent_track_id"), (bool, float))))
            or (frame_id is not None and (metadata.get("frame_id") != frame_id or isinstance(metadata.get("frame_id"), (bool, float))))):
        return {**report, "reason": "Mask does not belong to the requested fish and frame.", "blockers": ["mask_identity_mismatch"]}
    if (not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype.kind not in "buif"
            or not np.isfinite(mask).all() or not np.isin(mask, (0, 1, 255)).all() or not mask.any()):
        return report
    blockers = []
    if metadata.get("parent_isolation_reliable") is not True:
        blockers.append("individual_mask_ownership_unreliable")
    blockers.extend(_visibility_issues(metadata))
    if blockers:
        return {**report, "reason": "; ".join(blockers), "blockers": blockers}
    binary = (mask != 0).astype(np.uint8)
    # Large photos use a bounded working grid for diagnostics, never metrology.
    scale = min(1., 384. / max(binary.shape))
    if scale < 1:
        binary = cv2.resize(binary, (max(1, round(binary.shape[1] * scale)), max(1, round(binary.shape[0] * scale))), interpolation=cv2.INTER_NEAREST)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    areas = sorted((int(v) for v in stats[1:, cv2.CC_STAT_AREA]), reverse=True)
    if count != 2 or not areas or areas[0] < 32:
        return {**report, "reason": "Fragmented or insufficient visible fish tissue."}
    y, x = np.nonzero(binary)
    points = np.column_stack((x, y)).astype(float)
    center = points.mean(axis=0)
    covariance = np.cov(points - center, rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    ratio = math.sqrt(max(0., values[1]) / max(1e-9, values[0]))
    axis = vectors[:, 1]
    longitudinal = (points - center) @ axis
    normal = (points - center) @ np.array([-axis[1], axis[0]])
    low, high = float(longitudinal.min()), float(longitudinal.max())
    span = high - low
    if span <= 0 or ratio < 2.:
        return {**report, "reason": "Fish is too short or foreshortened to resolve its anatomical axis.", "principal_axis_ratio": ratio}
    direction_votes = []
    for part in parts:
        if part.region not in {"Head", "Tail"}:
            continue
        px = (part.bbox[0] + part.bbox[2]) * .5
        py = (part.bbox[1] + part.bbox[3]) * .5
        ix, iy = int(px), int(py)
        if not (0 <= iy < mask.shape[0] and 0 <= ix < mask.shape[1] and mask[iy, ix]):
            continue
        position = float((np.array([px, py]) * scale - center) @ axis)
        fraction = (position - low) / span
        if part.region == "Head" and (fraction < .35 or fraction > .65):
            direction_votes.append(1 if fraction < .35 else -1)
        if part.region == "Tail" and (fraction < .25 or fraction > .75):
            direction_votes.append(-1 if fraction < .25 else 1)
    directional = bool(direction_votes) and len(set(direction_votes)) == 1
    if directional and direction_votes[0] < 0:
        axis = -axis
        longitudinal = -longitudinal
        low, high = -high, -low
    bins = np.clip(((longitudinal - low) / span * 24).astype(int), 0, 23)
    widths = [float(np.ptp(normal[bins == i])) / scale if np.any(bins == i) else 0. for i in range(24)]
    centers = [float(np.mean(normal[bins == i])) if np.any(bins == i) else 0. for i in range(24)]
    curvature = float(np.ptp(centers) / max(1., max(widths) * scale))
    orientation = "HEAD_TO_TAIL" if directional and curvature <= .6 else "UNCERTAIN"
    peak = max(widths)
    if peak <= 0:
        return {**report, "reason": "Insufficient transverse tissue support; a line is not a fish silhouette."}
    regions = {}
    if orientation == "HEAD_TO_TAIL":
        for region, indices in (("Head", range(0, 6)), ("Body", range(6, 19))):
            selected = [widths[i] for i in indices]
            regions[region] = {"tissue_pixels": int(np.isin(bins, list(indices)).sum()),
                               "longitudinal_occupancy": sum(w > 0 for w in selected) / len(selected),
                               "maximum_width_px": max(selected), "anatomical_identity_validated": False}
    return {**report, "status": "candidate", "orientation": orientation,
            "axis_head_to_tail": axis.tolist() if orientation == "HEAD_TO_TAIL" else None,
            "principal_axis_ratio": ratio, "centerline_deviation_ratio": curvature,
            "width_profile_px": widths, "continuous_longitudinal_support": all(w > 0 for w in widths[1:-1]),
            "endpoint_cut_candidates": {"start": widths[0] / peak > .55, "end": widths[-1] / peak > .55},
            "expected_regions": regions, "working_scale": scale,
            "reason": "Silhouette tissue, continuity and endpoint candidates are uncalibrated; they cannot establish anatomical presence or absence."}


def verify_anatomy(presence, *, threshold, fish_id, frame_id, source=None,
                   geometry=None, evidence=(), frame_quality=None, model2_available=True):
    """Model 2 first; independently reviewed evidence only for missed regions."""
    quality = frame_quality if isinstance(frame_quality, Mapping) else {}
    association_blockers = [key for key in ("parent_uncertain", "association_ambiguous", "source_pixels_mismatch", "evidence_identity_mismatch")
                            if quality.get(key)]
    if quality.get("parent_usable") is False:
        association_blockers.append("parent_usable")
    if str(quality.get("association_status", "")).lower() in {"ambiguous", "association_ambiguous", "unassigned", "rejected"}:
        association_blockers.append("association_ambiguous")
    binding = quality.get("anatomical_input_context")
    if isinstance(binding, Mapping) and (binding.get("fish_id") != fish_id or binding.get("frame_id") != frame_id
                                         or isinstance(binding.get("fish_id"), (bool, float))
                                         or isinstance(binding.get("frame_id"), (bool, float))):
        association_blockers.append("evidence_identity_mismatch")
    blockers = list(dict.fromkeys([*association_blockers, *_visibility_issues(quality),
                                  *(["usable"] if quality.get("usable") is False else [])]))
    primary = {}
    parts = {}
    for region in (*REQUIRED, "Tail"):
        confidence = _confidence(presence.get(region)) if model2_available else None
        confidence = confidence if confidence else None
        detected = confidence is not None and confidence >= threshold
        primary[region] = {"detected": detected, "confidence": confidence,
                           "status": "unavailable" if not model2_available else "detected" if detected else "below_threshold" if confidence else "not_detected",
                           "fish_id": fish_id, "frame_id": frame_id,
                           "association_valid": not association_blockers and model2_available}
        if region == "Tail":
            continue
        parts[region] = {"state": "PRESENT" if detected else "UNCERTAIN", "source": "model2" if detected else "silhouette_geometry",
                         "confidence": confidence if detected else None,
                         "reason": "Model 2 detected this region." if detected else "A missing detection does not prove missing anatomy."}
    missing = [region for region in REQUIRED if not primary[region]["detected"]]
    result = {"version": VERSION, "fish_id": fish_id, "frame_id": frame_id,
              "activated": bool(missing) and model2_available, "primary": primary, "parts": parts,
              "undetected_regions": missing, "missing_regions": [], "geometry": {}, "automatic_rejection": False, "rejection_reason": None,
              "review_reason": None, "uncertainty_causes": [],
              "status": "PRESENT", "reason": "Model 2 detected both required anatomical regions; continue normal grading."}
    if not model2_available:
        result.update(status="UNAVAILABLE", reason="Model 2 is unavailable; secondary verification requires a completed primary detection attempt.")
        result.update(review_reason=result["reason"], uncertainty_causes=["model2_unavailable"])
        return result
    if not missing:
        if association_blockers:
            reason = "Head/Body detections are not reliably associated with this fish and frame: " + ", ".join(dict.fromkeys(association_blockers)) + "."
            result.update(status="UNCERTAIN", reason=reason, review_reason=reason,
                          uncertainty_causes=list(dict.fromkeys(association_blockers)))
            for part in parts.values():
                part.update(state="UNCERTAIN", reason=reason)
        return result
    result["geometry"] = dict(geometry or {})
    result["uncertainty_causes"] = list(blockers)
    if isinstance(geometry, Mapping):
        result["uncertainty_causes"].extend(str(cause) for cause in geometry.get("blockers", []) if isinstance(cause, str))
    records = evidence if isinstance(evidence, (list, tuple)) else ()
    for region in missing:
        verified = []
        for row in records:
            if (not isinstance(row, Mapping) or row.get("region") != region
                    or not source_matches(row, fish_id=fish_id, frame_id=frame_id, source=source)
                    or row.get("source") != "expert_review"
                    or not isinstance(row.get("state"), str)
                    or row.get("state") not in {"present", "confirmed_absent"}
                    or not all(row.get(k) is True for k in ("reviewed", "ownership_validated", "visibility_validated"))
                    or not all(isinstance(row.get(k), str) and row[k].strip() for k in ("reviewer", "review_id"))
                    or ("confidence" in row and (_confidence(row["confidence"]) is None
                                                or _confidence(row["confidence"]) < MINIMUM_REVIEW_CONFIDENCE))
                    or _visibility_issues(row, strict=True)):
                continue
            verified.append(row)
        states = {row["state"] for row in verified}
        if blockers or len(states) != 1:
            result["uncertainty_causes"].append(f"{region.lower()}_conflicting_independent_evidence" if len(states) > 1
                                                else f"{region.lower()}_unverified_detection_failure")
            parts[region]["reason"] = ("Verification blocked: " + ", ".join(blockers) if blockers else
                                        "Independent anatomical evidence conflicts." if len(states) > 1 else
                                        (geometry or {}).get("reason", "No independently validated anatomy evidence is available."))
            continue
        state = "MISSING" if next(iter(states)) == "confirmed_absent" else "PRESENT"
        confidences = [_confidence(row.get("confidence")) for row in verified]
        parts[region] = {"state": state, "source": "reviewed_anatomy",
                         "confidence": min(confidences) if all(v is not None for v in confidences) else None,
                         "reason": f"Independent review confirms {region} is {'physically absent' if state == 'MISSING' else 'present'} in this fish and frame.",
                         "evidence": [dict(row) for row in verified]}
    absent = [region for region in REQUIRED if parts[region]["state"] == "MISSING"]
    uncertain = [region for region in REQUIRED if parts[region]["state"] == "UNCERTAIN"]
    if absent:
        result.update(status="MISSING", automatic_rejection=True, missing_regions=absent,
                      rejection_reason="Confirmed physically missing " + " and ".join(absent) + ".",
                      reason="Independent anatomical absence overrides quality grading.")
    elif uncertain:
        result.update(status="UNCERTAIN", reason="Cannot confidently verify " + " and ".join(uncertain) + "; review is required.")
        result["review_reason"] = result["reason"] + " " + " ".join(parts[region]["reason"] for region in uncertain)
    else:
        result.update(reason="Secondary evidence confirms the required anatomy is present; continue the unchanged quality grading gates.")
    result["uncertainty_causes"] = list(dict.fromkeys(result["uncertainty_causes"])) if uncertain else []
    return result


def apply_anatomical_gate(decision, report):
    """Separate physical absence/uncertainty from unchanged quality scores."""
    if report.get("automatic_rejection") is True and report.get("status") == "MISSING":
        absent = [region for region in REQUIRED if report["parts"][region]["state"] == "MISSING"]
        return replace(decision, final_grade="Rejected", final_support=None,
                       reason_codes=tuple("RJ_CONFIRMED_MISSING_" + region.upper() for region in absent),
                       override={"source": "secondary_anatomical_verification", "reason": report["rejection_reason"],
                                 "regions": absent, "quality_scores_unchanged": True,
                                 "confidence_kind": "independent_anatomical_evidence_not_quality_support"})
    if report.get("status") == "UNCERTAIN":
        reasons = tuple(code for code in decision.reason_codes if code.startswith("UG_"))
        return replace(decision, final_grade=None, final_support=None,
                       reason_codes=tuple(dict.fromkeys((*reasons, "UG_ANATOMY_UNCERTAIN"))), override=None)
    return decision
