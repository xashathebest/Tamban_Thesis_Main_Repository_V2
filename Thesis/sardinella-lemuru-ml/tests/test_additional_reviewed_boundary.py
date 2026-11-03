"""Reviewed full-frame foreground can disprove bbox-only image clipping."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.inference.association import ParentAnchor
from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from src.inference.mask_ownership import validate_candidate_masks
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds


SHAPE = (120, 640)
PARENT = ParentAnchor(1, (0, 30, 280, 90))
REVIEW = {"reviewer": "software-fixture", "review_id": "edge-padding-fixture", "reference_set_id": "synthetic-only"}


def evidence():
    parts = [PartDetection.from_source_class(0, .9, (90, 38, 215, 82)),
             PartDetection.from_source_class(1, .8, (30, 47, 75, 73))]
    return parts, [SimpleNamespace(part=part, status="ASSIGNED", track_id=1) for part in parts]


def mask(center=(150, 60)):
    pixels = np.zeros(SHAPE, np.uint8)
    cv2.ellipse(pixels, center, (120, 22), 0, 0, 360, 1, -1)
    return pixels.astype(bool)


def candidate(pixels=None):
    return {"mask": mask() if pixels is None else pixels, "parent_id": 1, "bbox_global": PARENT.bbox,
            "provenance": {"frame_key": "native-frame", "coordinate_space": "original_frame",
                "mask_shape": list(SHAPE), "source": "reviewed_native_instance_mask", "parent_id": 1,
                "original_bbox_global": list(PARENT.bbox), "validation_provenance": deepcopy(REVIEW)}}


def validate(value):
    parts, rows = evidence()
    return validate_candidate_masks({1: value}, [PARENT], parts, associations=rows,
        frame_shape=SHAPE, expected_frame_key="native-frame")[1]


def test_reviewed_native_foreground_clear_of_image_edge_does_not_fail_padded_bbox():
    result = validate(candidate())
    assert result["engineering_checks_passed"]
    assert result["metrics"]["parent_bbox_touches_frame_boundary"] is True
    assert result["metrics"]["mask_touches_frame_boundary"] is False
    # Engineering consistency is never permission to invent expert approval.
    assert result["ownership_validated"] is False
    assert result["approved_for_grading"] is False


def test_actual_reviewed_foreground_contact_remains_clipped():
    result = validate(candidate(mask(center=(80, 60))))
    assert not result["engineering_checks_passed"]
    assert "mask_touches_frame_boundary" in result["reasons"]
    assert "parent_touches_frame_boundary" in result["reasons"]


@pytest.mark.parametrize("field,value,reason", [
    ("validation_provenance", None, "reviewed_mask_provenance_unavailable"),
    ("validation_provenance", {"reviewer": "only-a-name"}, "reviewed_mask_provenance_unavailable"),
    ("coordinate_space", "crop_local", "candidate_native_coordinates_mismatch"),
    ("mask_shape", [60, 280], "candidate_native_coordinates_mismatch"),
    ("parent_id", 2, "candidate_parent_identity_mismatch"),
    ("original_bbox_global", [0, 30, 281, 90], "candidate_prompt_box_mismatch"),
    ("frame_key", "old-frame", "candidate_frame_identity_mismatch"),
])
def test_reviewed_label_does_not_bypass_native_identity_and_review_checks(field, value, reason):
    supplied = candidate()
    supplied["provenance"][field] = value
    result = validate(supplied)
    assert not result["engineering_checks_passed"]
    assert reason in result["reasons"]


class UnavailableSam:
    @contextmanager
    def open_frame(self, frame, frame_key):
        yield self

    def predict(self, *args, **kwargs):
        return {"status": "unavailable", "mask": None, "reason": "No neural inference in this regression."}

    def diagnostics(self):
        return {}


def test_real_reviewed_candidate_constructor_retains_native_boundary_provenance():
    frame = np.full((*SHAPE, 3), 80, np.uint8)
    whole = mask()
    body = np.zeros(SHAPE, bool)
    body[44:76, 100:200] = True
    reviewed = {1: {"whole_mask": whole, "body_mask": body, "validation_provenance": deepcopy(REVIEW),
                    "body_region_validated": True}}
    context = ExperimentalFrameSegmentation(frame, "fixture", service=UnavailableSam())
    parts, rows = evidence()
    context.prepare([PARENT], parts, rows, reviewed_instances=reviewed)
    assert context.reviewed_ownership[1]["engineering_checks_passed"]
    measured, metadata = context.get(1, CropBounds(0, 30, 280, 90))
    assert np.array_equal(measured, whole[30:90, :280])
    assert metadata["source"] == "reviewed_native_instance_mask"
    assert metadata["validation_provenance"] == REVIEW
