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


class ExperimentalFrameSegmentation:
    def __init__(self, frame, frame_id, *, service=None):
        self.frame, self.frame_id = frame, frame_id
        self.service = service
        self.parents = []
        self.parts = []
        self.frame_key = None
        self.candidates, self.ownership = {}, {}
        self.shadow = {"applied_to_grading": False, "reason": "No candidate analysis has run."}
        self._generation_key = None
        self._reports = {}
        self._diagnostics = {"backend": "mobilesam_experimental", "experimental": True,
                             "embedding_calls": 0, "prompt_calls": 0, "segmentation_ms": 0.0,
                             "used_for_grading": False, "validation_status": "Not validated"}

    def prepare(self, parents, parts=(), associations=None):
        from src.inference.mask_ownership import validate_candidate_masks, shadow_mask_associations
        parents = list(parents)
        generation_key = (hashlib.blake2b(memoryview(np.ascontiguousarray(self.frame)), digest_size=16).hexdigest(),
                          tuple((p.track_id, tuple(p.bbox)) for p in parents))
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
                            self.candidates[parent.track_id] = session.predict(
                                parent.track_id, parent.bbox, detection_version=generation_key[0])
                        self._diagnostics.update(session.diagnostics())
                except Exception as error:
                    self.candidates = {p.track_id: {"status": "unavailable", "mask": None,
                        "reason": "MobileSAM inference unavailable.", "error_type": type(error).__name__,
                        "detail": str(error), "score": None} for p in parents}
                    self._diagnostics.update(status="unavailable", reason=str(error), error_type=type(error).__name__)
            self._diagnostics["segmentation_ms"] = round((perf_counter() - started) * 1000, 3)
            self._generation_key = generation_key
        self.parts = list(parts)
        self.ownership = validate_candidate_masks(self.candidates, parents, self.parts,
                                                  associations=associations, frame_shape=self.frame.shape,
                                                  expected_frame_key=self.frame_key)
        self.shadow = shadow_mask_associations(self.candidates, self.ownership, parents, parts)
        self._reports.clear()

    def get(self, parent_id, bounds):
        candidate = self.candidates.get(parent_id, {})
        ownership = self.ownership.get(parent_id, {})
        mask = candidate.get("mask")
        usable = ownership.get("engineering_checks_passed") is True
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
            "frame_id": self.frame_id, "parent_track_id": parent_id,
            "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
            "coordinate_space": "crop_local_native_pixels", "segmentation_ms": 0.0}
        return local, metadata

    def body_mask(self, parent_id, bounds):
        from src.inference.mask_ownership import body_support_mask
        mask, metadata = body_support_mask(parent_id, self.candidates.get(parent_id, {}),
                                          self.ownership.get(parent_id, {}), self.parts, self.frame.shape)
        if mask is None:
            return None, metadata
        return mask[bounds.y1:bounds.y2, bounds.x1:bounds.x2], metadata

    def report(self, parent_id):
        if parent_id in self._reports:
            return self._reports[parent_id]
        candidate = self.candidates.get(parent_id, {})
        ownership = self.ownership.get(parent_id, {})
        mask = candidate.get("mask")
        contours = []
        if isinstance(mask, np.ndarray) and mask.shape == self.frame.shape[:2]:
            found, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for item in sorted(found, key=cv2.contourArea, reverse=True)[:64]:
                polygon = cv2.approxPolyDP(item, 1.0, True).reshape(-1, 2)
                if len(polygon) >= 3:
                    contours.append(polygon[:2048].astype(int).tolist())
        report = {"backend": "mobilesam_experimental", "experimental": True,
            "status": candidate.get("status", "unavailable"),
            "ownership_status": ownership.get("status", "unavailable"),
            "engineering_checks_passed": ownership.get("engineering_checks_passed", False),
            "validation_status": "Not validated", "used_for_grading": False,
            "parent_track_id": parent_id, "frame_id": self.frame_id,
            "source_parent_bbox": next((list(parent.bbox) for parent in self.parents if parent.track_id == parent_id), None),
            "mask_score_unvalidated": candidate.get("score"),
            "reasons": ownership.get("reasons", []) or [candidate.get("reason", "Candidate unavailable.")],
            "ownership": ownership, "provenance": candidate.get("provenance", {}),
            "shadow_association": self.shadow,
            "mask_overlay": {"coordinate_space": "original_frame", "frame_id": self.frame_id,
                             "frame_width_px": self.frame.shape[1], "frame_height_px": self.frame.shape[0],
                             "contours": contours, "candidate_only": True},
            "timings": {"embedding_ms": candidate.get("embedding_ms", candidate.get("shared_embedding_ms")), "prompt_ms": candidate.get("prompt_ms")}}
        self._reports[parent_id] = report
        return report

    def diagnostics(self):
        return {**self._diagnostics, "candidate_count": len(self.candidates),
                "engineering_checks_passed": sum(v.get("engineering_checks_passed") is True for v in self.ownership.values()),
                "applied_to_grading": False}
