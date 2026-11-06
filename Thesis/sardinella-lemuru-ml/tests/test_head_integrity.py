"""Headless rejection uses visible MobileSAM structure, not a missed Head box."""

import cv2
import numpy as np
import pytest

from src.inference.head_integrity import apply_head_integrity, assess_head_integrity
from src.inference.part_types import PartDetection


def _rotate(image, angle):
    center = ((image.shape[1] - 1) / 2.0, (image.shape[0] - 1) / 2.0)
    transform = cv2.getRotationMatrix2D(center, -angle, 1.0)
    return cv2.warpAffine(image, transform, (image.shape[1], image.shape[0]), flags=cv2.INTER_NEAREST)


def _box(mask):
    ys, xs = np.nonzero(mask)
    return (float(xs.min()) - 1.0, float(ys.min()) - 1.0, float(xs.max()) + 2.0, float(ys.max()) + 2.0)


def specimen(angle=0, *, head=False, touch_border=False):
    canvas = np.zeros((280, 280), np.uint8)
    body = np.zeros_like(canvas)
    tail = np.zeros_like(canvas)
    head_mask = np.zeros_like(canvas)
    cv2.rectangle(body, (70, 115), (190, 165), 1, -1)
    cv2.fillPoly(tail, [np.array([(190, 120), (250, 140), (190, 160)], np.int32)], 1)
    if head:
        snout = np.array([(70, 140), (40, 128), (28, 140), (40, 152)], np.int32)
        cv2.fillPoly(head_mask, [snout], 1)
        cv2.circle(head_mask, (78, 140), 16, 1, -1)
    fish = np.clip(body + tail + head_mask, 0, 1)
    parts = [
        PartDetection.from_source_class(0, 0.95, _box(body)),
        PartDetection.from_source_class(2, 0.92, _box(tail)),
    ]
    if head:
        parts.append(PartDetection.from_source_class(1, 0.93, _box(head_mask)))
    if angle:
        fish = _rotate(fish, angle)
        parts = [PartDetection.from_source_class(part.source_class_id, part.confidence, _rotated_box(part.bbox, angle, canvas.shape)) for part in parts]
    if touch_border:
        fish[0:116, 118:122] = 1
    return fish, parts


def _rotated_box(box, angle, shape):
    center = ((shape[1] - 1) / 2.0, (shape[0] - 1) / 2.0)
    transform = cv2.getRotationMatrix2D(center, -angle, 1.0)
    corners = np.array(((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])), dtype=np.float64)
    moved = corners @ transform[:, :2].T + transform[:, 2]
    return (float(moved[:, 0].min()), float(moved[:, 1].min()), float(moved[:, 0].max()), float(moved[:, 1].max()))


def ownership(**extra):
    payload = {
        "backend": "mobilesam_experimental",
        "source": "mobilesam_experimental_candidate",
        "ownership": {
            "mask_geometry_checks_passed": True,
            "engineering_checks_passed": False,
            "conflicting_parent_ids": [],
            "reasons": ["required_head_evidence_unavailable"],
        },
        "parent_isolation_reliable": False,
    }
    payload.update(extra)
    return payload


def assess(mask, parts, **kwargs):
    values = dict(mask_metadata=ownership(), model2_available=True, association_reliable=True)
    values.update(kwargs)
    return assess_head_integrity(mask, parts, **values)


@pytest.mark.parametrize("angle", (0, 90, 45))
def test_orientation_preserves_length_width_and_ratio(angle):
    mask, parts = specimen(angle, head=True)
    report = assess(mask, parts)
    measured = report["measurements"]
    assert report["classification"] == "present"
    assert report["grade_effect"] == "none"
    assert measured["anatomical_length_px"] == pytest.approx(223, abs=16)
    assert measured["max_body_width_px"] == pytest.approx(51, abs=8)
    assert measured["width_to_length_ratio"] == pytest.approx(
        measured["max_body_width_px"] / measured["anatomical_length_px"], abs=0.001,
    )
    assert measured["head_to_body_size_ratio"] > 0.05
    difference = abs(measured["orientation_degrees"] - (angle % 180))
    assert min(difference, 180 - difference) < 8


def test_missing_tail_detection_can_use_a_blunt_cut_and_narrow_posterior_end():
    mask, parts = specimen()
    parts = [part for part in parts if part.region != "Tail"]
    report = assess(mask, parts)
    assert report["classification"] == "confirmed_absent", report["cut_end_metrics"]
    assert report["posterior_source"] == "silhouette_morphology"
    assert report["mask_eligibility"]["eligible"] is True
    assert report["mask_eligibility"]["engineering_checks_passed"] is False
    assert report["reliable_ownership"] is True


def test_rectangle_without_a_narrow_end_is_not_called_headless():
    mask = np.zeros((280, 280), np.uint8)
    cv2.rectangle(mask, (60, 110), (220, 160), 1, -1)
    body = PartDetection.from_source_class(0, 0.95, (60, 110, 220, 160))
    report = assess(mask, [body])
    assert report["classification"] == "unverified_nondetection"
    assert report["cut_end_confirmed"] is False


def test_visible_snout_is_not_a_severed_end():
    mask, parts = specimen(head=True)
    parts = [part for part in parts if part.region != "Head"]
    report = assess(mask, parts)
    assert report["classification"] == "unverified_nondetection"
    assert report["grade_effect"] == "none"


def test_clear_headless_fish_is_rejected_from_mask_geometry():
    mask, parts = specimen()
    report = assess(mask, parts)
    assert report["classification"] == "confirmed_absent", report
    assert report["grade_effect"] == "reject"
    assert report["measurements"]["head_to_body_size_ratio"] == 0.0
    assert report["used_for_grading"] is True
    analysis = {"final_grade": "Class A", "feature_fusion": {"schema_version": "feature_fusion_v1", "final_grade": "Class A"}, "explanation": []}
    grade = apply_head_integrity(analysis, "Class A", report)
    assert grade == "Rejected"
    assert analysis["final_grade"] == "Rejected"
    assert analysis["feature_fusion"]["final_grade"] == "Rejected"
    assert analysis["override"]["source"] == "confirmed_physical_head_absence"
    assert analysis["head_integrity"]["prior_grade"] == "Class A"


def test_model2_failure_does_not_invent_a_headless_rejection():
    mask, parts = specimen()
    report = assess(mask, parts, model2_available=False)
    assert report["classification"] == "unverified_model2"
    assert report["grade_effect"] == "none"
    assert report["measurements"]["head_to_body_size_ratio"] is None


def test_anterior_tissue_without_a_head_label_is_not_absence():
    mask, parts = specimen(head=True)
    parts = [part for part in parts if part.region != "Head"]
    report = assess(mask, parts)
    assert report["classification"] == "unverified_nondetection"
    assert report["grade_effect"] == "none"


def test_overlap_occlusion_and_frame_exit_are_not_rejected():
    mask, parts = specimen()
    contaminated = ownership()
    contaminated["ownership"] = {
        **contaminated["ownership"],
        "mask_geometry_checks_passed": False,
        "conflicting_parent_ids": [2],
        "reasons": ["required_head_evidence_unavailable", "overlapping_mask_ownership_conflict"],
    }
    overlap = assess(mask, parts, overlapping=True, mask_metadata=contaminated)
    assert overlap["classification"] == "ungraded_overlapping"
    assert overlap["grade_effect"] == "none"
    boxes_only = assess(mask, parts, overlapping=True)
    assert boxes_only["classification"] == "confirmed_absent"
    border, border_parts = specimen(touch_border=True)
    outside = assess(border, border_parts)
    assert outside["classification"] == "ungraded_out_of_frame"
    assert outside["grade_effect"] == "none"
    analysis = {"final_grade": "Class B", "override": None, "feature_fusion": {"schema_version": "feature_fusion_v1", "final_grade": "Class B"}}
    assert apply_head_integrity(analysis, "Class B", overlap) == "Class B"
    assert analysis["feature_fusion"]["final_grade"] == "Class B"


def test_another_fish_head_is_not_borrowed_or_called_absent():
    mask, parts = specimen()
    foreign = PartDetection.from_source_class(1, 0.9, (180, 120, 230, 165))
    report = assess(mask, parts, other_heads=[foreign])
    assert report["classification"] == "unverified_ownership"
    assert report["grade_effect"] == "none"


def test_low_confidence_head_on_the_fish_is_a_miss_not_absence():
    mask, parts = specimen(head=True)
    parts = [part for part in parts if part.region != "Head"]
    missed = PartDetection.from_source_class(1, 0.05, (186, 116, 236, 166))
    report = assess(mask, parts, unassigned_heads=[missed], minimum_part_confidence=0.25)
    assert report["classification"] == "unverified_nondetection"
    assert report["grade_effect"] == "none"


def test_grabcut_mask_cannot_confirm_head_absence():
    mask, parts = specimen()
    report = assess(mask, parts, mask_metadata={"source": "runtime_grabcut", "ownership": {}})
    assert report["classification"] == "unavailable"
    assert report["grade_effect"] == "none"
    assert report["measurements"]["anatomical_length_px"] is None
    assert "mask_not_mobilesam" in report["evidence"]


def _profile_mask(samples):
    """Paint a silhouette whose cross-section follows a recorded width profile."""

    mask = np.zeros((240, 460), np.uint8)
    columns = np.arange(30, 430)
    positions = np.linspace(columns[0], columns[-1], len(samples))
    peak = max(float(value) for value in samples) or 1.0
    fractions = np.interp(columns, positions, samples) / peak
    for column, fraction in zip(columns, fractions):
        half = max(1, int(round(float(fraction) * 36)))
        mask[120 - half:120 + half + 1, int(column)] = 1
    return mask


def test_recorded_inspection_profiles_reject_only_the_headless_ends():
    """Fish 1, 3, and 4 from the 2026-11-06 inspection; Fish 2 keeps its head."""

    profiles = {
        1: (4, 191, 260, 347, 358, 379, 392, 370, 365, 349, 320, 313, 286, 271, 247, 214, 181, 151, 158, 185, 6),
        2: (10, 183, 262, 300, 329, 351, 363, 370, 372, 365, 337, 304, 269, 248, 244, 206, 189, 143, 163, 194, 2),
        3: (4, 125, 139, 147, 167, 185, 204, 228, 235, 252, 254, 254, 262, 266, 273, 293, 297, 245, 185, 142, 7),
        4: (49, 132, 134, 141, 167, 208, 231, 246, 247, 257, 271, 273, 283, 295, 321, 332, 330, 306, 223, 145, 6),
    }
    for fish_id in (1, 3, 4):
        mask = _profile_mask(profiles[fish_id])
        body = PartDetection.from_source_class(0, 0.9, _box(mask))
        report = assess(mask, [body])
        assert report["classification"] == "confirmed_absent", (fish_id, report["cut_end_metrics"])
        assert report["grade_effect"] == "reject"
        assert report["posterior_source"] == "silhouette_morphology"
    intact = _profile_mask(profiles[2])
    body = PartDetection.from_source_class(0, 0.9, _box(intact))
    visible = assess(intact, [body])
    assert visible["classification"] == "unverified_nondetection", visible["cut_end_metrics"]
    assert visible["grade_effect"] == "none"
    clipped = assess(intact, [body], clipped=True)
    assert clipped["classification"] == "ungraded_out_of_frame"
    assert clipped["grade_effect"] == "none"


def test_parent_crop_edge_is_not_treated_as_image_clipping():
    mask, parts = specimen()
    parts = [part for part in parts if part.region != "Tail"]
    ys, xs = np.nonzero(mask)
    cropped = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    dx, dy = float(xs.min()), float(ys.min())
    shifted = []
    for part in parts:
        box = part.bbox
        shifted.append(PartDetection.from_source_class(
            part.source_class_id, part.confidence,
            (box[0] - dx, box[1] - dy, box[2] - dx, box[3] - dy),
        ))
    metadata = ownership()
    metadata.update(
        crop_bounds=[40, 80, 40 + cropped.shape[1], 80 + cropped.shape[0]],
        native_frame_shape=[1200, 1600],
    )
    report = assess(cropped, shifted, mask_metadata=metadata)
    assert report["classification"] == "confirmed_absent", report["cut_end_metrics"]
    assert "silhouette_meets_parent_crop_edge" in report["evidence"]


def test_slanted_and_irregular_cuts_are_rejected_and_a_severed_tail_is_not():
    from src.inference.head_silhouette import HeadSilhouetteConfig

    slanted = np.zeros((280, 420), np.uint8)
    cv2.fillPoly(slanted, [np.array([(20, 115), (190, 115), (330, 140), (190, 165), (120, 165)], np.int32)], 1)
    body = PartDetection.from_source_class(0, 0.95, _box(slanted))
    slanted_report = assess(slanted, [body])
    assert slanted_report["classification"] == "confirmed_absent", slanted_report["end_geometry"]
    assert slanted_report["cut_character"] == "slanted"
    assert slanted_report["grade_effect"] == "reject"
    assert slanted_report["orientation_reliable"] is True
    assert slanted_report["width_profile_ratio"]

    irregular = np.zeros((280, 360), np.uint8)
    cv2.rectangle(irregular, (80, 115), (200, 165), 1, -1)
    for offset, depth in enumerate((0, 16, 3, 18, 2, 14, 5, 17, 1, 12)):
        irregular[115 + offset * 5:120 + offset * 5, 80 - depth:80] = 1
    cv2.fillPoly(irregular, [np.array([(200, 118), (250, 140), (200, 162)], np.int32)], 1)
    irregular_report = assess(irregular, [PartDetection.from_source_class(0, 0.95, _box(irregular))])
    assert irregular_report["classification"] == "confirmed_absent", irregular_report["end_geometry"]
    assert irregular_report["cut_character"] in {"blunt", "irregular"}

    severed_tail = np.zeros((280, 400), np.uint8)
    cv2.ellipse(severed_tail, (120, 140), (90, 25), 0, 0, 360, 1, -1)
    cv2.rectangle(severed_tail, (120, 115), (250, 165), 1, -1)
    tail_report = assess(severed_tail, [PartDetection.from_source_class(0, 0.95, _box(severed_tail))])
    assert tail_report["classification"] == "unverified_nondetection", tail_report["end_geometry"]
    assert tail_report["geometry_decision"] == "severed_tail"
    assert "tail_damage_not_head_absence" in tail_report["evidence"]
    assert tail_report["grade_effect"] == "none"

    strict = HeadSilhouetteConfig(blunt_rise_fraction=0.01, irregular_rise_fraction=0.02, slanted_rise_fraction=0.03)
    mask, parts = specimen()
    parts = [part for part in parts if part.region != "Tail"]
    withheld = assess(mask, parts, head_config=strict)
    assert withheld["classification"] == "unverified_nondetection"
    assert withheld["cut_end_confirmed"] is False


def test_partial_occlusion_fragment_stays_ungraded():
    mask, parts = specimen()
    mask = mask.copy()
    mask[10:40, 10:40] = 1
    report = assess(mask, parts)
    assert report["classification"] == "ungraded_occluded"
    assert report["grade_effect"] == "none"


def test_model2_rejected_label_survives_a_hidden_head():
    mask, parts = specimen()
    report = assess(mask, parts, clipped=True)
    analysis = {
        "final_grade": "Rejected",
        "override": {"applied": True, "source": "Model 2 trained Rejected_* part label"},
        "feature_fusion": {"schema_version": "feature_fusion_v1", "final_grade": "Rejected"},
    }
    assert apply_head_integrity(analysis, "Rejected", report) == "Rejected"
    assert analysis["final_grade"] == "Rejected"
    assert analysis["head_integrity"]["classification"] == "ungraded_out_of_frame"
