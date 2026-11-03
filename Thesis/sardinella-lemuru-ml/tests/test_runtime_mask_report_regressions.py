"""Mask reports must distinguish available candidates from failed ownership."""
from copy import deepcopy

import numpy as np

from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from src.inference.preprocessing import CropBounds
from test_experimental_segmentation_pipeline import PARENTS, Service, parts


def provider(mode="normal", *, required_head=True):
    frame = np.full((120, 640, 3), 80, np.uint8)
    value = ExperimentalFrameSegmentation(frame, "native-report", service=Service(mode))
    evidence = parts()
    if not required_head:
        evidence = [part for part in evidence if part.region != "Head"]
    value.prepare(PARENTS, evidence)
    return value


def test_successful_candidate_report_does_not_claim_it_is_unavailable():
    value = provider()
    report = value.report(1)
    assert report["engineering_checks_passed"] is True
    assert report["ownership_status"] == "checks_passed_unvalidated"
    assert report["mask_overlay"]["contours"]
    assert report["reasons"]
    assert all("unavailable" not in reason.lower() for reason in report["reasons"])
    assert "unvalidated" in " ".join(report["reasons"]).lower()
    assert report["used_for_grading"] is False
    assert report["ownership"]["approved_for_grading"] is False


def test_withheld_mask_retains_exact_required_part_failure_and_raw_candidate():
    value = provider(required_head=False)
    report = value.report(1)
    assert report["engineering_checks_passed"] is False
    assert "required_head_evidence_unavailable" in report["reasons"]
    assert report["mask_overlay"]["contours"]  # Review display remains possible.
    pixels, metadata = value.get(1, CropBounds(20, 30, 280, 90))
    assert pixels is None
    assert metadata["measurement_validated"] is False


def test_prompt_failure_report_keeps_backend_error_detail_without_weakening_gates():
    value = provider("failed_first")
    report = value.report(1)
    assert report["engineering_checks_passed"] is False
    assert "candidate_unavailable" in report["reasons"]
    assert report["backend_error"] == {"type": "RuntimeError", "detail": "One decoder prompt failed"}
    assert not report["mask_overlay"]["contours"]
    assert report["used_for_grading"] is False


def test_cached_report_does_not_change_success_or_other_parent():
    value = provider()
    first = deepcopy(value.report(1))
    second = value.report(2)
    assert second["engineering_checks_passed"] is True
    assert value.report(1) == first
    assert len(value.service.frames) == 1
    assert len(value.service.prompts) == 2
