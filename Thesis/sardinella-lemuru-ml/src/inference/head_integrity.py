"""Decide whether a fish is physically headless from visible evidence.

A missing Model 2 Head detection is not absence. Rejection uses a separate
Head-integrity pathway: a MobileSAM candidate that passes geometry, isolation,
clipping, and neighbor checks, a Body silhouette, one wide severed end opposite
a narrow posterior end, and no Head tissue on that fish. Overlap, occlusion,
and frame truncation stay unrejected.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from src.inference.anatomical_measurements import _binary, _region_pixels, _selected, measure_mask_anatomy
from src.inference.fish_geometry import FishGeometryConfig
from src.inference.head_silhouette import HeadSilhouetteConfig
from src.inference.mask_ownership import head_integrity_mask_eligibility


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def mobilesam_ownership_gap(metadata: Mapping[str, Any] | None, *, geometric_body_supported: bool = False,
                            independent_head_endpoint: bool = False) -> tuple[str | None, dict[str, Any]]:
    """Return why a mask cannot prove a missing Head, plus the separate eligibility record.

    Engineering checks may fail only because no Head was detected. That failure
    is not reused here. Eligibility is the Head-integrity pathway.
    """

    record = _mapping(metadata)
    source = str(record.get("source", ""))
    provenance = _mapping(record.get("candidate_provenance"))
    backend = record.get("backend") or provenance.get("backend")
    supplied = record.get("head_integrity_eligibility")
    # An eligibility summary cannot waive a conflicting native ownership record.
    # Recompute from the checks whenever the underlying evidence is available.
    ownership = record.get("ownership")
    eligibility = head_integrity_mask_eligibility(ownership if isinstance(ownership, Mapping) else None,
        geometric_body_supported=geometric_body_supported, independent_head_endpoint=independent_head_endpoint)
    waivable = {"required_body_evidence_unavailable"}
    if eligibility.get("body_ambiguity_separate_from_head_integrity") is True:
        waivable.add("required_anatomical_ownership_ambiguous")
    supplied_blockers = set(supplied.get("blocking_reasons") or []) if isinstance(supplied, Mapping) else set()
    body_only_withheld = (geometric_body_supported and isinstance(supplied, Mapping)
                         and bool(supplied_blockers) and supplied_blockers.issubset(waivable))
    if isinstance(supplied, Mapping) and supplied.get("eligible") is not True and not body_only_withheld:
        eligibility = {**eligibility, "eligible": False,
                       "withheld_category": supplied.get("withheld_category") or "ownership_checks_failed",
                       "blocking_reasons": sorted(set(eligibility.get("blocking_reasons", ()))
                                                  | set(supplied.get("blocking_reasons", ())))}
    if backend != "mobilesam_experimental" and "mobilesam" not in source and provenance.get("source") != "mobilesam_box_prompt_candidate":
        eligibility = {**eligibility, "eligible": False, "withheld_category": "mask_not_mobilesam"}
        return "mask_not_mobilesam", eligibility
    if eligibility.get("eligible") is True:
        return None, eligibility
    return str(eligibility.get("withheld_category") or "ownership_checks_failed"), eligibility


def _crop_meets_image_frame(metadata: Mapping[str, Any] | None) -> bool | None:
    """True when this crop touches the image. None when the crop is unknown."""

    record = _mapping(metadata)
    bounds = record.get("crop_bounds")
    shape = record.get("native_frame_shape")
    try:
        x1, y1, x2, y2 = (int(value) for value in bounds)
        height, width = int(shape[0]), int(shape[1])
    except (TypeError, ValueError, IndexError):
        return None
    if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
        return None
    return x1 <= 0 or y1 <= 0 or x2 >= width or y2 >= height


def _head_intersects(mask: np.ndarray, parts: Sequence[Any], minimum_confidence: float) -> bool:
    binary = _binary(mask)
    if binary is None:
        return False
    for part in _selected(parts, "Head", minimum_confidence):
        pixels = _region_pixels(part, binary.shape, binary)
        if pixels is not None and int(pixels.sum()) > 0:
            return True
    return False


def assess_head_integrity(
    mask: np.ndarray | None,
    parts: Sequence[Any] = (),
    *,
    other_heads: Sequence[Any] = (),
    unassigned_heads: Sequence[Any] = (),
    mask_metadata: Mapping[str, Any] | None = None,
    model2_available: bool = True,
    model2_failed: bool = False,
    overlapping: bool = False,
    clipped: bool = False,
    association_reliable: bool = True,
    config: FishGeometryConfig | None = None,
    head_config: HeadSilhouetteConfig | None = None,
    minimum_part_confidence: float = 0.25,
    minimum_candidate_head_confidence: float | None = None,
    native_instance_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify Head presence without treating a detector miss as headless."""

    settings = config or FishGeometryConfig()
    candidate_head_threshold = max(minimum_part_confidence, minimum_candidate_head_confidence
                                   if minimum_candidate_head_confidence is not None else minimum_part_confidence)
    measurements = measure_mask_anatomy(
        mask, parts, config=settings, head_config=head_config, minimum_part_confidence=minimum_part_confidence,
    )
    from src.inference.head_body_support import measure_silhouette_torso_support
    torso = (measure_silhouette_torso_support(mask, measurements, parts=parts, config=settings, head_config=head_config)
             if int(measurements.get("body_pixels") or 0) <= 0 else
             {"eligible": False, "source": "not_needed", "reasons": ["owned_model2_body_available"]})
    endpoint = {"verified": False, "clear": False, "reasons": ["native_instance_context_unavailable"]}
    if isinstance(native_instance_context, Mapping):
        try:
            from src.inference.head_endpoint_ownership import inspect_head_endpoint_ownership
            endpoint = inspect_head_endpoint_ownership(
                native_instance_context["candidates"], native_instance_context["ownership"],
                native_instance_context["parents"], native_instance_context["parent_id"], measurements,
                expected_frame_key=native_instance_context["frame_key"],
                frame_shape=native_instance_context["frame_shape"], config=settings, head_config=head_config)
        except Exception as error:
            endpoint = {"verified": False, "clear": False, "reasons": ["head_endpoint_ownership_processing_failed"],
                        "error_type": type(error).__name__}
    independent_endpoint = endpoint.get("verified") is True and endpoint.get("clear") is True
    ownership_gap, eligibility = mobilesam_ownership_gap(mask_metadata,
        geometric_body_supported=torso.get("eligible") is True, independent_head_endpoint=independent_endpoint)
    metadata = _mapping(mask_metadata)
    crop_meets_frame = _crop_meets_image_frame(mask_metadata)
    if crop_meets_frame is False and "silhouette_touches_frame_boundary" in measurements["reasons"]:
        measurements["reasons"] = [
            reason for reason in measurements["reasons"] if reason != "silhouette_touches_frame_boundary"
        ]
        measurements["reasons"].append("silhouette_meets_parent_crop_edge")
    if ownership_gap == "mask_not_mobilesam":
        # GrabCut or an unknown mask must not be reported as a MobileSAM measurement.
        for field in (
            "anatomical_length_px", "max_body_width_px", "width_to_length_ratio",
            "head_to_body_size_ratio", "orientation_degrees", "anterior_extension_px",
            "centerline_px", "cross_section_profile", "terminal_width_ratio", "terminal_width_ratios",
            "truncation_evidence", "body_taper", "orientation_confidence",
        ):
            measurements[field] = None
        measurements.update(status="unavailable", supporting_evidence=False)
        torso.update(eligible=False, reasons=[*torso.get("reasons", []), "mask_not_mobilesam"])
        measurements["reasons"] = list(dict.fromkeys([*measurements["reasons"], "mask_not_mobilesam"]))
    report: dict[str, Any] = {
        "classification": "unavailable",
        "grade_effect": "none",
        "summary": "Head integrity was not assessed.",
        "evidence": list(measurements["reasons"]),
        "measurements": measurements,
        "used_for_grading": False,
        "reliable_ownership": eligibility.get("eligible") is True,
        "ownership_gap": ownership_gap,
        "mask_eligibility": eligibility,
        "orientation_degrees": measurements.get("orientation_degrees"),
        "posterior_source": measurements.get("posterior_source"),
        "cut_end_confirmed": measurements.get("cut_end_confirmed") is True,
        "cut_end_axis": measurements.get("cut_end_axis"),
        "cut_character": measurements.get("cut_character"),
        "geometry_decision": measurements.get("geometry_decision"),
        "orientation_reliable": measurements.get("orientation_reliable") is True,
        "representative_body_width_px": measurements.get("representative_body_width_px"),
        "width_profile_ratio": (measurements.get("cut_end_metrics") or {}).get("width_profile_ratio"),
        "end_geometry": (measurements.get("cut_end_metrics") or {}).get("ends"),
        "cut_end_metrics": measurements.get("cut_end_metrics"),
        "withheld_reasons": list(eligibility.get("blocking_reasons") or []),
        "model2_available": model2_available is True and model2_failed is not True,
        "prior_grade": None,
        "head_endpoint_ownership": endpoint,
        "body_association_status": {
            "ambiguous_regions": list(eligibility.get("ambiguous_anatomical_regions") or []),
            "preserved_for_quality_grading": "AMBIGUOUS" if eligibility.get("body_ambiguity_scope_verified") else None,
            "separate_from_head_integrity": eligibility.get("body_ambiguity_separate_from_head_integrity") is True,
            "detector_body_assignment_created": False,
        },
        "body_support": {"source": "owned_model2_body_roi" if int(measurements.get("body_pixels") or 0) > 0 else torso.get("source"),
                         "model2_body_pixels": int(measurements.get("body_pixels") or 0),
                         "geometric_torso": torso,
                         "used_instead_of_missing_body_detection": torso.get("eligible") is True},
        "diagnostic_version": "head_integrity_v2",
        "ownership_checks": _mapping(metadata.get("ownership")),
        "source_context_reasons": list(metadata.get("context_reliability_reasons") or []),
        "orientation_confidence": measurements.get("orientation_confidence"),
        "terminal_width_ratio": measurements.get("terminal_width_ratio"),
        "terminal_width_ratios": measurements.get("terminal_width_ratios"),
        "truncation_evidence": measurements.get("truncation_evidence"),
        "body_taper": measurements.get("body_taper"),
        "anterior_extension_px": measurements.get("anterior_extension_px"),
        "anterior_extension_length_ratio": measurements.get("anterior_extension_length_ratio"),
        "orientation_confidence_interpretation": "Geometric consistency, not a calibrated probability.",
        "head_detection_status": {
            "accepted_count": len(_selected(parts, "Head", minimum_part_confidence)),
            "owned_silhouette_pixels": int(measurements.get("head_pixels") or 0),
            "owned_head_intersects": _head_intersects(mask, parts, minimum_part_confidence),
            "foreign_head_intersects": _head_intersects(mask, other_heads, candidate_head_threshold),
            "unassigned_head_intersects": _head_intersects(mask, unassigned_heads, candidate_head_threshold),
            "candidate_evidence_threshold": candidate_head_threshold,
            "diagnostic_only_head_intersects": _head_intersects(mask, [
                part for part in [*other_heads, *unassigned_heads]
                if part not in _selected([part], "Head", candidate_head_threshold)
            ], 0.0),
            "diagnostic_candidates_affect_grading": False,
            "missing_detection_proves_absence": False,
        },
    }

    # Evaluate every gate before the first return so an early overlap veto does
    # not hide clipping, orientation, or detector failures on the same fish.
    blocking = set(eligibility.get("blocking_reasons") or [])
    frame_contact = clipped or metadata.get("explicit_native_clipping") is True or eligibility.get("native_frame_clipped") is True or eligibility.get("withheld_category") == "frame_clipped" or (
        "silhouette_touches_frame_boundary" in measurements["reasons"] and crop_meets_frame is not False
    )
    fragmented = (eligibility.get("withheld_category") == "occluded_or_fragmented"
                  or bool(blocking & {"fragmented_or_merged_foreground_components", "implausible_silhouette_holes"})
                  or "multiple_foreground_components" in measurements["reasons"])
    contaminated = (eligibility.get("withheld_category") == "overlap_or_contamination"
                    or bool(eligibility.get("ownership_conflicts"))
                    or bool(blocking & {"foreground_in_neighbor_exclusive_region",
                                       "candidate_contains_neighbor_anatomical_evidence",
                                       "overlapping_mask_ownership_conflict"}))
    crop_truncated = eligibility.get("analysis_crop_truncated") is True or eligibility.get("withheld_category") == "analysis_crop_truncated"
    polarity_conflicts = [reason for reason in measurements["reasons"] if reason in {
        "tail_body_polarity_uncertain", "tail_reaches_anterior_tip", "tail_cut_polarity_conflict",
        "tail_not_on_silhouette", "multiple_tail_associations",
    }]
    if (measurements.get("tail_anterior_end") and measurements.get("cut_end_axis")
            and measurements["tail_anterior_end"] != measurements["cut_end_axis"]):
        polarity_conflicts.append("tail_cut_polarity_conflict")
    centerline = measurements.get("centerline_quality") or {}
    geometry_failures = [name for name, limit in (
        ("centerline_tortuosity", settings.maximum_centerline_tortuosity),
        ("longitudinal_gap_fraction", settings.maximum_hole_fraction),
    ) if centerline.get(name, 0) > limit]
    # Tip displacement and residuals remain diagnostic: a valid slanted cut
    # naturally moves its terminal center away from the central body axis.
    checks = [
        ("model2_available", report["model2_available"], "model2_unavailable"),
        ("usable_silhouette", measurements["status"] == "measured", "silhouette_unusable"),
        ("source_context", not report["source_context_reasons"] and metadata.get("stale_source_frame") is not True,
         "unreliable_source_context"),
        ("mask_ownership", eligibility.get("eligible") is True, ownership_gap or "mask_not_eligible"),
        ("no_mask_contamination", not contaminated, "overlapping_fish"),
        ("native_frame_complete", not frame_contact, "head_may_be_outside_frame"),
        ("analysis_crop_complete", not crop_truncated,
         "analysis_crop_truncates_silhouette"),
        ("no_occlusion_evidence", not fragmented, "partial_occlusion"),
        ("part_association", association_reliable, "association_uncertain"),
        ("independent_head_endpoint", not eligibility.get("body_ambiguity_scope_verified") or independent_endpoint,
         "head_endpoint_not_independently_clear"),
        ("no_foreign_head", not report["head_detection_status"]["foreign_head_intersects"], "foreign_head_overlap"),
        ("no_unassigned_head", not report["head_detection_status"]["unassigned_head_intersects"],
         "unassigned_head_overlaps_silhouette"),
        ("no_owned_head", report["head_detection_status"]["accepted_count"] == 0, "owned_head_evidence_present"),
        ("body_evidence", int(measurements.get("body_pixels") or 0) > 0 or torso.get("eligible") is True, "body_silhouette_missing"),
        ("anterior_truncation", measurements.get("cut_end_confirmed") is True, "severed_end_not_confirmed"),
        ("orientation", measurements.get("orientation_reliable") is True
         and "multiple_body_associations" not in measurements["reasons"], "orientation_ambiguous"),
        ("centerline_geometry", not geometry_failures, "unreliable_centerline_geometry"),
        ("tail_polarity", not polarity_conflicts, "tail_landmark_contradicts_orientation"),
    ]
    report["rejection_gates"] = [
        {"gate": gate, "passed": bool(passed), "reason": "passed" if passed else reason}
        for gate, passed, reason in checks
    ]
    report["failed_rejection_gates"] = [gate for gate in report["rejection_gates"] if not gate["passed"]]
    report["polarity_conflicts"] = list(dict.fromkeys(polarity_conflicts))
    report["geometry_quality_failures"] = geometry_failures
    report["clipping_checks"] = {
        "native_frame_contact": bool(frame_contact), "crop_meets_image_frame": crop_meets_frame,
        "analysis_crop_truncated": crop_truncated,
        "crop_foreground_retained_fraction": _mapping(metadata.get("analysis_crop_retention")).get("retained_foreground_fraction"),
    }

    def finish(classification: str, effect: str, summary: str, *evidence: str) -> dict[str, Any]:
        report.update(classification=classification, grade_effect=effect, summary=summary)
        report["decision_reason"] = evidence[0] if evidence else classification
        report["evidence"] = list(dict.fromkeys([*report["evidence"], *evidence]))
        report["used_for_grading"] = effect == "reject"
        measurements["used_for_grading"] = effect == "reject"
        if effect == "reject" and measurements.get("body_pixels"):
            measurements["head_to_body_size_ratio"] = 0.0
            measurements["head_to_body_size_ratio_basis"] = "No exclusive Head pixels on the owned silhouette; Body pixels were measured."
        return report

    if model2_available is not True or model2_failed is True:
        return finish(
            "unverified_model2", "none",
            "Model 2 did not produce a usable Head inspection. A failed or missing detector run is not treated as a headless fish.",
            "model2_unavailable",
        )
    if measurements["status"] != "measured":
        return finish(
            "unavailable", "none",
            "No usable silhouette was available, so Head absence was not inferred.",
            "silhouette_unusable",
        )
    if report["source_context_reasons"] or metadata.get("stale_source_frame") is True:
        return finish(
            "unverified_source", "none",
            "The source frame, parent detection, or crop is unreliable. Head removal was not inferred.",
            "unreliable_source_context",
        )
    if contaminated:
        return finish(
            "ungraded_overlapping", "none",
            "The silhouette is contaminated by another fish, so a hidden Head cannot be rejected. The existing grade is not replaced.",
            "overlapping_fish",
        )
    if overlapping and eligibility.get("eligible") is True:
        report["evidence"].append("detector_boxes_overlap_without_mask_contamination")
    if frame_contact:
        return finish(
            "ungraded_out_of_frame", "none",
            "The fish meets the image boundary, so a Head outside the frame is not rejected. The existing grade is not replaced.",
            "head_may_be_outside_frame",
        )
    if crop_truncated:
        return finish(
            "unverified_crop_truncation", "none",
            "The analysis crop excludes native silhouette pixels. Its artificial edge cannot establish a severed Head.",
            "analysis_crop_truncates_silhouette",
        )
    if fragmented:
        return finish(
            "ungraded_occluded", "none",
            "The silhouette is fragmented, which is consistent with occlusion. The fish is not rejected.",
            "partial_occlusion",
        )
    if eligibility.get("body_ambiguity_scope_verified") and not independent_endpoint:
        return finish(
            "unverified_endpoint_ownership", "none",
            "Body detection ownership is unresolved, and the Head-side endpoint is not independently clear of neighboring fish. Head removal was not inferred.",
            "head_endpoint_not_independently_clear",
        )
    if not association_reliable:
        return finish(
            "unverified_ownership", "none",
            "Part ownership is not reliable, so another fish's Head cannot be separated from this fish. No headless rejection was applied.",
            "association_uncertain",
        )
    if ownership_gap == "ownership_conflict" or report["head_detection_status"]["foreign_head_intersects"]:
        return finish(
            "unverified_ownership", "none",
            "A Head belonging to another detection overlaps this fish. It was not used as this fish's Head and was not treated as absence.",
            "foreign_head_overlap",
        )
    if report["head_detection_status"]["unassigned_head_intersects"]:
        return finish(
            "unverified_nondetection", "none",
            "Model 2 saw Head evidence on this fish that was not accepted as an owned Head. That miss is not physical absence.",
            "unassigned_head_overlaps_silhouette",
        )
    owned_head_pixels = int(measurements.get("head_pixels") or 0)
    if report["head_detection_status"]["accepted_count"] > 0 and owned_head_pixels == 0:
        return finish(
            "unverified_nondetection", "none",
            "Accepted Head evidence cannot be verified as one independent silhouette region. Head removal was not inferred.",
            "owned_head_evidence_not_separable",
        )
    if owned_head_pixels > 0 and measurements.get("head_to_body_size_ratio") is not None:
        return finish(
            "present", "none",
            "An owned Head is on this silhouette. Head-to-Body size is supporting evidence and does not replace Model 2 grades.",
            "owned_head_on_silhouette",
        )
    if owned_head_pixels > 0:
        return finish(
            "ungraded_occluded", "none",
            "Head pixels meet the silhouette but are not separable from the Body or are only partly visible. The fish is not rejected.",
            "partial_head_visibility",
        )
    if int(measurements.get("body_pixels") or 0) <= 0 and torso.get("eligible") is not True:
        return finish(
            "unverified_nondetection", "none",
            "Model 2 did not assign a Head, and the Body silhouette is not available. That is not physical Head removal.",
            "body_silhouette_missing",
        )
    if eligibility.get("eligible") is not True:
        return finish(
            "unverified_nondetection", "none",
            "The MobileSAM candidate is not eligible for Head-absence review. A missing Head detection was not treated as removal.",
            ownership_gap or "mask_not_eligible",
        )
    geometry_decision = measurements.get("geometry_decision")
    if geometry_decision == "severed_tail":
        return finish(
            "unverified_nondetection", "none",
            "One end is severed and the other has snout geometry. That is a damaged or missing Tail, not a missing Head.",
            "tail_damage_not_head_absence",
        )
    cut_axis = measurements.get("cut_end_axis")
    tail_axis = measurements.get("tail_anterior_end")
    if tail_axis and cut_axis and tail_axis != cut_axis:
        return finish(
            "unverified_nondetection", "none",
            "The Tail landmark sits on the severed end, so this is not classified as a missing Head.",
            "tail_damage_not_head_absence",
        )
    if measurements.get("cut_end_confirmed") is not True:
        return finish(
            "unverified_nondetection", "none",
            "Model 2 did not assign a Head, and the silhouette does not show one severed anterior end opposite a posterior end. Absence was not inferred.",
            "severed_end_not_confirmed" if measurements.get("posterior_source") else "posterior_end_ambiguous",
        )
    if measurements.get("orientation_reliable") is not True or "multiple_body_associations" in measurements["reasons"]:
        return finish(
            "unverified_nondetection", "none",
            "Anatomical orientation is ambiguous, so the fish was not rejected for a missing Head.",
            "orientation_ambiguous",
        )
    if polarity_conflicts:
        return finish(
            "unverified_nondetection", "none",
            "The Tail landmark does not establish a consistent posterior end. Head removal was not inferred.",
            "tail_landmark_contradicts_orientation", *polarity_conflicts,
        )
    if geometry_failures:
        return finish(
            "unverified_geometry", "none",
            "The silhouette centerline is bent, discontinuous, or unreliable for terminal anatomy. Head removal was not inferred.",
            "unreliable_centerline_geometry", *geometry_failures,
        )
    character = measurements.get("cut_character") or "severed"
    return finish(
        "confirmed_absent", "reject",
        f"The Head is physically absent. The eligible silhouette has a {character} severed anterior end, a posterior end, Body tissue, and no Head detection on this fish.",
        "severed_end_confirmed", f"{character}_cut_surface", "no_owned_or_neighbor_head",
        "posterior_from_tail" if tail_axis else "posterior_from_silhouette",
    )


def apply_head_integrity(
    analysis: dict[str, Any],
    published_grade: str | None,
    report: Mapping[str, Any],
) -> str | None:
    """Record measurements and apply only a confirmed-absence or visibility hold."""

    payload = dict(report)
    measurements = dict(payload.get("measurements") or {})
    payload["measurements"] = measurements
    analysis["anatomical_measurements"] = measurements
    analysis["head_integrity"] = payload
    effect = payload.get("grade_effect")
    prior = analysis.get("final_grade") or published_grade or "Ungraded"
    payload["prior_grade"] = prior
    payload["quality_grading_before_integrity"] = {
        "grade": prior, "reason_codes": list(analysis.get("reason_codes") or []),
        "verdict_reason_code": analysis.get("verdict_reason_code"),
        "verdict_reason_text": analysis.get("verdict_reason_text"),
        "final_score": analysis.get("final_score"), "final_support": analysis.get("final_support"),
    }
    if effect not in {"reject", "withhold"}:
        if measurements.get("supporting_evidence"):
            length = measurements.get("anatomical_length_px")
            width = measurements.get("max_body_width_px")
            ratio = measurements.get("width_to_length_ratio")
            head_ratio = measurements.get("head_to_body_size_ratio")
            analysis.setdefault("explanation", [])
            if isinstance(analysis["explanation"], list):
                analysis["explanation"].append(
                    "MobileSAM supporting measurements: "
                    f"length {length} px, maximum Body width {width} px, "
                    f"width-to-length {ratio}, Head-to-Body size {head_ratio if head_ratio is not None else 'unavailable'}. "
                    "These measurements do not replace Model 2 grade weights."
                )
        return published_grade
    override = analysis.get("override") if isinstance(analysis.get("override"), dict) else None
    model2_rejection = prior == "Rejected" and isinstance(override, dict) and override.get("source") == "Model 2 trained Rejected_* part label"
    if effect == "withhold" and model2_rejection:
        payload["grade_effect"] = "preserved_model2_rejection"
        payload["summary"] = payload["summary"] + " The existing Model 2 Rejected label was kept."
        return published_grade
    grade = "Rejected" if effect == "reject" else "Ungraded"
    analysis["final_grade"] = grade
    analysis["ai_final_grade"] = grade
    # Weighted support for the former grade is not confidence in an anatomical
    # rejection. Preserve it above without inventing a geometry probability.
    analysis["final_score"] = None
    analysis["final_support"] = None
    payload["confidence_basis"] = "Anatomical gates passed; no calibrated probability is available."
    analysis["verdict_status"] = "AUTO_GRADED" if grade == "Rejected" else "NEEDS_REVIEW"
    code = "RJ_CONFIRMED_HEAD_ABSENCE" if grade == "Rejected" else "UG_HEAD_NOT_VISIBLE"
    analysis["verdict_reason_code"] = code
    analysis["reason_codes"] = [code]
    analysis["verdict_reason_text"] = payload["summary"]
    analysis["override"] = {
        "applied": True,
        "source": "confirmed_physical_head_absence" if grade == "Rejected" else "head_visibility_withheld",
        "prior_grade": prior,
        "classification": payload.get("classification"),
        "evidence": list(payload.get("evidence") or []),
    }
    fusion = analysis.get("feature_fusion")
    if isinstance(fusion, dict):
        fusion["final_grade"] = grade
        fusion["final_support"] = None
        fusion["head_integrity_changed_classification"] = grade != prior
        contributions = list(fusion.get("contributions_applied") or [])
        contributions.append("head_integrity")
        fusion["contributions_applied"] = contributions
    explanation = list(analysis.get("explanation") or [])
    explanation.append(str(payload["summary"]))
    analysis["explanation"] = explanation
    return grade
