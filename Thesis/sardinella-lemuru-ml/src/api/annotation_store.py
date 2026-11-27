"""Learning views over the sole canonical annotation store.

No labels or images are stored here. Canonical COCO masks and stable class IDs
remain authoritative. This adapter exposes the fixed model taxonomy to training
and records small review/learning metadata in the same SQLite database.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock

import cv2
import numpy as np
from PIL import Image

from src.annotation.masks import segmentation_to_mask
from src.api.annotation_feedback import correction_report
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


class CanonicalDatabase:
    def __init__(self, canonical):
        self.canonical = canonical

    @contextmanager
    def _connection(self):
        # Canonical transactions serialize learning state with label revisions.
        with self.canonical.connection() as connection:
            connection.row_factory = sqlite3.Row
            yield connection


def _group_name(filename):
    stem = Path(filename).stem.casefold()
    return re.split(r"(?:_jpg|_jpeg|_png)?\.rf\.", stem)[0]


def annotation_view(annotation, classes, width, height, *, model_ids=False):
    """Native-coordinate editable projection; never reduce a complex mask."""
    result = deepcopy(annotation)
    category = classes.get(annotation.get("class_id"), {})
    model_id = category.get("model_class_id")
    if model_ids:
        if model_id not in SOURCE_CLASSES or category.get("source_name") != SOURCE_CLASSES[model_id]:
            return None
        result.update(class_id=model_id, class_name=SOURCE_CLASSES[model_id])
    else:
        result["class_name"] = category.get("name", annotation.get("class_name", "Unknown"))
    result["kind"] = category.get("kind", "other")
    result["fish_id"] = annotation["id"] if result["kind"] == "whole_fish" else annotation.get("parent_id")
    bbox = annotation.get("bbox") or [0, 0, 0, 0]
    result["bbox"] = [bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]]
    result.update(mask=None, contours=[], mask_complete=False)
    if model_ids:
        # Learning uses the lossless segmentation directly. Creating SVG
        # contours for every historical mask makes a small status request
        # needlessly rasterize the entire baseline (twice for manual labels).
        # Only the currently displayed review image needs editable contours.
        return result
    try:
        binary = segmentation_to_mask(annotation.get("segmentation"), height, width)
        contours, hierarchy = cv2.findContours(binary.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        result["contours"] = [c.reshape(-1, 2).tolist() for c in contours]
        if len(contours) == 1 and hierarchy is not None and hierarchy[0][0][3] == -1:
            points = contours[0].reshape(-1, 2).tolist()
            if len(points) >= 3:
                result.update(mask=points, mask_complete=True)
    except (TypeError, ValueError, cv2.error):
        pass
    return result


class AnnotationStore:
    """A verified-only view, plus metadata, using canonical label revisions."""
    def __init__(self, canonical):
        self.canonical = canonical
        self.database = CanonicalDatabase(canonical)
        self._lock = RLock()
        self._pixel_cache = {}
        self._baseline_cache = {}
        self._cache_key = None
        self._cache = None
        self._initialized = False

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            with self.database._connection() as db:
                # Existing schemas need only a WAL read, even while a long
                # import owns the writer. DDL no-ops still acquire write locks.
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='annotation_feedback_metadata'").fetchone()
                if not exists:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("CREATE TABLE IF NOT EXISTS annotation_feedback_metadata (key TEXT PRIMARY KEY,value_json TEXT NOT NULL)")
            self._initialized = True

    def metadata(self, key, default=None):
        self.initialize()
        with self.database._connection() as db:
            row = db.execute("SELECT value_json FROM annotation_feedback_metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_metadata(self, key, value):
        self.initialize()
        with self.database._connection() as db:
            db.execute("INSERT INTO annotation_feedback_metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                       (key, json.dumps(value, allow_nan=False)))
        self._cache_key = None

    def protect(self, image_id, reason):
        self.set_metadata("quarantine:" + image_id, str(reason))

    def baseline_profile(self):
        """Read the canonical dataset selection; keep no competing registry."""
        with self.database._connection() as db:
            row = db.execute("SELECT value FROM meta WHERE key='primary_learning_dataset'").fetchone()
        explicit = json.loads(row[0]) if row else None
        if hasattr(self.canonical, "datasets"):
            registry = self.canonical.datasets()
            primary_id = registry.get("primary_dataset_id")
            selected = next((d for d in registry.get("datasets", []) if d.get("id", d.get("dataset_id")) == primary_id), None)
            if selected:
                # The registry synthesizes a legacy entry for existing stores.
                # That is not an explicit baseline switch and must not bypass
                # the original source-fingerprint/idempotence checks.
                if primary_id == "v2-coco-v7" and explicit is None:
                    return None
                return dict(selected, dataset_id=primary_id, secondary_dataset_ids=[d.get("id", d.get("dataset_id")) for d in registry["datasets"] if d.get("id", d.get("dataset_id")) != primary_id])
        return explicit

    def _pixels(self, document):
        path = self.canonical.root / document["pixels_path"]
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = self._pixel_cache.get(key)
        if cached is None:
            raw = path.read_bytes()
            # Canonical artifact filenames are the content hash.
            digest = sha256(raw).hexdigest()
            if digest != path.stem:
                raise ValueError("Immutable annotation pixels have changed.")
            with Image.open(path) as opened:
                rgb = opened.convert("RGB")
                pixels = sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            cached = (str(path), digest, pixels)
            self._pixel_cache[key] = cached
        return cached

    def _baseline_identity(self, document, profile=None):
        baseline = document.get("baseline")
        if not baseline:
            metadata = document.get("metadata") or {}
            dataset = document.get("dataset_id") or metadata.get("dataset_id") or "feedback"
            group = document.get("group_id") or metadata.get("leakage_group_id") or metadata.get("group_id") or document["filename"]
            return str(dataset), _group_name(str(group))
        path = self.canonical.root / baseline["path"]
        key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        if key not in self._baseline_cache:
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != baseline["sha256"]:
                raise ValueError("Original manual baseline snapshot has changed.")
            data = json.loads(raw)
            self._baseline_cache[key] = {row["id"]: row for row in data["images"]}
        image = self._baseline_cache[key][baseline["source_image_id"]]
        extra = image.get("extra") or {}
        group = document.get("group_id") or baseline.get("group_id") or (document.get("metadata") or {}).get("leakage_group_id") or extra.get("leakage_group_id") or extra.get("specimen_id") or extra.get("group_id") or extra.get("name") or image["file_name"]
        dataset_id = baseline.get("dataset_id") or document.get("dataset_id") or (document.get("metadata") or {}).get("dataset_id") or ("v2-coco-v7" if profile else "manual:" + str(self.canonical.manual_source))
        return str(dataset_id), _group_name(str(group))

    def _snapshot(self):
        self.initialize()
        with self._lock:
            profile = self.baseline_profile()
            with self.database._connection() as db:
                key = (tuple(db.execute("SELECT COUNT(*),MAX(rowid) FROM revisions").fetchone()),
                       db.execute("SELECT value FROM meta WHERE key='classes_revision'").fetchone()[0],
                       tuple(db.execute("SELECT COUNT(*),MAX(rowid) FROM annotation_feedback_metadata").fetchone()), json.dumps(profile, sort_keys=True))
                # File integrity is checked again by the training exporter.
                if key == self._cache_key and self._cache is not None:
                    return deepcopy(self._cache)
                documents = [json.loads(row[0]) for row in db.execute("SELECT document FROM images ORDER BY id")]
                histories = defaultdict(list)
                for image_id, raw in db.execute("SELECT image_id,document FROM revisions ORDER BY revision"):
                    histories[image_id].append(json.loads(raw))
                metadata = {k: json.loads(v) for k, v in db.execute("SELECT key,value_json FROM annotation_feedback_metadata")}
            classes = {c["id"]: c for c in self.canonical.classes()["classes"]}
            rows = []
            for document in documents:
                try:
                    path, file_hash, pixel_hash = self._pixels(document)
                    dataset_id, group = self._baseline_identity(document, profile)
                except (OSError, ValueError, KeyError) as error:
                    path, file_hash, pixel_hash = "", "", document.get("image_sha256", "")
                    dataset_id, group = "corrupt", "corrupt:" + document["id"]
                    metadata["quarantine:" + document["id"]] = str(error)
                history = histories[document["id"]]
                first = history[0] if history else document
                predicted = next((r for r in history if r.get("automation") and any(a.get("source") == "automated" for a in r["annotations"])), None)
                if predicted is None:
                    predicted = next((r for r in history if any(a.get("source") == "automated" for a in r["annotations"])), None)
                source = "manual" if document.get("baseline") else ("human_corrected" if any(a.get("source") == "user" for a in document["annotations"]) else "ai")
                verified = document["status"] in {"approved", "manual_verified"}
                status = "manual" if document["status"] == "manual_verified" else ("corrected" if verified and source == "human_corrected" else "approved" if verified else "declined" if document["status"] == "rejected" else "pending")
                current_labels = [a for a in document["annotations"] if a.get("status") != "rejected"]
                original_labels = [a for a in first["annotations"] if a.get("status") != "rejected"]
                original_predictions = predicted["annotations"] if predicted else []
                model_version = (predicted or document).get("automation", {}).get("learning_model_version") or (predicted or document).get("automation", {}).get("model_version", "existing-detectors")
                review_info = metadata.get("review:" + document["id"], {})
                report = correction_report(original_predictions, current_labels, width=document["width"], height=document["height"]) if predicted and verified else None
                def convert(labels):
                    return [view for a in labels if (view := annotation_view(a, classes, document["width"], document["height"], model_ids=True)) is not None]
                source_split = document.get("split") or (document.get("metadata") or {}).get("split")
                split = {"valid": "val", "validation": "val", None: "train"}.get(source_split, source_split)
                protected_split = (document.get("metadata") or {}).get("protected_split")
                protected_split = {"valid": "val", "validation": "val"}.get(protected_split, protected_split)
                if source_split is None and profile and source == "manual" and dataset_id == profile.get("dataset_id"):
                    split = "unassigned"
                row = {"image_id": document["id"], "filename": document["filename"], "image_path": path,
                       "image_sha256": file_hash, "original_image_sha256": document.get("image_sha256"),
                       "pixel_sha256": pixel_hash, "width": document["width"], "height": document["height"],
                       "dataset_id": dataset_id, "group_id": group, "split": split, "protected_split": protected_split,
                       "source": source, "status": status, "annotations": convert(current_labels),
                       "original_annotations": convert(original_labels), "predictions": convert(original_predictions),
                       "canonical_annotations": current_labels, "canonical_predictions": original_predictions,
                       "revision": document["revision"], "model_version": model_version,
                       "corrections": report, "review_time_ms": review_info.get("review_time_ms"),
                       "review_reason": review_info.get("reason"), "reviewed_at": review_info.get("reviewed_at"),
                       "updated_at": document.get("updated_at"), "quarantined": False}
                selected = not profile or (dataset_id == profile.get("dataset_id") if source == "manual" else dataset_id not in profile.get("secondary_dataset_ids", []))
                row["source_dataset_selected"] = selected
                row["selected_for_learning"] = selected and (not profile or (profile.get("status", "ready") == "ready" and profile.get("reference_eligible", True)))
                explicit_review = source == "manual" and document["status"] == "approved"
                row["training_verified_after_import"] = explicit_review
                row["feedback_eligible"] = explicit_review and row["selected_for_learning"]
                row["training_eligible"] = not profile or source != "manual" or bool(profile.get("training_certified", True)) or explicit_review
                if "quarantine:" + document["id"] in metadata:
                    row.update(quarantined=True, quarantine_reason=metadata["quarantine:" + document["id"]])
                unsupported = [a for a in current_labels if classes.get(a["class_id"], {}).get("kind") != "whole_fish"
                    and (classes.get(a["class_id"], {}).get("model_class_id") not in SOURCE_CLASSES
                         or classes.get(a["class_id"], {}).get("source_name") != SOURCE_CLASSES.get(classes.get(a["class_id"], {}).get("model_class_id")))]
                if unsupported:
                    row.update(quarantined=True, quarantine_reason="Annotation classes are outside the fixed 12-class model mapping; labels were preserved and excluded from model learning.")
                if not profile and source != "manual" and metadata.get("baseline_bootstrap", {}).get("state") in {"indexing", "errors", "source_changed"}:
                    row.update(quarantined=True, quarantine_reason="Original baseline identities are not fully indexed; feedback is saved and held out of learning until indexing succeeds.")
                rows.append(row)
            # Reserve evaluation identity even for unverified or declined copies.
            held_pixels = {r["pixel_sha256"] for r in rows if r["split"] in {"val", "test"} or r["protected_split"] in {"val", "test"}}
            held_groups = {r["group_id"] for r in rows if r["split"] in {"val", "test"} or r["protected_split"] in {"val", "test"}}
            by_pixels = defaultdict(list)
            for row in rows:
                by_pixels[row["pixel_sha256"]].append(row)
                if row["split"] == "train" and (row["pixel_sha256"] in held_pixels or row["group_id"] in held_groups):
                    row.update(quarantined=True, quarantine_reason="Image or source group belongs to validation/test.")
            for copies in by_pixels.values():
                eligible = [r for r in copies if r["selected_for_learning"] and not r["quarantined"] and r["status"] in {"approved", "corrected", "manual"}]
                # Prefer the permanent manual baseline over feedback copies.
                eligible.sort(key=lambda r: (r["source"] != "manual", r["image_id"]))
                if len(eligible) > 1:
                    def label_signature(r):
                        labels = r["original_annotations"] if r["source"] == "manual" else r["annotations"]
                        return sorted((a["class_id"], sha256(segmentation_to_mask(a.get("segmentation"), r["height"], r["width"]).tobytes()).hexdigest()) for a in labels)
                    signatures = {json.dumps(label_signature(r)) for r in eligible}
                    manual = [r for r in eligible if r["source"] == "manual"]
                    # A contradictory feedback copy cannot displace permanent
                    # manual truth. Conflicting manual baselines require review.
                    excluded = [r for r in eligible if r["source"] != "manual"] if len(signatures) > 1 and len(manual) == 1 else eligible if len(signatures) > 1 else eligible[1:]
                    for row in excluded:
                        row.update(quarantined=True, quarantine_reason="Contradictory verified labels for identical pixels." if len(signatures) > 1 else "Duplicate verified image pixels.")
            self._cache_key, self._cache = key, deepcopy(rows)
            return rows

    def all_examples(self):
        return self._snapshot()

    def verified_examples(self):
        return [r for r in self._snapshot() if r["status"] in {"approved", "corrected", "manual"} and not r["quarantined"] and r["selected_for_learning"]]

    def get(self, image_id):
        return next((r for r in self._snapshot() if r["image_id"] == image_id), None)

    def stats(self):
        rows = self._snapshot()
        verified = [r for r in rows if r["status"] in {"manual", "approved", "corrected"} and not r["quarantined"] and r["selected_for_learning"]]
        reviewed_by_pixel = {}
        for row in rows:
            if row["source"] != "manual" and row["selected_for_learning"] and not row["quarantined"] and row["status"] in {"approved", "corrected", "declined"}:
                reviewed_by_pixel.setdefault(row["pixel_sha256"], row)
        reviewed = list(reviewed_by_pixel.values())
        accepted = [r for r in reviewed if r["status"] in {"approved", "corrected"}]
        counts, classes = Counter(), Counter()
        reports = [r["corrections"] for r in accepted if r["corrections"]]
        for report in reports:
            counts.update(report["counts"])
            classes.update(report["corrected_classes"])
        unchanged = sum(bool(r["corrections"]) and r["corrections"]["counts"].get("corrected_annotations", 0) == 0 for r in accepted)
        times = [r["review_time_ms"] for r in reviewed if isinstance(r["review_time_ms"], (int, float))]
        def average(field):
            values = [r[field] for r in reports if r.get(field) is not None]
            return sum(values) / len(values) if values else None
        return {"verified_examples": len(verified), "approved_images": len(accepted),
                "primary_baseline": self.baseline_profile(), "retained_secondary_examples": sum(not r["source_dataset_selected"] for r in rows),
                "manual_baseline_images": sum(r["source"] == "manual" for r in verified),
                "corrected_annotations": counts["corrected_annotations"], "corrected_masks": counts["mask_correction"],
                "corrected_classes": dict(classes), "common_mistakes": dict(counts),
                "approved_without_edit_rate": unchanged / len(reviewed) if reviewed else None,
                "declined_rate": sum(r["status"] == "declined" for r in reviewed) / len(reviewed) if reviewed else None,
                "avg_review_time_ms": sum(times) / len(times) if times else None,
                "average_corrections_per_image": counts["corrected_annotations"] / len(accepted) if accepted else None,
                "mask_correction_frequency": counts["mask_correction"] / sum(r["predictions"] for r in reports) if sum(r["predictions"] for r in reports) else None,
                "review_detection_precision": average("detection_precision"), "review_detection_recall": average("detection_recall"),
                "review_mask_iou": average("mean_mask_iou"), "review_class_accuracy": average("class_accuracy"),
                "missing_annotation_rate": counts["missing_annotation"] / sum(r["verified_annotations"] for r in reports) if sum(r["verified_annotations"] for r in reports) else None,
                "quarantined_examples": sum(r["quarantined"] for r in rows),
                "metric_basis": "Complete reviewed annotation sets vs original predictions; independent model performance is reported only by candidate evaluation."}
