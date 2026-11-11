"""Independent torso support cannot fill missing Model 2 anatomical labels."""
from copy import deepcopy

import cv2
import numpy as np
import pytest

from src.inference.anatomical_measurements import measure_mask_anatomy
from src.inference.fish_geometry import FishGeometryConfig
from src.inference.head_body_support import measure_silhouette_torso_support
from src.inference.part_types import PartDetection


def fish(*, intact=False, angle=0):
    mask = np.zeros((360, 360), np.uint8)
    cv2.rectangle(mask, (80, 155), (220, 205), 1, -1)
    cv2.fillPoly(mask, [np.array([(220, 160), (290, 180), (220, 200)], np.int32)], 1)
    if intact:
        cv2.fillPoly(mask, [np.array([(80, 180), (50, 168), (38, 180), (50, 192)], np.int32)], 1)
        cv2.circle(mask, (88, 180), 16, 1, -1)
    if angle:
        rotation = cv2.getRotationMatrix2D((180, 180), angle, 1)
        mask = cv2.warpAffine(mask, rotation, (360, 360), flags=cv2.INTER_NEAREST)
    return mask


@pytest.mark.parametrize("angle", [0, 45, 90, 135, 180])
def test_no_detected_body_can_have_resolved_torso_support_without_synthesized_pixels(angle):
    mask = fish(angle=angle)
    anatomy = measure_mask_anatomy(mask, ())
    snapshot, native = deepcopy(anatomy), mask.copy()
    report = measure_silhouette_torso_support(mask, anatomy)
    assert report["eligible"] is True, report
    assert report["source"] == "silhouette_torso_geometry"
    assert report["support_pixels"] >= FishGeometryConfig().minimum_mask_pixels
    assert report["width_px"] >= FishGeometryConfig().minimum_transverse_pixels
    assert report["span_px"] >= FishGeometryConfig().minimum_body_profile_pixels
    assert report["support_length_fraction"][0] >= report["terminal_exclusion_fraction"]
    assert report["support_length_fraction"][1] <= 1.0 - report["terminal_exclusion_fraction"]
    assert anatomy["body_pixels"] == 0
    assert anatomy == snapshot
    assert np.array_equal(native, mask)
    assert report["ownership_required"] is True
    assert report["ownership_validated"] is False
    assert report["model2_body_pixels_synthesized"] is False
    assert report["used_for_normal_grading"] is False


def test_intact_snout_cannot_supply_missing_body_rejection_evidence():
    report = measure_silhouette_torso_support(fish(intact=True))
    assert report["eligible"] is False
    assert "snout_like_anterior_extension" in report["reasons"]


def test_fragmentation_is_not_repaired_before_support_is_accepted():
    mask = fish()
    mask[20:45, 20:45] = 1
    report = measure_silhouette_torso_support(mask)
    assert report["eligible"] is False
    assert "multiple_foreground_components" in report["reasons"]


def test_merged_parallel_fish_or_bridged_foreground_is_withheld():
    mask = fish()
    shifted = np.roll(mask, 90, axis=0)
    mask |= shifted
    mask[180:280, 150:154] = 1
    report = measure_silhouette_torso_support(mask)
    assert report["eligible"] is False
    assert any(reason in report["reasons"] for reason in (
        "orientation_uncertain", "gapped_interior_cross_sections", "implausible_silhouette_holes",
        "centerline_residual_exceeds_limit", "severed_anterior_end_not_confirmed"))


def test_split_torso_cannot_be_used_as_contiguous_support():
    mask = fish()
    mask[:, 150:175] = 0
    report = measure_silhouette_torso_support(mask)
    assert report["eligible"] is False
    assert "multiple_foreground_components" in report["reasons"]


def test_tiny_tapered_mask_does_not_establish_a_resolved_torso():
    mask = np.zeros((80, 100), np.uint8)
    cv2.fillPoly(mask, [np.array([(20, 38), (20, 42), (75, 40)], np.int32)], 1)
    report = measure_silhouette_torso_support(mask)
    assert report["eligible"] is False
    assert any(reason in report["reasons"] for reason in (
        "insufficient_foreground_pixels", "insufficient_contiguous_broad_torso_sections",
        "insufficient_interior_torso_pixels"))


def test_supplied_anterior_direction_must_agree_with_fresh_native_profile():
    mask = fish()
    anatomy = measure_mask_anatomy(mask, ())
    anatomy["cut_end_axis"] = ("minimum_projection" if anatomy["cut_end_axis"] == "maximum_projection"
                                  else "maximum_projection")
    report = measure_silhouette_torso_support(mask, anatomy)
    assert report["eligible"] is False
    assert "anterior_polarity_not_agreed" in report["reasons"]


def test_tail_landmark_conflict_is_not_erased_by_silhouette_morphology():
    mask = fish()
    anatomy = measure_mask_anatomy(mask, ())
    anatomy["reasons"].append("tail_cut_polarity_conflict")
    report = measure_silhouette_torso_support(mask, anatomy)
    assert report["eligible"] is False
    assert "anatomical_landmark_conflict" in report["reasons"]


def test_resolution_requirements_come_from_existing_geometry_settings():
    mask = fish()
    report = measure_silhouette_torso_support(mask, config=FishGeometryConfig(minimum_body_profile_pixels=400))
    assert report["eligible"] is False
    assert "insufficient_contiguous_broad_torso_sections" in report["reasons"]


def test_invalid_mask_remains_unavailable():
    report = measure_silhouette_torso_support(np.zeros((5, 5, 3), np.uint8))
    assert report["eligible"] is False
    assert report["reasons"] == ["segmentation_mask_unavailable"]


def test_slanted_cut_uses_torso_interior_instead_of_tip_centerline_deviation():
    mask = np.zeros((280, 420), np.uint8)
    cv2.fillPoly(mask, [np.array([(20, 115), (190, 115), (330, 140), (190, 165), (120, 165)], np.int32)], 1)
    report = measure_silhouette_torso_support(mask)
    assert report["eligible"] is True, report
    assert report["profile_quality"]["centerline_deviation_width_ratio"] > FishGeometryConfig().maximum_centerline_deviation_width_ratio
    assert report["interior_centerline_quality"]["centerline_deviation_width_ratio"] <= FishGeometryConfig().maximum_centerline_deviation_width_ratio


def test_tail_landmark_on_posterior_agrees_with_geometric_torso_without_body_detection():
    tail = PartDetection.from_source_class(2, .95, (235, 165, 290, 195))
    report = measure_silhouette_torso_support(fish(), parts=[tail])
    assert report["eligible"] is True, report
    assert report["tail_polarity_check"]["status"] == "confirmed"


@pytest.mark.parametrize("box,expected_reason", [
    ((80, 155, 110, 205), "tail_cut_polarity_conflict"),
    ((145, 155, 165, 205), "tail_body_polarity_uncertain"),
    ((5, 5, 15, 15), "tail_not_on_silhouette"),
])
def test_tail_contradictions_cannot_be_ignored_when_body_detector_missed(box, expected_reason):
    tail = PartDetection.from_source_class(2, .95, box)
    report = measure_silhouette_torso_support(fish(), parts=[tail])
    assert report["eligible"] is False
    assert expected_reason in report["reasons"]


def test_multiple_tail_associations_prevent_torso_only_fallback():
    tail = PartDetection.from_source_class(2, .95, (235, 165, 290, 195))
    report = measure_silhouette_torso_support(fish(), parts=[tail, tail])
    assert report["eligible"] is False
    assert "multiple_tail_associations" in report["reasons"]


def test_irregular_only_terminal_requires_real_detector_body_support():
    mask = np.zeros((180, 320), np.uint8)
    for index, column in enumerate(range(30, 271)):
        width = (19 if index < 40 else round(19 + 32 * (index - 40) / 10) if index < 50
                 else 51 if index <= 120 else max(1, round(51 * (240 - index) / 120)))
        mask[90 - width // 2:90 + width // 2 + 1, column] = 1
    anatomy = measure_mask_anatomy(mask, ())
    assert anatomy["cut_end_confirmed"] is True
    assert anatomy["cut_character"] == "irregular"
    report = measure_silhouette_torso_support(mask, anatomy)
    assert report["eligible"] is False
    assert "irregular_terminal_requires_detector_body" in report["reasons"]
