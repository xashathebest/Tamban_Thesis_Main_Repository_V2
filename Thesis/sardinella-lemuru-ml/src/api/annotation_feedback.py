"""Measured differences between a complete prediction set and human verification.

This is review evidence, not an independent estimate of generalization accuracy.
Masks are compared as pixels, retaining COCO holes and disconnected regions.
"""
from __future__ import annotations

from collections import Counter
import math

import numpy as np

from src.annotation.masks import segmentation_to_mask


def _mask(annotation, height, width):
    segmentation = annotation.get("segmentation")
    if segmentation is None and annotation.get("mask"):
        segmentation = [[v for point in annotation["mask"] for v in point]]
    try:
        return segmentation_to_mask(segmentation, height, width) != 0
    except (TypeError, ValueError, OverflowError):
        return None


def correction_report(predictions: list[dict], verified: list[dict], *, width: int, height: int) -> dict:
    """Use stable object identities; do not guess ownership or match by class.

    An object removed by the reviewer is an extra prediction. It is a duplicate
    only when another original mask of that class and parent overlaps it heavily.
    """
    previous = {str(a["id"]): a for a in predictions}
    final = {str(a["id"]): a for a in verified}
    counts = Counter()
    corrected_classes = Counter()
    changes = []
    ious, confidences = [], []
    independent_correct = 0
    for object_id, original in previous.items():
        original_mask = _mask(original, height, width)
        replacement = final.get(object_id)
        if replacement is None:
            duplicate = False
            if original_mask is not None:
                for other_id, other in previous.items():
                    if other_id == object_id or other.get("class_id") != original.get("class_id") or other.get("parent_id") != original.get("parent_id"):
                        continue
                    other_mask = _mask(other, height, width)
                    if other_mask is not None:
                        union = np.count_nonzero(original_mask | other_mask)
                        if union and np.count_nonzero(original_mask & other_mask) / union >= .9:
                            duplicate = True
                            break
            kind = "duplicate_annotation" if duplicate else "extra_annotation"
            counts[kind] += 1
            changes.append({"id": object_id, "kind": kind, "before_class": original.get("class_id")})
            continue
        errors = []
        if replacement.get("class_id") != original.get("class_id"):
            counts["class_correction"] += 1
            key = f"{original.get('class_id')}→{replacement.get('class_id')}"
            corrected_classes[key] += 1
            errors.append("class_correction")
        # Support the learning view and canonical COCO representations.
        old_parent = original.get("parent_id", original.get("fish_id"))
        new_parent = replacement.get("parent_id", replacement.get("fish_id"))
        if old_parent != new_parent:
            counts["ownership_correction"] += 1
            errors.append("ownership_correction")
        final_mask = _mask(replacement, height, width)
        if original_mask is None and final_mask is not None:
            counts["missing_mask"] += 1
            counts["mask_correction"] += 1
            errors.append("missing_mask")
        elif original_mask is not None and final_mask is not None:
            union = np.count_nonzero(original_mask | final_mask)
            iou = float(np.count_nonzero(original_mask & final_mask) / union) if union else 1.0
            ious.append(iou)
            if not np.array_equal(original_mask, final_mask):
                counts["mask_correction"] += 1
                errors.append("mask_boundary")
        elif original_mask is not None:
            counts["mask_correction"] += 1
            errors.append("mask_removed")
        if errors:
            counts["corrected_annotations"] += 1
            changes.append({"id": object_id, "kind": errors, "before_class": original.get("class_id"), "after_class": replacement.get("class_id")})
        else:
            independent_correct += 1
        confidence = original.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence) and 0 <= confidence <= 1:
            confidences.append({"confidence": float(confidence), "accepted_unchanged": not errors})
    for object_id, added in final.items():
        if object_id not in previous:
            counts["missing_annotation"] += 1
            changes.append({"id": object_id, "kind": "missing_annotation", "after_class": added.get("class_id")})
    counts["corrected_annotations"] += counts["missing_annotation"] + counts["extra_annotation"] + counts["duplicate_annotation"]
    removed = counts["extra_annotation"] + counts["duplicate_annotation"]
    matched = len(previous) - removed
    return {
        "counts": dict(counts), "changes": changes,
        "corrected_classes": dict(corrected_classes),
        "predictions": len(predictions), "verified_annotations": len(verified),
        "accepted_unchanged": independent_correct,
        "mean_mask_iou": sum(ious) / len(ious) if ious else None,
        "detection_precision": matched / len(previous) if previous else None,
        "detection_recall": matched / len(final) if final else None,
        "class_accuracy": (matched - counts["class_correction"]) / matched if matched else None,
        "confidence_observations": confidences,
        "basis": "complete_human_verified_set_vs_original_prediction; stable_object_ids; not_held_out_model_accuracy",
    }
