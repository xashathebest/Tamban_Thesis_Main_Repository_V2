"""Frame-owned MobileSAM candidates; production grading remains independent."""
from __future__ import annotations

import hashlib
import os
from time import perf_counter

import cv2
import numpy as np


BACKENDS = {"grabcut", "mobilesam_experimental", "geometry_only"}


def segmentation_backend(value=None):
    name = str(value if value is not None else os.getenv("SEGMENTATION_BACKEND", "grabcut")).strip().lower()
    if name not in BACKENDS:
        raise ValueError("Segmentation backend must be grabcut, mobilesam_experimental or geometry_only.")
    return name


def inspection_segmentation_backend(value=None):
    """Automatic inspection uses SAM; explicit operators can select fallback."""
    return segmentation_backend(value if value is not None else os.getenv("SEGMENTATION_BACKEND", "mobilesam_experimental"))


class ExperimentalFrameSegmentation:
    def __init__(self, frame, frame_id, *, service=None):
        self.frame, self.frame_id = frame, frame_id
        self.service = service
        self.parents = []
        self.parts = []
        self.trusted_parts = []
        self.reviewed_instances = {}
        self.reviewed_ownership = {}
        self.frame_key = None
        self.candidates, self.ownership = {}, {}
        self.shadow = {"applied_to_grading": False, "reason": "No candidate analysis has run."}
        self._generation_key = None
        self._reports = {}
        self._diagnostics = {"backend": "mobilesam_experimental", "experimental": True,
                             "embedding_calls": 0, "prompt_calls": 0, "segmentation_ms": 0.0,
                             "used_for_grading": False, "validation_status": "Not validated"}

    def prepare(self, parents, parts=(), associations=None, *, trusted_parts=(), reviewed_instances=None):
        from src.inference.mask_ownership import validate_candidate_masks, shadow_mask_associations, trusted_prompt_points
        parents = list(parents)
        parts = list(parts)
        self.trusted_parts = list(trusted_parts)
        self.reviewed_instances = dict(reviewed_instances or {})
        self.reviewed_ownership = {}
        point_prompts = {p.track_id: trusted_prompt_points(p.track_id, self.trusted_parts, self.frame.shape) for p in parents}
        generation_key = (hashlib.blake2b(memoryview(np.ascontiguousarray(self.frame)), digest_size=16).hexdigest(),
                          tuple((p.track_id, tuple(p.bbox),
                                 tuple(map(tuple, point_prompts[p.track_id]["point_coords"])),
                                 tuple(point_prompts[p.track_id]["point_labels"])) for p in parents))
        if self._generation_key != generation_key:
            self.parents = parents
            self.frame_key = f"{self.frame_id}:{generation_key[0]}"
            self.candidates, self._reports = {}, {}
            started = perf_counter()
            if parents:
                try:
                    if self.service is None:
                        from src.inference.mobilesam_backend import get_mobilesam_service
                        self.service = get_mobilesam_service()
                    with self.service.open_frame(self.frame, self.frame_key) as session:
                        for parent in parents:
                            # Detector rectangles are box prompts. Their centers
                            # are not invented anatomical positive/negative points.
                            points = point_prompts[parent.track_id]
                            options = ({"point_coords": points["point_coords"], "point_labels": points["point_labels"]}
                                       if points["point_coords"] else {})
                            try:
                                self.candidates[parent.track_id] = session.predict(
                                    parent.track_id, parent.bbox, detection_version=generation_key[0], **options)
                                self.candidates[parent.track_id]["reviewed_point_prompts"] = points
                            except Exception as error:
                                self.candidates[parent.track_id] = self._unavailable(error)
                        self._diagnostics.update(session.diagnostics())
                except Exception as error:
                    for parent in parents:
                        self.candidates.setdefault(parent.track_id, self._unavailable(error))
                    self._diagnostics.update(status="unavailable", reason=str(error), error_type=type(error).__name__)
            self._diagnostics["segmentation_ms"] = round((perf_counter() - started) * 1000, 3)
            self._generation_key = generation_key
        self.parts = list(parts)
        try:
            self.ownership = validate_candidate_masks(self.candidates, parents, self.parts,
                                                      associations=associations, frame_shape=self.frame.shape,
                                                      expected_frame_key=self.frame_key)
            self.shadow = shadow_mask_associations(self.candidates, self.ownership, parents, parts)
            reviewed_candidates = {identity: {"mask": row["whole_mask"], "parent_id": identity,
                "bbox_global": next(p.bbox for p in parents if p.track_id == identity),
                "provenance": {"frame_key": self.frame_key, "coordinate_space": "original_frame",
                    "mask_shape": list(self.frame.shape[:2]), "source": "reviewed_native_instance_mask",
                    "parent_id": identity,
                    "original_bbox_global": list(next(p.bbox for p in parents if p.track_id == identity)),
                    "validation_provenance": row.get("validation_provenance")}}
                for identity, row in self.reviewed_instances.items()}
            self.reviewed_ownership = (validate_candidate_masks(
                {**self.candidates, **reviewed_candidates}, parents, self.parts, associations=associations,
                frame_shape=self.frame.shape, expected_frame_key=self.frame_key) if reviewed_candidates else {})
        except Exception as error:
            # Optional mask diagnostics must not discard the original weighted
            # verdict if an ownership validator cannot process a candidate.
            self.ownership = {p.track_id: {"status": "unavailable", "engineering_checks_passed": False,
                "ownership_validated": False, "approved_for_grading": False,
                "reasons": ["Mask ownership processing failed; candidate withheld."],
                "error_type": type(error).__name__} for p in parents}
            self.shadow = {"applied_to_grading": False, "reason": "Ownership validation unavailable."}
        self._reports.clear()

    @staticmethod
    def _unavailable(error):
        return {"status": "unavailable", "mask": None, "reason": "MobileSAM inference unavailable.",
                "error_type": type(error).__name__, "detail": str(error), "score": None}

    def is_current(self):
        # The shared embedding depends on every source pixel, including pixels
        # outside a particular fish ROI. Never reuse it after an in-place edit.
        return (self._generation_key is not None and self._generation_key[0] ==
                hashlib.blake2b(memoryview(np.ascontiguousarray(self.frame)), digest_size=16).hexdigest())

    def get(self, parent_id, bounds):
        reviewed = self.reviewed_instances.get(parent_id)
        if reviewed is not None and self.is_current() and self.reviewed_ownership.get(parent_id, {}).get("engineering_checks_passed"):
            native = reviewed["whole_mask"]
            local = native[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
            x, y, width, height = cv2.boundingRect(native.astype(np.uint8))
            return local, {"source": "reviewed_native_instance_mask", "status": "reviewed_for_features",
                "measurement_validated": True, "ownership_validated": True,
                "validation_provenance": reviewed["validation_provenance"], "parent_track_id": parent_id,
                "coordinate_space": "crop_local_native_pixels", "frame_id": self.frame_id,
                "full_frame_foreground_bbox": [x,y,x+width,y+height], "full_frame_foreground_pixels": int(native.sum()),
                "native_frame_shape": list(native.shape), "full_frame_native_mask": True,
                "sampling": {"estimated": False, "native_output_shape": list(local.shape)},
                "crop_bounds": [bounds.x1,bounds.y1,bounds.x2,bounds.y2]}
        candidate = self.candidates.get(parent_id, {})
        ownership = self.ownership.get(parent_id, {})
        mask = candidate.get("mask")
        current = self.is_current()
        usable = current and ownership.get("engineering_checks_passed") is True
        if not isinstance(mask, np.ndarray) or mask.shape != self.frame.shape[:2] or not usable:
            local = None
        else:
            local = np.asarray(mask[bounds.y1:bounds.y2, bounds.x1:bounds.x2], dtype=bool)
        metadata = {"source": "mobilesam_experimental_candidate", "status": "estimated_candidate" if local is not None else "unavailable",
            "reason": "; ".join(str(reason) for reason in ownership.get("reasons", [])) or candidate.get("reason") or "Experimental candidate; ownership is not independently validated.",
            "backend": "mobilesam_experimental", "experimental": True, "ownership_validated": False,
            "parent_isolation_reliable": usable, "parent_isolation_reasons": ownership.get("reasons", []),
            "measurement_validated": False, "mask_validated_for_cracks": False, "approved_for_grading": False,
            "sampling": {"mode": "mobilesam_candidate", "estimated": True,
                         "native_shape": list(self.frame.shape[:2]),
                         "native_output_shape": [bounds.height, bounds.width], "native_boundary_validated": False},
            "candidate_provenance": candidate.get("provenance", {}), "ownership": ownership,
            "full_frame_foreground_bbox": ownership.get("metrics", {}).get("foreground_bbox"),
            "full_frame_foreground_pixels": ownership.get("metrics", {}).get("foreground_pixels"),
            "native_frame_shape": list(self.frame.shape[:2]), "full_frame_native_mask": True,
            "crop_foreground_pixels": int(local.sum()) if local is not None else 0,
            "frame_id": self.frame_id, "parent_track_id": parent_id,
            "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
            "coordinate_space": "crop_local_native_pixels", "segmentation_ms": 0.0}
        if not current:
            metadata.update(reason="Source frame changed; recompute candidates before reuse.", stale_source_frame=True,
                            parent_isolation_reliable=False)
        return local, metadata

    def body_mask(self, parent_id, bounds):
        from src.inference.mask_ownership import body_support_mask
        if not self.is_current():
            return None, {"source": "unavailable", "validated": False, "reason": "Source frame changed; Body pixels withheld."}
        reviewed = self.reviewed_instances.get(parent_id)
        if reviewed is not None and self.reviewed_ownership.get(parent_id, {}).get("engineering_checks_passed"):
            return reviewed["body_mask"][bounds.y1:bounds.y2,bounds.x1:bounds.x2], {
                "source": "reviewed_native_body_mask", "validated": True,
                "body_region_validated": reviewed.get("body_region_validated") is True,
                "expected_parent_id": parent_id, "validation_provenance": reviewed["validation_provenance"]}
        mask, metadata = body_support_mask(parent_id, self.candidates.get(parent_id, {}),
                                          self.ownership.get(parent_id, {}), self.trusted_parts, self.frame.shape)
        if mask is None:
            return None, metadata
        return mask[bounds.y1:bounds.y2, bounds.x1:bounds.x2], metadata

    def report(self, parent_id):
        if not self.is_current():
            return {"backend": "mobilesam_experimental", "experimental": True, "status": "unavailable",
                    "ownership_status": "unavailable", "validation_status": "Not validated", "used_for_grading": False,
                    "parent_track_id": parent_id, "frame_id": self.frame_id,
                    "reasons": ["Source frame changed or no candidates prepared; recompute before reuse."]}
        if parent_id in self._reports:
            return self._reports[parent_id]
        candidate = self.candidates.get(parent_id, {})
        ownership = self.ownership.get(parent_id, {})
        mask = candidate.get("mask")
        def polygons(binary, vertex_budget=4096):
            contours = []
            found, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for item in sorted(found, key=cv2.contourArea, reverse=True)[:64]:
                polygon = cv2.approxPolyDP(item, 1.0, True).reshape(-1, 2)
                if len(polygon) >= 3 and len(polygon) <= vertex_budget:
                    contours.append(polygon.astype(int).tolist())
                    vertex_budget -= len(polygon)
            return contours
        contours, conflicts = [], []
        if isinstance(mask, np.ndarray) and mask.shape == self.frame.shape[:2]:
            contours = polygons(mask)
            overlap = np.zeros(mask.shape, dtype=bool)
            for neighbor_id in ownership.get("conflicting_parent_ids", []):
                neighbor = self.candidates.get(neighbor_id, {}).get("mask")
                if isinstance(neighbor, np.ndarray) and neighbor.shape == mask.shape:
                    overlap |= (mask != 0) & (neighbor != 0)
            if overlap.any():
                conflicts = polygons(overlap, vertex_budget=2048)
        own_shadow = {**self.shadow,
            "parts": [row for row in self.shadow.get("parts", []) if row.get("proposed_track_id") == parent_id
                      or any(support.get("parent_id") == parent_id for support in row.get("supports", []))],
            "parents": {parent_id: self.shadow.get("parents", {}).get(parent_id, {})}}
        reasons = list(ownership.get("reasons") or [])
        if not reasons:
            if ownership.get("engineering_checks_passed") is True:
                reasons = ["Engineering checks passed; candidate remains unvalidated for anatomical ownership and grading."]
            else:
                reasons = [candidate.get("reason") or "Candidate mask ownership checks unavailable; candidate remains withheld."]
        report = {"backend": "mobilesam_experimental", "experimental": True,
            "status": candidate.get("status", "unavailable"),
            "ownership_status": ownership.get("status", "unavailable"),
            "engineering_checks_passed": ownership.get("engineering_checks_passed", False),
            "validation_status": "Not validated", "used_for_grading": False,
            "parent_track_id": parent_id, "frame_id": self.frame_id,
            "source_parent_bbox": next((list(parent.bbox) for parent in self.parents if parent.track_id == parent_id), None),
            "mask_score_unvalidated": candidate.get("score"),
            "checkpoint_sha256": candidate.get("provenance", {}).get("checkpoint_sha256"),
            "reviewed_point_prompts": candidate.get("reviewed_point_prompts", {}),
            "reasons": reasons,
            "ownership": ownership, "provenance": candidate.get("provenance", {}),
            "shadow_association": own_shadow,
            "mask_overlay": {"coordinate_space": "original_frame", "frame_id": self.frame_id,
                             "frame_width_px": self.frame.shape[1], "frame_height_px": self.frame.shape[0],
                             "contours": contours, "conflict_contours": conflicts, "candidate_only": True},
            "timings": {"embedding_ms": candidate.get("embedding_ms", candidate.get("shared_embedding_ms")), "prompt_ms": candidate.get("prompt_ms")}}
        if candidate.get("detail") or candidate.get("error_type"):
            report["backend_error"] = {"type": candidate.get("error_type"), "detail": candidate.get("detail")}
        self._reports[parent_id] = report
        return report

    def diagnostics(self):
        return {**self._diagnostics, "candidate_count": len(self.candidates),
                "engineering_checks_passed": sum(v.get("engineering_checks_passed") is True for v in self.ownership.values()),
                "applied_to_grading": False}
