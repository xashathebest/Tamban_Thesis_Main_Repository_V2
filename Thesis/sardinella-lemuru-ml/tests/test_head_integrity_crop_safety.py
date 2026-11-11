"""Analysis crop edges cannot manufacture anatomical truncation evidence."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from src.inference.preprocessing import CropBounds


def context(*, native_clipped=False, full_engineering=False):
    frame = np.zeros((120, 320, 3), np.uint8)
    mask = np.zeros(frame.shape[:2], bool)
    cv2.ellipse(mask.view(np.uint8), (150, 60), (120, 22), 0, 0, 360, 1, -1)
    if native_clipped:
        mask[59:62, :31] = True
    reasons = [] if full_engineering else ["required_head_evidence_unavailable"]
    if native_clipped:
        reasons.append("mask_touches_frame_boundary")
    ownership = {
        "mask_geometry_checks_passed": not native_clipped,
        "engineering_checks_passed": full_engineering and not native_clipped,
        "conflicting_parent_ids": [], "reasons": reasons,
        "metrics": {"foreground_pixels": int(mask.sum())},
    }
    value = ExperimentalFrameSegmentation(frame, "fixture")
    value.candidates = {1: {"mask": mask}}
    value.ownership = {1: ownership}
    value.is_current = lambda: True
    return value, mask, ownership


@pytest.mark.parametrize("method,full_engineering", [("head_integrity_mask", False), ("get", True)])
def test_truncated_crop_is_withheld_without_altering_native_mask_or_ownership(method, full_engineering):
    value, native, ownership = context(full_engineering=full_engineering)
    before_mask, before_record = native.copy(), deepcopy(ownership)
    local, metadata = getattr(value, method)(1, CropBounds(80, 20, 280, 100))
    retention = metadata["analysis_crop_retention"]
    assert local is not None
    assert retention["omitted_native_foreground_pixels"] > 0
    assert retention["retained_foreground_fraction"] < 1.0
    assert retention["contains_complete_native_silhouette"] is False
    assert retention["native_silhouette_frame_clipped"] is False
    assert metadata["head_integrity_eligibility"]["eligible"] is False
    assert metadata["head_integrity_eligibility"]["withheld_category"] == "analysis_crop_truncated"
    assert "analysis_crop_truncates_silhouette" in metadata["ownership"]["reasons"]
    assert np.array_equal(native, before_mask)
    assert ownership == before_record


def test_complete_crop_remains_eligible_without_required_head_detection():
    value, native, _ = context()
    local, metadata = value.head_integrity_mask(1, CropBounds(20, 20, 280, 100))
    assert local is not None
    assert int(local.sum()) == int(native.sum())
    assert metadata["analysis_crop_retention"]["contains_complete_native_silhouette"] is True
    assert metadata["head_integrity_eligibility"]["eligible"] is True
    assert metadata["head_integrity_eligibility"]["engineering_checks_passed"] is False


def test_native_clipping_remains_distinct_from_complete_crop():
    value, _, _ = context(native_clipped=True)
    _, metadata = value.head_integrity_mask(1, CropBounds(0, 0, 320, 120))
    assert metadata["analysis_crop_retention"]["contains_complete_native_silhouette"] is True
    assert metadata["analysis_crop_retention"]["native_silhouette_frame_clipped"] is True
    assert metadata["head_integrity_eligibility"]["analysis_crop_truncated"] is False
    assert metadata["head_integrity_eligibility"]["withheld_category"] == "frame_clipped"
    assert metadata["head_integrity_eligibility"]["eligible"] is False


def test_invalid_crop_bounds_do_not_silently_slice_another_region():
    value, _, _ = context()
    local, metadata = value.head_integrity_mask(1, CropBounds(-10, 10, 280, 100))
    assert local is None
    assert metadata["head_integrity_eligibility"]["eligible"] is False
    assert "invalid_analysis_crop_bounds" in metadata["head_integrity_eligibility"]["blocking_reasons"]
