"""Check an anterior endpoint against source-bound native neighbor masks.

This is evidence for the independent head-integrity pathway, never an ownership
assignment or an anatomical verdict. No foreground is cut, reassigned or filled.
The normal association scores, margins and required-region rules are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Integral

import cv2
import numpy as np

from src.inference.association import ParentAnchor
from src.inference.fish_geometry import FishGeometryConfig, _aligned_profile
from src.inference.head_silhouette import analyze_silhouette_ends, load_head_silhouette_config
from src.inference.instance_association import _native_candidate


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _box(parent):
    try:
        value = np.asarray(_field(parent, "bbox"), dtype=float)
    except (TypeError, ValueError):
        return None
    if (value.shape != (4,) or not np.isfinite(value).all()
            or value[2] <= value[0] or value[3] <= value[1]):
        return None
    return value


def _overlap(first, second):
    return bool(max(first[0], second[0]) < min(first[2], second[2])
                and max(first[1], second[1]) < min(first[3], second[3]))


def inspect_head_endpoint_ownership(
    candidates, ownership, parents, parent_id, measurements, *,
    expected_frame_key, frame_shape, config=None, head_config=None,
):
    """Measure shared native foreground in the confirmed anterior window.

    ``candidates`` and ``ownership`` must be the actual current frame provider's
    native records, not a positive summary supplied in serialized metadata. The
    common native-candidate checks bind every required mask to its parent,
    prompt, frame key, shape and checked foreground count. Parent-box overlap
    alone never establishes occlusion. Any shared anterior pixel blocks the
    independent proof, even when global mask overlap passes its existing gate.

    The largest component defines the axis extent, matching anatomy metrology.
    Every foreground pixel, including secondary components, participates in the
    overlap check. Crop translation cannot affect this projection-based test.
    """
    settings = config or FishGeometryConfig()
    end_settings = head_config or load_head_silhouette_config()
    result = {
        "algorithm_version": "native_anterior_endpoint_ownership_v1",
        "verified": False, "clear": False, "parent_id": parent_id,
        "frame_key": expected_frame_key, "coordinate_space": "original_frame",
        "anterior_end": None, "anterior_window_fraction": end_settings.slanted_rise_fraction,
        "anterior_foreground_pixels": 0, "anterior_shared_pixels": 0,
        "neighbors": [], "required_neighbor_ids": [], "unverified_neighbor_ids": [],
        "native_pixels_modified": False, "ownership_validated": False,
        "used_for_part_assignment": False, "reasons": [],
        "scope": "Native foreground sharing at the geometrically confirmed anterior endpoint; not expert anatomical ownership validation.",
    }

    def fail(reason):
        if reason not in result["reasons"]:
            result["reasons"].append(reason)

    try:
        shape = tuple(frame_shape[:2])
    except (TypeError, ValueError):
        shape = ()
    if (len(shape) != 2 or any(not isinstance(value, Integral) or isinstance(value, bool) or value <= 0 for value in shape)
            or not isinstance(candidates, Mapping) or not isinstance(ownership, Mapping)
            or expected_frame_key is None):
        fail("native_frame_context_unavailable")
        return result
    result["frame_shape"] = [int(value) for value in shape]
    parents = list(parents)
    identities = [_field(parent, "track_id") for parent in parents]
    if (len(set(identities)) != len(identities) or parent_id not in identities
            or any(not isinstance(identity, Integral) or isinstance(identity, bool) for identity in identities)):
        fail("native_parent_context_unavailable")
        return result
    boxes = {_field(parent, "track_id"): _box(parent) for parent in parents}
    if any(box is None for box in boxes.values()):
        fail("invalid_native_parent_geometry")
        return result
    parents = [ParentAnchor(int(_field(parent, "track_id")), tuple(boxes[_field(parent, "track_id")])) for parent in parents]
    parent = next(parent for parent in parents if parent.track_id == parent_id)
    native, source_reasons = _native_candidate(
        candidates.get(parent_id), ownership.get(parent_id), parent, shape, expected_frame_key)
    if native is None:
        fail("owner_native_mask_not_verified")
        result["owner_source_reasons"] = source_reasons
        return result
    measured = dict(measurements) if isinstance(measurements, Mapping) else {}
    confidence = measured.get("orientation_confidence") or {}
    anterior = measured.get("cut_end_axis")
    if (measured.get("cut_end_confirmed") is not True
            or anterior not in {"minimum_projection", "maximum_projection"}
            or measured.get("orientation_reliable") is not True
            or measured.get("anatomical_orientation_reliable") is not True
            or not isinstance(confidence, Mapping) or confidence.get("polarity_reliable") is not True):
        fail("anterior_endpoint_not_independently_resolved")
        return result
    try:
        axis = np.asarray(measured.get("orientation_axis_vector"), dtype=float)
    except (TypeError, ValueError):
        axis = np.empty(0)
    if axis.shape != (2,) or not np.isfinite(axis).all() or float(np.linalg.norm(axis)) <= 0:
        fail("signed_anatomical_axis_unavailable")
        return result
    axis = axis / np.linalg.norm(axis)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(native.astype(np.uint8), connectivity=8)
    if count <= 1:
        fail("owner_native_foreground_unavailable")
        return result
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    component = labels == largest
    component_pixels = int(stats[largest, cv2.CC_STAT_AREA])
    secondary = 1.0 - component_pixels / max(1, int(native.sum()))
    result["owner_secondary_component_fraction"] = round(secondary, 6)
    if secondary > settings.maximum_secondary_component_fraction:
        fail("owner_native_foreground_fragmented")
        return result
    try:
        diagnostics, _, widths, _, transform, lower, upper = _aligned_profile(component.astype(np.uint8))
    except (cv2.error, ValueError, FloatingPointError, ZeroDivisionError):
        fail("native_endpoint_profile_unavailable")
        return result
    fresh_axis = transform[0, :2]
    ratio = float(diagnostics["principal_axis_ratio"])
    result["native_axis_ratio"] = round(ratio, 6)
    # Measurements serialize six decimal places. This tolerance verifies their
    # numerical coordinate agreement; it is not an anatomical class threshold.
    if ratio < settings.minimum_axis_ratio or not np.allclose(axis, fresh_axis, rtol=0, atol=1e-5):
        fail("signed_axis_does_not_match_native_mask")
        return result
    fresh_ends = analyze_silhouette_ends(widths, lower, upper, config=end_settings)
    result["native_geometry_decision"] = fresh_ends.get("geometry_decision") if fresh_ends else None
    if not fresh_ends or fresh_ends.get("cut_end_confirmed") is not True or fresh_ends.get("cut_end_axis") != anterior:
        fail("anterior_endpoint_does_not_match_native_mask")
        return result
    ys, xs = np.nonzero(component)
    projection = xs * axis[0] + ys * axis[1]
    low, high = float(projection.min()), float(projection.max())
    if high <= low or not 0 < end_settings.slanted_rise_fraction < 1:
        fail("anterior_window_unavailable")
        return result
    own_y, own_x = np.nonzero(native)
    own_projection = own_x * axis[0] + own_y * axis[1]
    fraction = end_settings.slanted_rise_fraction
    threshold = low + fraction * (high - low) if anterior == "minimum_projection" else high - fraction * (high - low)
    is_anterior = own_projection <= threshold if anterior == "minimum_projection" else own_projection >= threshold
    cap_y, cap_x = own_y[is_anterior], own_x[is_anterior]
    result.update(anterior_end=anterior, orientation_axis_vector=np.round(axis, 6).tolist(),
                  projection_range_px=[round(low, 6), round(high, 6)],
                  anterior_projection_limit_px=round(threshold, 6),
                  anterior_foreground_pixels=int(len(cap_x)))
    if not len(cap_x):
        fail("anterior_foreground_unavailable")
        return result
    shared_union = np.zeros(len(cap_x), dtype=bool)
    for neighbor in parents:
        identity = _field(neighbor, "track_id")
        if identity == parent_id:
            continue
        overlaps = _overlap(boxes[parent_id], boxes[identity])
        candidate = candidates.get(identity)
        raw = candidate.get("mask") if isinstance(candidate, Mapping) else None
        raw_cap_contact = False
        if isinstance(raw, np.ndarray) and raw.shape == shape and raw.dtype.kind in "buif":
            samples = raw[cap_y, cap_x]
            raw_cap_contact = bool(np.any(samples >= .5 if raw.dtype.kind == "f" else samples > 0))
        required = overlaps or raw_cap_contact
        other, reasons = _native_candidate(
            candidate, ownership.get(identity), neighbor, shape, expected_frame_key)
        row = {"parent_id": identity, "parent_boxes_overlap": overlaps,
               "raw_foreground_claims_anterior": raw_cap_contact,
               "source_verified": other is not None, "required_for_endpoint_proof": required,
               "anterior_shared_pixels": None, "shared_foreground_pixels": None, "reasons": reasons}
        result["neighbors"].append(row)
        if required:
            result["required_neighbor_ids"].append(identity)
        if other is None:
            if required:
                result["unverified_neighbor_ids"].append(identity)
                fail("overlapping_neighbor_native_mask_not_verified")
            continue
        shared_cap = other[cap_y, cap_x]
        shared_pixels = int(np.count_nonzero(shared_cap))
        row.update(anterior_shared_pixels=shared_pixels,
                   shared_foreground_pixels=int(np.count_nonzero(native & other)))
        shared_union |= shared_cap
        if shared_pixels:
            fail("anterior_endpoint_shared_foreground")
    result["anterior_shared_pixels"] = int(np.count_nonzero(shared_union))
    result["verified"] = not result["unverified_neighbor_ids"]
    result["clear"] = result["verified"] and result["anterior_shared_pixels"] == 0
    return result
