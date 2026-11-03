"""Read explicitly reviewed, pixel-bound feature records; never approve data."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np


def load_reviewed_instances(frame, parents, source_context=None):
    configured = os.getenv("FISH_REVIEWED_FEATURES_PATH", "").strip()
    if not configured:
        return {}, {"status": "not_configured", "approved_records": 0}
    path = Path(configured).expanduser().resolve()
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if catalog.get("schema_version") != "reviewed_feature_records_v1" or not isinstance(catalog.get("records"), list) or len(catalog["records"]) > 1000:
            raise ValueError("Expected at most 1000 reviewed_feature_records_v1 records.")
        digest = hashlib.sha256(memoryview(np.ascontiguousarray(frame))).hexdigest()
        source_id = (source_context or {}).get("source_id")
        ids = {parent.track_id for parent in parents}
        accepted, duplicates = {}, set()
        for record in catalog["records"]:
            if not isinstance(record, dict) or record.get("source_id") != source_id or record.get("frame_pixels_sha256") != digest:
                continue
            identity = record.get("fish_id")
            if isinstance(identity, bool) or identity not in ids:
                continue
            review = record.get("validation_provenance")
            if not isinstance(review, dict) or not all(isinstance(review.get(k), str) and review[k].strip() for k in ("reviewer", "review_id", "reference_set_id")):
                continue
            if not all(record.get(k) is True for k in ("reviewed", "ownership_validated", "measurement_validated", "body_mask_validated")):
                continue
            if any(record.get(k) is not False for k in ("clipped", "overlapping", "ownership_ambiguous", "partial_silhouette")):
                continue
            masks = {}
            for name in ("whole_mask_path", "body_mask_path"):
                location = Path(record.get(name) or "")
                location = location if location.is_absolute() else path.parent / location
                pixels = cv2.imread(str(location), cv2.IMREAD_GRAYSCALE)
                if pixels is None or pixels.shape != frame.shape[:2] or not np.isin(pixels, [0, 1, 255]).all() or not pixels.any():
                    raise ValueError(f"Reviewed {name} must contain native, binary, nonempty pixels.")
                masks[name] = pixels != 0
            if np.any(masks["body_mask_path"] & ~masks["whole_mask_path"]):
                raise ValueError("Reviewed Body support must lie inside the reviewed fish mask.")
            structural = record.get("structural_evidence")
            if isinstance(structural, dict):
                valid_identity = (structural.get("fish_id") == identity and not isinstance(structural.get("fish_id"), bool)
                    and structural.get("parent_track_id", identity) == identity
                    and structural.get("source_id") == source_id and structural.get("frame_pixels_sha256") == digest)
                locations = structural.get("locations")
                valid_locations = isinstance(locations, list) and bool(locations)
                for location in locations if isinstance(locations, list) else ():
                    values = [location.get(key) for key in ("x", "y", "width", "height")] if isinstance(location, dict) else []
                    if len(values) != 4 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in values):
                        valid_locations = False
                        break
                    x,y,w,h = values
                    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > frame.shape[1] or y+h > frame.shape[0]:
                        valid_locations = False
                        break
                    support = masks["body_mask_path"][int(y):math.ceil(y+h),int(x):math.ceil(x+w)]
                    if not support.size or not support.all():
                        valid_locations = False
                        break
                if not valid_identity or not valid_locations:
                    record = {**record, "structural_evidence": None}
            if identity in accepted:
                duplicates.add(identity)
                continue
            accepted[identity] = {**deepcopy(record), "whole_mask": masks["whole_mask_path"], "body_mask": masks["body_mask_path"]}
        for identity in duplicates:
            accepted.pop(identity, None)
        return accepted, {"status": "reviewed_artifacts_loaded", "approved_records": len(accepted),
                          "conflicting_review_ids": sorted(duplicates), "frame_pixels_sha256": digest}
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return {}, {"status": "unavailable", "approved_records": 0, "reason": str(error)}


def refine_reviewed_associations(rows, reviewed, frame_shape):
    """Exclude contradictory pixels; only explicit reviewed labels assign parts.

    SAM candidates never enter this function. Masks alone do not resolve a
    neighboring Head/Body box: assignment requires a matching reviewed part
    record as well as the independently reviewed native fish pixels.
    """
    from dataclasses import replace
    conflicts = {}
    identities = list(reviewed)
    for index, first in enumerate(identities):
        for second in identities[index+1:]:
            if np.any(reviewed[first]["whole_mask"] & reviewed[second]["whole_mask"]):
                conflicts.setdefault(first,set()).add(second)
                conflicts.setdefault(second,set()).add(first)
    result = []
    for row in rows:
        x1,y1,x2,y2 = row.part.bbox
        left,top = max(0,math.floor(x1)),max(0,math.floor(y1))
        right,bottom = min(frame_shape[1],math.ceil(x2)),min(frame_shape[0],math.ceil(y2))
        claims = []
        for identity, record in reviewed.items():
            support = record["whole_mask"][top:bottom,left:right]
            if identity in conflicts or not support.size or not support.any():
                continue
            for claim in record.get("part_ownership", []):
                if not isinstance(claim,dict) or claim.get("reviewed") is not True or claim.get("region") != row.part.region:
                    continue
                box = claim.get("bbox")
                if (claim.get("source_class_id") == row.part.source_class_id and isinstance(box,list) and len(box)==4
                        and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in box)
                        and np.allclose(box,row.part.bbox,rtol=0,atol=.001)):
                    claims.append(identity)
                    break
        if row.track_id in conflicts:
            owners = tuple(sorted({row.track_id,*conflicts[row.track_id]}))
            row = replace(row,status="AMBIGUOUS",track_id=None,ambiguous_track_ids=owners,reason="reviewed_pixel_ownership_conflict")
        elif len(claims)>1:
            row = replace(row,status="AMBIGUOUS",track_id=None,ambiguous_track_ids=tuple(sorted(claims)),reason="conflicting_reviewed_part_labels")
        elif len(claims)==1:
            row = replace(row,status="ASSIGNED",track_id=claims[0],ambiguous_track_ids=(),reason="source_bound_reviewed_part_and_instance_pixels")
        elif row.status=="ASSIGNED" and row.track_id in reviewed:
            support = reviewed[row.track_id]["whole_mask"][top:bottom,left:right]
            if not support.size or not support.any():
                row = replace(row,status="UNASSIGNED",track_id=None,reason="reviewed_instance_excludes_part")
        result.append(row)
    return result
