"""A Body ambiguity can be separated only from a verified, clear anterior cap."""

import cv2
import json
import numpy as np
import pytest

from src.inference.anatomical_measurements import measure_mask_anatomy
from src.inference.association import ParentAnchor
from src.inference.head_endpoint_ownership import inspect_head_endpoint_ownership
from src.inference.mask_ownership import validate_candidate_masks


SHAPE = (600, 600)
FRAME_KEY = "endpoint-native-frame"


def _bbox(mask, padding=45):
    ys, xs = np.nonzero(mask)
    return (float(max(0, xs.min() - padding)), float(max(0, ys.min() - padding)),
            float(min(SHAPE[1], xs.max() + padding + 1)), float(min(SHAPE[0], ys.max() + padding + 1)))


def scene(angle=0, *, shared=None):
    own = np.zeros(SHAPE, np.uint8)
    cv2.rectangle(own, (150, 220), (320, 270), 1, -1)
    cv2.fillPoly(own, [np.array(((320, 225), (410, 245), (320, 265)))], 1)
    neighbor = np.zeros(SHAPE, np.uint8)
    cv2.rectangle(neighbor, (150, 320), (330, 360), 1, -1)
    cv2.ellipse(neighbor, (150, 340), (40, 22), 0, 0, 360, 1, -1)
    cv2.fillPoly(neighbor, [np.array(((330, 325), (410, 340), (330, 355)))], 1)
    parents = [ParentAnchor(1, _bbox(own)), ParentAnchor(2, _bbox(neighbor))]
    if shared == "head":
        neighbor[245, 150] = 1
    elif shared == "tail":
        neighbor[245, 400] = 1
    if angle:
        transform = cv2.getRotationMatrix2D((299.5, 299.5), angle, 1)
        own = cv2.warpAffine(own, transform, SHAPE[::-1], flags=cv2.INTER_NEAREST)
        neighbor = cv2.warpAffine(neighbor, transform, SHAPE[::-1], flags=cv2.INTER_NEAREST)
        parents = [ParentAnchor(1, _bbox(own)), ParentAnchor(2, _bbox(neighbor))]
    candidates = {
        parent.track_id: {"mask": mask.astype(bool), "parent_id": parent.track_id,
            "provenance": {"backend": "mobilesam_experimental", "source": "mobilesam_box_prompt_candidate",
                "frame_key": FRAME_KEY, "parent_id": parent.track_id, "coordinate_space": "original_frame",
                "mask_shape": list(SHAPE), "original_bbox_global": list(parent.bbox),
                "prompt_bbox_global": list(parent.bbox)}}
        for parent, mask in zip(parents, (own, neighbor))
    }
    checked = validate_candidate_masks(candidates, parents, [], associations=[], frame_shape=SHAPE,
                                       expected_frame_key=FRAME_KEY)
    anatomy = measure_mask_anatomy(own, ())
    return candidates, checked, parents, anatomy


def inspect(candidates, checked, parents, anatomy, **kwargs):
    options = {"expected_frame_key": FRAME_KEY, "frame_shape": SHAPE}
    options.update(kwargs)
    return inspect_head_endpoint_ownership(candidates, checked, parents, 1, anatomy, **options)


@pytest.mark.parametrize("angle", [0, 45, -45, 90, 135])
def test_disjoint_native_masks_have_clear_independent_endpoints_in_any_orientation(angle):
    candidates, checked, parents, anatomy = scene(angle)
    snapshots = {identity: candidate["mask"].copy() for identity, candidate in candidates.items()}
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] is True, report
    assert report["clear"] is True
    assert report["anterior_shared_pixels"] == 0
    assert report["anterior_window_fraction"] == .30
    assert report["native_pixels_modified"] is False
    assert report["ownership_validated"] is False
    assert report["used_for_part_assignment"] is False
    for identity, candidate in candidates.items():
        np.testing.assert_array_equal(candidate["mask"], snapshots[identity])
    json.dumps(report, allow_nan=False)


def test_a_single_shared_anterior_pixel_blocks_the_independent_proof():
    candidates, checked, parents, anatomy = scene(shared="head")
    assert checked[1]["mask_geometry_checks_passed"] is True
    assert checked[1]["metrics"]["pair_overlap_fraction"]["2"] < .10
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] is True
    assert report["clear"] is False
    assert report["anterior_shared_pixels"] == 1
    assert "anterior_endpoint_shared_foreground" in report["reasons"]


def test_posterior_contact_does_not_become_anterior_occlusion():
    candidates, checked, parents, anatomy = scene(shared="tail")
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] and report["clear"]
    assert report["neighbors"][0]["shared_foreground_pixels"] == 1
    assert report["neighbors"][0]["anterior_shared_pixels"] == 0


def test_crop_translation_preserves_native_endpoint_proof():
    candidates, checked, parents, _ = scene()
    own = candidates[1]["mask"]
    local = own[180:290, 120:440]
    anatomy = measure_mask_anatomy(local, ())
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] and report["clear"]
    assert report["coordinate_space"] == "original_frame"


@pytest.mark.parametrize("missing", ["candidate", "record"])
def test_missing_overlapping_neighbor_evidence_withholds_proof(missing):
    candidates, checked, parents, anatomy = scene()
    (candidates if missing == "candidate" else checked).pop(2)
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] is False and report["clear"] is False
    assert report["unverified_neighbor_ids"] == [2]


@pytest.mark.parametrize("identity", [1, 2])
@pytest.mark.parametrize("field,value", [("frame_key", "different-frame"), ("parent_id", 99),
                                       ("mask_shape", [599, 600]), ("coordinate_space", "crop_local")])
def test_native_source_or_parent_mismatch_cannot_claim_clear_ownership(identity, field, value):
    candidates, checked, parents, anatomy = scene()
    candidates[identity]["provenance"][field] = value
    report = inspect(candidates, checked, parents, anatomy)
    assert report["verified"] is False and report["clear"] is False


def test_public_positive_summary_cannot_replace_native_source_records():
    candidates, checked, parents, anatomy = scene()
    checked[1] = {"verified": True, "clear": True, "head_endpoint_ownership": {"verified": True, "clear": True}}
    report = inspect(candidates, checked, parents, anatomy)
    assert not report["verified"] and not report["clear"]


def test_unresolved_or_stale_anterior_direction_withholds_proof():
    candidates, checked, parents, anatomy = scene()
    anatomy["cut_end_axis"] = "maximum_projection"
    report = inspect(candidates, checked, parents, anatomy)
    assert not report["verified"] and not report["clear"]
    assert "anterior_endpoint_does_not_match_native_mask" in report["reasons"]
    anatomy["orientation_confidence"]["polarity_reliable"] = False
    report = inspect(candidates, checked, parents, anatomy)
    assert "anterior_endpoint_not_independently_resolved" in report["reasons"]


def test_a_stale_signed_axis_cannot_place_the_cap_at_the_wrong_end():
    candidates, checked, parents, anatomy = scene()
    anatomy["orientation_axis_vector"] = [-value for value in anatomy["orientation_axis_vector"]]
    report = inspect(candidates, checked, parents, anatomy)
    assert not report["verified"] and not report["clear"]
    assert "signed_axis_does_not_match_native_mask" in report["reasons"]


def test_unverified_neighbor_foreground_at_the_cap_cannot_hide_behind_disjoint_boxes():
    candidates, checked, parents, anatomy = scene(shared="head")
    # The stale candidate foreground claims the cut, although its parent box is
    # elsewhere. Its claimed pixel must make source verification mandatory.
    parents[1] = ParentAnchor(2, (10, 400, 100, 480))
    candidates[2]["provenance"]["frame_key"] = "stale-frame"
    report = inspect(candidates, checked, parents, anatomy)
    assert not report["verified"] and not report["clear"]
    assert report["neighbors"][0]["parent_boxes_overlap"] is False
    assert report["neighbors"][0]["raw_foreground_claims_anterior"] is True
    assert report["neighbors"][0]["required_for_endpoint_proof"] is True
