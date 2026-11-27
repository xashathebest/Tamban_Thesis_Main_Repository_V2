"""Transactional annotation revisions and immutable local dataset artifacts.

The external manual dataset is read only. Images, original COCO bytes, mask
PNGs, and every saved document remain accessible under the workspace root.
SQLite is the authoritative revision index; JSON files are recovery artifacts.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from threading import RLock
import uuid
import zipfile

import cv2
import numpy as np

from src.annotation.masks import coco_segmentation_to_mask, mask_to_rle, segmentation_to_mask, yolo_polygon
from src.preprocessing.dataset_utils import project_root
from src.preprocessing.audit_v7_exports import SOURCE_NAME_TO_ID

SPLITS = ("train", "valid", "test")
KINDS = {"whole_fish", "anatomy", "quality", "other"}
OBJECT_STATUSES = {"unreviewed", "corrected", "approved", "rejected", "manual_verified"}
IMAGE_STATUSES = OBJECT_STATUSES
COLORS = ("#ff595e", "#ffca3a", "#8ac926", "#1982c4", "#6a4c93", "#f9844a", "#43aa8b", "#f15bb5", "#00bbf9", "#9b5de5", "#90be6d", "#f8961e", "#4d908e", "#f94144")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pixel_bbox(mask):
    """Exact binary bounds without allocating coordinates for every pixel."""
    x, y, width, height = cv2.boundingRect(mask)
    if not width or not height:
        raise ValueError("Segmentation mask has no foreground pixels.")
    return [x, y, width, height]


def _mask_intersection(first, second, first_bbox, second_bbox):
    """Count exact overlapping pixels only within intersecting native bounds."""
    ax, ay, aw, ah = first_bbox
    bx, by, bw, bh = second_bbox
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if left >= right or top >= bottom:
        return 0
    return int(np.count_nonzero(first[top:bottom, left:right] & second[top:bottom, left:right]))


class AnnotationError(ValueError):
    status_code = 422


class RevisionConflict(AnnotationError):
    status_code = 409


class NotFound(AnnotationError):
    status_code = 404


def _metadata(name):
    if name in SOURCE_NAME_TO_ID:
        elements = name.split("_")
        return {"kind": "anatomy", "region": elements[-1].lower(),
                "quality_grade": "_".join(elements[:-1]), "model_class_id": SOURCE_NAME_TO_ID[name]}
    return {"kind": "other", "region": None, "quality_grade": None, "model_class_id": None}


class AnnotationStore:
    def __init__(self, root: Path | str | None = None, manual_source: Path | str | None = None):
        self.root = Path(root or os.getenv("FISH_ANNOTATION_ROOT") or project_root() / "dataset" / "annotation_workspace").resolve()
        self.manual_source = Path(manual_source or project_root() / "Dried Fish Quality Grading.v7i.coco-segmentation").resolve()
        self._lock, self._initialized = RLock(), False

    def _initialize(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            for name in ("images", "pixels", "masks", "baselines", "revisions", "exports"):
                (self.root / name).mkdir(exist_ok=True)
            with sqlite3.connect(self.root / "annotations.sqlite3") as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS classes (id INTEGER PRIMARY KEY,document TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY,content_hash TEXT NOT NULL,document TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS revisions (image_id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,
                        created_at TEXT NOT NULL,PRIMARY KEY(image_id,revision));
                    CREATE TABLE IF NOT EXISTS imports (import_key TEXT PRIMARY KEY,image_id TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS images_hash ON images(content_hash);
                """)
                if db.execute("SELECT 1 FROM meta WHERE key='classes_revision'").fetchone() is None:
                    categories = []
                    for split in SPLITS:
                        path = self.manual_source / split / "_annotations.coco.json"
                        if path.is_file():
                            categories = json.loads(path.read_bytes()).get("categories", [])
                            break
                    # Keep original stable category IDs; source_model IDs are separate.
                    for category in categories:
                        class_id, name = int(category["id"]), str(category["name"])
                        metadata = _metadata(name)
                        entry = {"id": class_id, "name": name, "source_name": name,
                                 "color": COLORS[class_id % len(COLORS)], "active": category.get("supercategory") != "none", **metadata}
                        db.execute("INSERT INTO classes VALUES (?,?)", (class_id, _json(entry)))
                    class_id = max([int(c["id"]) for c in categories], default=-1) + 1
                    fish = {"id": class_id, "name": "Whole fish", "source_name": "Whole fish", "kind": "whole_fish",
                            "color": "#00e5ff", "active": True, "region": None, "quality_grade": None, "model_class_id": None}
                    db.execute("INSERT INTO classes VALUES (?,?)", (class_id, _json(fish)))
                    db.execute("INSERT INTO meta VALUES ('classes_revision','1')")
            self._initialized = True

    @contextmanager
    def _db(self, write=False):
        self._initialize()
        with self._lock:
            db = sqlite3.connect(self.root / "annotations.sqlite3", timeout=30)
            db.execute("PRAGMA synchronous=FULL")
            try:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def _artifact(self, directory, data: bytes, suffix):
        digest = hashlib.sha256(data).hexdigest()
        relative = f"{directory}/{digest}{suffix}"
        path = self.root / relative
        # Hard-link publication exposes either the whole fsynced file or nothing.
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise AnnotationError(f"Immutable artifact is corrupt: {relative}")
        else:
            descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if path.read_bytes() != data:
                        raise AnnotationError("Immutable artifact hash collision or corruption.")
            finally:
                Path(temporary).unlink(missing_ok=True)
        return relative

    def classes(self):
        with self._db() as db:
            return {"classes": [json.loads(row[0]) for row in db.execute("SELECT document FROM classes ORDER BY id")],
                    "revision": int(db.execute("SELECT value FROM meta WHERE key='classes_revision'").fetchone()[0])}

    def datasets(self):
        from src.annotation.primary_baseline import datasets
        return datasets(self)

    def import_primary_zip(self, path, *, dataset_id=None, name="Fish Annotations Cleaned"):
        from src.annotation.primary_baseline import import_primary_zip
        return import_primary_zip(self, path, dataset_id=dataset_id, name=name)

    def _change_class(self, class_id, changes, create=False):
        if not isinstance(changes, dict):
            raise AnnotationError("Class details must be an object.")
        with self._db(True) as db:
            entries = [json.loads(row[0]) for row in db.execute("SELECT document FROM classes ORDER BY id")]
            if create:
                next_row = db.execute("SELECT value FROM meta WHERE key='next_class_id'").fetchone()
                class_id = max(max([e["id"] for e in entries], default=-1) + 1, int(next_row[0]) if next_row else 0)
                db.execute("INSERT OR REPLACE INTO meta VALUES ('next_class_id',?)", (str(class_id + 1),))
                entry = {"id": class_id, "name": "", "kind": "anatomy", "color": COLORS[class_id % len(COLORS)],
                         "active": True, "source_name": None, "model_class_id": None, "region": None, "quality_grade": None}
            else:
                entry = next((deepcopy(e) for e in entries if e["id"] == class_id), None)
                if entry is None:
                    raise NotFound("Class not found.")
            # Model mapping and source IDs are deliberately immutable across renames.
            allowed = {"name", "kind", "color", "active", "region", "quality_grade"}
            if set(changes) - allowed:
                raise AnnotationError("Unknown or immutable class field.")
            entry.update(changes)
            if not isinstance(entry.get("name"), str):
                raise AnnotationError("Class name must be a string.")
            entry["name"] = entry["name"].strip()
            if not entry["name"] or len(entry["name"]) > 120:
                raise AnnotationError("Class name must contain 1–120 characters.")
            if not isinstance(entry["kind"], str) or entry["kind"] not in KINDS or not isinstance(entry["active"], bool):
                raise AnnotationError("Invalid class kind or active flag.")
            for field in ("region", "quality_grade"):
                value = entry.get(field)
                if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 120):
                    raise AnnotationError(f"Class {field} must be null or a string containing 1–120 characters.")
            if not isinstance(entry["color"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", entry["color"]):
                raise AnnotationError("Class color must be #RRGGBB.")
            if any(e["id"] != class_id and e["name"].casefold() == entry["name"].casefold() for e in entries):
                raise AnnotationError("A class with that name already exists.")
            used = any(a.get("class_id") == class_id for row in db.execute("SELECT document FROM revisions")
                       for a in json.loads(row[0])["annotations"])
            old = next((e for e in entries if e["id"] == class_id), {})
            if used and (entry["kind"] != old.get("kind") or not entry["active"]):
                raise AnnotationError("A class used by current or historical annotations cannot change kind or be disabled.")
            if old.get("source_name") is not None and (entry["kind"] != old.get("kind") or entry["active"] != old.get("active")):
                raise AnnotationError("The original manual taxonomy and model classes must remain available. Rename the class or add a new class instead.")
            db.execute("INSERT OR REPLACE INTO classes VALUES (?,?)", (class_id, _json(entry)))
            db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='classes_revision'")
            return entry

    def add_class(self, changes):
        return self._change_class(None, changes, True)

    def update_class(self, class_id, changes):
        return self._change_class(class_id, changes)

    def delete_class(self, class_id):
        with self._db(True) as db:
            row = db.execute("SELECT document FROM classes WHERE id=?", (class_id,)).fetchone()
            if row is None:
                raise NotFound("Class not found.")
            if json.loads(row[0]).get("source_name") is not None:
                raise AnnotationError("Class is used by the original manual taxonomy or annotation models; rename it instead.")
            for (document,) in db.execute("SELECT document FROM revisions"):
                if any(a.get("class_id") == class_id for a in json.loads(document)["annotations"]):
                    raise AnnotationError("Class is used by current or historical annotations; rename it instead.")
            db.execute("DELETE FROM classes WHERE id=?", (class_id,))
            db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='classes_revision'")
        return {"deleted": class_id}

    def _get(self, db, image_id):
        row = db.execute("SELECT document FROM images WHERE id=?", (image_id,)).fetchone()
        if row is None:
            raise NotFound("Image not found.")
        return json.loads(row[0])

    def get(self, image_id):
        with self._db() as db:
            return self._get(db, image_id)

    def list(self):
        with self._db() as db:
            documents = [json.loads(row[0]) for row in db.execute("SELECT document FROM images ORDER BY rowid DESC")]
        return {"root": str(self.root), "images": [{**{k: v for k, v in d.items() if k != "annotations"},
                "annotation_count": len(d["annotations"]),
                "unreviewed_count": sum(a["status"] in {"unreviewed", "corrected"} for a in d["annotations"])} for d in documents]}

    def _decode(self, data):
        if not data or len(data) > 40 * 1024 * 1024:
            raise AnnotationError("Image is empty or exceeds 40 MiB.")
        # Header dimension check precedes allocation/decompression.
        from PIL import Image
        import io
        try:
            with Image.open(io.BytesIO(data)) as header:
                width, height = header.size
                if min(width, height) <= 0 or width * height > 64_000_000:
                    raise AnnotationError("Image dimensions exceed the 64 megapixel limit.")
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        except Exception as error:
            raise AnnotationError(f"Image cannot be decoded: {type(error).__name__}.") from error
        if frame is None or frame.shape[:2] != (height, width):
            raise AnnotationError("Image is corrupt or has inconsistent dimensions.")
        return frame

    def _persist(self, db, document):
        document["updated_at"] = _now()
        serialized = _json(document)
        artifact = self._artifact("revisions", serialized.encode("utf-8"), ".json")
        db.execute("INSERT INTO revisions VALUES (?,?,?,?)", (document["id"], document["revision"], serialized, document["updated_at"]))
        db.execute("INSERT OR REPLACE INTO images VALUES (?,?,?)", (document["id"], document["image_sha256"], serialized))
        return deepcopy(document)

    def _image_document(self, data, filename, image_id):
        frame = self._decode(data)
        height, width = frame.shape[:2]
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}:
            suffix = ".bin"
        original = self._artifact("images", data, suffix)
        success, png = cv2.imencode(".png", frame)
        if not success:
            raise AnnotationError("Could not persist image pixels.")
        pixels = self._artifact("pixels", png.tobytes(), ".png")
        return {"id": image_id, "filename": Path(filename.replace("\\", "/")).name[:240],
                "width": width, "height": height, "image_sha256": hashlib.sha256(data).hexdigest(),
                "original_path": original, "pixels_path": pixels,
                "pixels_url": f"/api/annotations/images/{image_id}/pixels", "status": "unreviewed", "revision": 1,
                "annotations": [], "baseline": None, "split": None, "created_at": _now()}

    def upload(self, data: bytes, filename: str, dataset_id=None):
        with self._db(True) as db:
            digest = hashlib.sha256(data).hexdigest()
            # Repeated uploads of the same original are idempotent.
            row = db.execute("SELECT document FROM images WHERE content_hash=? ORDER BY rowid LIMIT 1", (digest,)).fetchone()
            if row:
                return json.loads(row[0])
            from src.annotation.primary_baseline import PRIMARY_META
            selected = db.execute("SELECT value FROM meta WHERE key=?", (PRIMARY_META,)).fetchone()
            selected_id = json.loads(selected[0]).get("dataset_id") if selected else None
            if dataset_id is not None:
                if not isinstance(dataset_id, str) or dataset_id not in {d["id"] for d in self.datasets()["datasets"]}:
                    raise AnnotationError("Upload dataset is not registered.")
                selected_id = dataset_id
            document = self._image_document(data, filename, f"upload-{digest[:24]}")
            if selected_id is not None:
                document["dataset_id"] = selected_id
            return self._persist(db, document)

    def pixels_path(self, image_id):
        document = self.get(image_id)
        path = self.root / document["pixels_path"]
        self._verify_artifact(path)
        return path

    def frame(self, image_id):
        document = self.get(image_id)
        path = self.pixels_path(image_id)
        frame = cv2.imread(str(path))
        if frame is None or frame.shape[:2] != (document["height"], document["width"]):
            raise AnnotationError("Saved image pixels are corrupt.")
        return frame

    def _verify_artifact(self, path):
        digest = path.name.split(".", 1)[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise AnnotationError(f"Missing or corrupt immutable artifact: {path.name}")

    def _normal_annotations(self, annotations, document, previous=None, trusted_source=None):
        if not isinstance(annotations, list) or len(annotations) > 2000:
            raise AnnotationError("Annotations must be a list with at most 2000 objects.")
        classes = {c["id"]: c for c in self.classes()["classes"]}
        prior = {a["id"]: a for a in (previous or [])}
        ids, result = set(), []
        for raw in annotations:
            if not isinstance(raw, dict):
                raise AnnotationError("Every annotation must be an object.")
            annotation = deepcopy(raw)
            identifier = annotation.get("id") or uuid.uuid4().hex
            if not isinstance(identifier, str) or not identifier or len(identifier) > 160 or identifier in ids:
                raise AnnotationError("Annotation IDs must be unique nonempty strings.")
            ids.add(identifier)
            annotation["id"] = identifier
            class_id = annotation.get("class_id")
            if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id not in classes or not classes[class_id]["active"]:
                raise AnnotationError(f"Annotation {identifier} has an unknown or inactive class ID.")
            category = classes[class_id]
            annotation["region"] = category.get("region")
            annotation["quality_grade"] = category.get("quality_grade")
            annotation["class_name"] = category["name"]
            parent = annotation.get("parent_id")
            if parent is not None and (not isinstance(parent, str) or parent == identifier):
                raise AnnotationError("Parent ID must name a different whole-fish annotation.")
            annotation["parent_id"] = parent
            confidence = annotation.get("confidence")
            if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise AnnotationError("Confidence must be null or a finite number from 0 to 1.")
            annotation["confidence"] = confidence
            status = annotation.get("status", "unreviewed")
            if not isinstance(status, str) or status not in OBJECT_STATUSES:
                raise AnnotationError("Invalid annotation review status.")
            flags = annotation.get("flags", [])
            if not isinstance(flags, list) or any(not isinstance(f, str) for f in flags):
                raise AnnotationError("Annotation flags must be a list of strings.")
            annotation["flags"] = list(dict.fromkeys(flags))
            segmentation = annotation.get("segmentation")
            if segmentation is not None and segmentation != []:
                try:
                    mask = segmentation_to_mask(segmentation, document["height"], document["width"])
                    computed_bbox = _pixel_bbox(mask)
                except (TypeError, ValueError) as error:
                    raise AnnotationError(f"Annotation {identifier}: {error}") from error
                # Store an exact pixel mask as well as the editable segmentation.
                ok, encoded = cv2.imencode(".png", mask * 255)
                if not ok:
                    raise AnnotationError("Mask could not be encoded.")
                annotation["mask_path"] = self._artifact("masks", encoded.tobytes(), ".png")
                annotation["mask_sha256"] = Path(annotation["mask_path"]).stem
                if trusted_source == "manual":
                    # Original coordinate values remain in the manual baseline.
                    annotation["original_bbox"] = deepcopy(annotation.get("bbox"))
                annotation["bbox"] = computed_bbox
                annotation["area"] = int(np.count_nonzero(mask))
                annotation["flags"] = [f for f in annotation["flags"] if f != "missing_segmentation"]
            else:
                annotation["segmentation"] = None
                annotation.pop("mask_path", None)
                annotation.pop("mask_sha256", None)
                annotation["area"] = 0
                bbox = annotation.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
                    raise AnnotationError("A draft without segmentation requires a valid xywh bounding box.")
                x, y, width, height = bbox
                if min(x, y) < 0 or min(width, height) <= 0 or x + width > document["width"] + 1e-6 or y + height > document["height"] + 1e-6:
                    raise AnnotationError("Bounding box is outside the image.")
                annotation["flags"] = list(dict.fromkeys([*annotation["flags"], "missing_segmentation"]))
            old = prior.get(identifier)
            if trusted_source is None:
                for protected in ("original_annotation", "original_bbox", "source_annotation_id", "source_category"):
                    if old is not None and protected in old:
                        annotation[protected] = deepcopy(old[protected])
                    else:
                        annotation.pop(protected, None)
            if trusted_source == "manual":
                annotation["source"], annotation["status"] = "manual", "manual_verified"
            elif trusted_source == "automated":
                annotation["source"], annotation["status"] = "automated", "unreviewed"
            else:
                # Clients cannot create manual truth or self-approve by forging fields.
                stable = ("class_id", "parent_id", "segmentation", "bbox", "confidence")
                changed = old is None or any(annotation.get(k) != old.get(k) for k in stable)
                if old and not changed and status == old["status"]:
                    annotation["source"], annotation["status"] = old["source"], old["status"]
                elif status == "rejected":
                    annotation["source"], annotation["status"] = "user", "rejected"
                elif old and not changed and status == "approved":
                    # Single-object review uses the same hard mask checks as batch.
                    if not annotation.get("mask_path"):
                        raise AnnotationError("A pixel mask is required before approving an object.")
                    annotation["source"], annotation["status"] = old["source"], "approved"
                else:
                    annotation["source"], annotation["status"] = "user", "corrected"
            result.append(annotation)
        by_id = {a["id"]: a for a in result}
        for annotation in result:
            parent = by_id.get(annotation["parent_id"])
            if annotation["parent_id"] is not None:
                if parent is None or classes[parent["class_id"]]["kind"] != "whole_fish" or classes[annotation["class_id"]]["kind"] == "whole_fish":
                    raise AnnotationError("Object association must reference an existing whole-fish parent in the same image.")
                if annotation["status"] != "rejected" and parent["status"] == "rejected":
                    raise AnnotationError("An active object cannot belong to a rejected fish.")
        return result

    def _check_revision(self, document, expected_revision):
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != document["revision"]:
            raise RevisionConflict(f"Image has revision {document['revision']}; reload before saving edits.")

    def save(self, image_id, expected_revision, annotations, status=None, metadata=None):
        with self._db(True) as db:
            document = self._get(db, image_id)
            self._check_revision(document, expected_revision)
            if status is not None and (not isinstance(status, str) or status not in IMAGE_STATUSES):
                raise AnnotationError("Invalid image review status.")
            updated = deepcopy(document)
            if metadata is not None:
                if not isinstance(metadata, dict):
                    raise AnnotationError("Image metadata must be an object.")
                if document.get("baseline"):
                    original_metadata = document.get("metadata") or {}
                    protected = {"source_provenance", "leakage_group_id", "dataset_group_id", "protected_split",
                                 "original_split", "dataset_id", "source_annotation_count", "source_validation_errors"}
                    if any(key in metadata and metadata[key] != original_metadata.get(key) for key in protected):
                        raise AnnotationError("Original manual source provenance, dataset identity and protected split metadata cannot be changed.")
                    updated["metadata"] = {**deepcopy(original_metadata), **deepcopy(metadata)}
                else:
                    updated["metadata"] = deepcopy(metadata)
            updated["annotations"] = self._normal_annotations(annotations, document, document["annotations"])
            prior_status = {a["id"]: a["status"] for a in document["annotations"]}
            individually_approved = {a["id"] for a in updated["annotations"] if a["status"] == "approved" and prior_status.get(a["id"]) != "approved"}
            if individually_approved:
                validation = self._validate_document(updated)
                # Review is allowed object by object while other masks remain
                # incomplete, but no individual approval can bypass ownership,
                # duplicate, class, pixel or image-integrity checks.
                relevant = [e for e in validation["errors"] if e.get("annotation_id") is None or e.get("annotation_id") in individually_approved or "duplicate" in e["message"].lower()]
                if relevant:
                    raise AnnotationError("Cannot approve object: " + "; ".join(e["message"] for e in relevant[:6]))
            changed = updated["annotations"] != document["annotations"]
            if status == "rejected":
                updated["status"] = "rejected"
            elif status in {"unreviewed", "corrected"}:
                updated["status"] = status
            elif changed or document["status"] == "rejected":
                updated["status"] = "corrected"
            # Existing approved image stays approved only for a true no-op save.
            if updated == document:
                return document
            updated["revision"] += 1
            return self._persist(db, updated)

    def auto(self, image_id, expected_revision, callback):
        document = self.get(image_id)
        self._check_revision(document, expected_revision)
        if document["annotations"] or document["status"] != "unreviewed" or document.get("baseline"):
            raise RevisionConflict("Auto-Annotate requires an empty, unreviewed image. Existing reviews and manual truth are protected.")
        if callback is None:
            raise AnnotationError("Local annotation automation is unavailable.")
        # Inference runs outside the transaction; optimistic revision check handles edits during it.
        output = callback(deepcopy(document), self.frame(image_id), self.classes()["classes"])
        annotations = output.get("annotations", []) if isinstance(output, dict) else output
        with self._db(True) as db:
            current = self._get(db, image_id)
            self._check_revision(current, expected_revision)
            current["annotations"] = self._normal_annotations(annotations, current, trusted_source="automated")
            if isinstance(output, dict):
                current["automation"] = deepcopy(output.get("automation", {}))
            current["revision"] += 1
            return self._persist(db, current)

    def approve(self, image_id, expected_revision):
        with self._db(True) as db:
            document = self._get(db, image_id)
            self._check_revision(document, expected_revision)
            if document["status"] == "rejected":
                raise AnnotationError("Restore or edit a rejected image before approval.")
            if document["annotations"] and all(a["status"] == "rejected" for a in document["annotations"]):
                raise AnnotationError("Every annotation is rejected. Restore or add a valid annotation before approval.")
            report = self._validate_document(document)
            if report["errors"]:
                raise AnnotationError("Cannot approve: " + "; ".join(i["message"] for i in report["errors"][:6]))
            if document["status"] in {"approved", "manual_verified"}:
                return document
            for annotation in document["annotations"]:
                if annotation["status"] not in {"rejected", "manual_verified"}:
                    annotation["status"] = "approved"
            document["status"] = "approved"
            document["revision"] += 1
            return self._persist(db, document)

    def history(self, image_id):
        with self._db() as db:
            self._get(db, image_id)
            return {"revisions": [{"revision": row[0], "created_at": row[1], "status": json.loads(row[2])["status"]}
                                  for row in db.execute("SELECT revision,created_at,document FROM revisions WHERE image_id=? ORDER BY revision DESC", (image_id,))]}

    def restore(self, image_id, expected_revision, revision):
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise AnnotationError("Saved revision must be a positive integer.")
        with self._db(True) as db:
            current = self._get(db, image_id)
            self._check_revision(current, expected_revision)
            row = db.execute("SELECT document FROM revisions WHERE image_id=? AND revision=?", (image_id, revision)).fetchone()
            if row is None:
                raise NotFound("Saved revision not found.")
            restored = json.loads(row[0])
            restored["revision"] = current["revision"] + 1
            restored["restored_from_revision"] = revision
            # An immutable original baseline can recover its verified provenance.
            if not (revision == 1 and restored.get("baseline")):
                restored["status"] = "corrected"
                for a in restored["annotations"]:
                    if a["status"] != "rejected":
                        a["status"] = "corrected"
            return self._persist(db, restored)

    def import_manual(self, splits=None):
        if splits is not None and not isinstance(splits, (list, tuple)):
            raise AnnotationError("splits must be a list containing train, valid, and/or test.")
        splits = list(SPLITS if splits is None else splits)
        if not splits or any(not isinstance(s, str) or s not in SPLITS for s in splits) or len(set(splits)) != len(splits):
            raise AnnotationError("Select train, valid, and/or test once each.")
        self._initialize()
        imported, skipped, errors = [], [], []
        for split in splits:
            path = self.manual_source / split / "_annotations.coco.json"
            if not path.is_file():
                errors.append({"split": split, "message": "Manual COCO source does not exist."})
                continue
            raw = path.read_bytes()
            try:
                source = json.loads(raw)
                if not isinstance(source.get("images"), list) or not isinstance(source.get("annotations"), list):
                    raise ValueError("COCO images and annotations must be lists.")
            except (ValueError, TypeError) as error:
                errors.append({"split": split, "message": str(error)})
                continue
            baseline_path = self._artifact("baselines", raw, ".coco.json")
            baseline_hash = hashlib.sha256(raw).hexdigest()
            by_image = {}
            for annotation in source["annotations"]:
                by_image.setdefault(annotation["image_id"], []).append(annotation)
            available_classes = {c["id"]: c for c in self.classes()["classes"]}
            category_names = {c["id"]: c["name"] for c in source["categories"]}
            if any(cid not in available_classes or available_classes[cid].get("source_name") != name for cid, name in category_names.items()):
                errors.append({"split": split, "message": "Source category IDs/names differ from the immutable baseline class mapping."})
                continue
            source_image_ids = {image["id"] for image in source["images"]}
            for missing in set(by_image) - source_image_ids:
                errors.append({"split": split, "message": f"Annotation references absent source image {missing}."})
            for image in source["images"]:
                key = f"{baseline_hash}:{split}:{image['id']}"
                image_id = "manual-" + hashlib.sha256(key.encode()).hexdigest()[:24]
                try:
                    with self._db(True) as db:
                        old = db.execute("SELECT image_id FROM imports WHERE import_key=?", (key,)).fetchone()
                        if old:
                            skipped.append(old[0])
                            continue
                        file_path = (path.parent / image["file_name"]).resolve()
                        if not file_path.is_relative_to(path.parent.resolve()):
                            raise AnnotationError("Manual image path leaves its dataset split.")
                        document = self._image_document(file_path.read_bytes(), image["file_name"], image_id)
                        if [document["width"], document["height"]] != [image["width"], image["height"]]:
                            raise AnnotationError("Manual image dimensions disagree with COCO metadata.")
                        document["baseline"] = {"path": baseline_path, "sha256": baseline_hash, "split": split,
                                                "source_image_id": image["id"], "revision": 1, "source_path": str(path)}
                        document["source_record"] = deepcopy(image)
                        document["split"], document["status"] = split, "manual_verified"
                        annotations = []
                        for a in by_image.get(image["id"], []):
                            segmentation = a.get("segmentation")
                            if segmentation:
                                segmentation = mask_to_rle(coco_segmentation_to_mask(segmentation, document["height"], document["width"]))
                            annotations.append({"id": f"manual-{a['id']}", "class_id": a["category_id"],
                                                "parent_id": None, "segmentation": segmentation,
                                                "bbox": deepcopy(a.get("bbox")), "confidence": None, "flags": [],
                                                "source_annotation_id": a["id"], "original_annotation": deepcopy(a),
                                                "source_category": deepcopy(next(c for c in source["categories"] if c["id"] == a["category_id"]))})
                        document["annotations"] = self._normal_annotations(annotations, document, trusted_source="manual")
                        if any(not a.get("mask_path") for a in document["annotations"]):
                            raise AnnotationError("Manual source lacks actual instance masks; baseline cannot be marked segmentation verified.")
                        self._persist(db, document)
                        db.execute("INSERT INTO imports VALUES (?,?)", (key, image_id))
                        imported.append(image_id)
                except (OSError, AnnotationError, KeyError, TypeError, ValueError) as error:
                    errors.append({"split": split, "filename": image.get("file_name"), "message": str(error)})
        return {"imported": len(imported), "skipped": len(skipped), "image_ids": imported, "errors": errors, "root": str(self.root)}

    def _validate_document(self, document):
        errors, warnings = [], []
        def issue(target, message, annotation_id=None):
            target.append({"image_id": document["id"], "annotation_id": annotation_id, "message": message})
        for field in ("original_path", "pixels_path"):
            try:
                self._verify_artifact(self.root / document[field])
            except AnnotationError as error:
                issue(errors, str(error))
        try:
            frame = cv2.imread(str(self.root / document["pixels_path"]))
            if frame is None or list(frame.shape[:2]) != [document["height"], document["width"]]:
                issue(errors, "Canonical image dimensions are corrupt.")
        except (OSError, cv2.error):
            issue(errors, "Canonical image cannot be decoded.")
        if document.get("baseline"):
            baseline = self.root / document["baseline"]["path"]
            if not baseline.is_file() or hashlib.sha256(baseline.read_bytes()).hexdigest() != document["baseline"]["sha256"]:
                issue(errors, "Original manual annotation snapshot is corrupt or missing.")
        classes = {c["id"]: c for c in self.classes()["classes"]}
        all_objects = {a["id"]: a for a in document["annotations"]}
        masks, mask_bounds, mask_areas = {}, {}, {}
        if len(all_objects) != len(document["annotations"]):
            issue(errors, "Annotation IDs are duplicated.")
        for a in document["annotations"]:
            if a["status"] == "rejected":
                continue
            cid = a.get("class_id")
            if cid not in classes or not classes[cid]["active"]:
                issue(errors, "Invalid or inactive class ID.", a["id"])
                continue
            if a.get("confidence") is not None and a["confidence"] < 0.5:
                issue(warnings, "Low-confidence prediction requires visual review.", a["id"])
            try:
                mask = segmentation_to_mask(a.get("segmentation"), document["height"], document["width"])
                expected_bbox = _pixel_bbox(mask)
                if a.get("bbox") != expected_bbox:
                    issue(errors, "Bounding box does not match the actual mask pixels.", a["id"])
                path = self.root / a["mask_path"]
                self._verify_artifact(path)
                stored = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if stored is None or not np.array_equal(stored != 0, mask != 0):
                    issue(errors, "Saved PNG mask differs from annotation segmentation.", a["id"])
                masks[a["id"]] = mask
                mask_bounds[a["id"]] = expected_bbox
                mask_areas[a["id"]] = int(cv2.countNonZero(mask))
                if np.any(mask[[0, -1], :]) or np.any(mask[:, [0, -1]]):
                    issue(warnings, "Mask touches the image edge; fish or part may be partially visible.", a["id"])
                count, _ = cv2.connectedComponents(mask)
                if count > 2:
                    issue(warnings, "Mask has disconnected regions; inspect object ownership.", a["id"])
            except (ValueError, KeyError, OSError, cv2.error) as error:
                issue(errors, f"Incomplete segmentation: {error}", a["id"])
            parent = all_objects.get(a.get("parent_id"))
            if a.get("parent_id") is not None and (parent is None or classes.get(parent["class_id"], {}).get("kind") != "whole_fish" or parent["status"] == "rejected"):
                issue(errors, "Invalid or rejected whole-fish parent.", a["id"])
            if classes[cid]["kind"] == "anatomy" and a.get("parent_id") is None:
                issue(warnings, "Anatomical part has no verified whole-fish association; original manual parts may be ungrouped.", a["id"])
        for a in document["annotations"]:
            child_mask, parent_mask = masks.get(a["id"]), masks.get(a.get("parent_id"))
            if child_mask is None or parent_mask is None or a["status"] == "rejected":
                continue
            intersection = _mask_intersection(child_mask, parent_mask, mask_bounds[a["id"]], mask_bounds[a["parent_id"]])
            if intersection == 0:
                issue(errors, "Part mask is completely disjoint from its assigned whole-fish parent.", a["id"])
            else:
                outside_fraction = 1 - intersection / mask_areas[a["id"]]
                if outside_fraction > .05:
                    issue(warnings, f"Part mask extends outside its assigned fish ({outside_fraction:.1%}); review object ownership.", a["id"])
        ids = list(masks)
        for index, first_id in enumerate(ids):
            first = all_objects[first_id]
            for second_id in ids[index + 1:]:
                second = all_objects[second_id]
                if second.get("parent_id") == first_id or first.get("parent_id") == second_id:
                    continue
                intersection = _mask_intersection(masks[first_id], masks[second_id], mask_bounds[first_id], mask_bounds[second_id])
                if not intersection:
                    continue
                area1, area2 = mask_areas[first_id], mask_areas[second_id]
                iou = intersection / (area1 + area2 - intersection)
                if iou > 0.98:
                    issue(errors, f"Possible duplicate mask {second_id} (IoU {iou:.3f}).", first_id)
                elif intersection / min(area1, area2) > 0.25:
                    issue(warnings, f"Ambiguous mask overlap with {second_id} ({iou:.3f} IoU).", first_id)
        for a in document["annotations"]:
            if a["status"] == "rejected" or classes.get(a["class_id"], {}).get("kind") != "whole_fish":
                continue
            observed = {classes.get(c["class_id"], {}).get("region") for c in document["annotations"] if c.get("parent_id") == a["id"] and c["status"] != "rejected"}
            missing = {"head", "body", "tail"} - observed
            if missing:
                issue(warnings, "Anatomy not detected or not visible (absence unverified): " + ", ".join(sorted(missing)) + ".", a["id"])
        return {"errors": errors, "warnings": warnings}

    def _selected(self, image_ids=None, approved_only=False):
        with self._db() as db:
            documents = [json.loads(r[0]) for r in db.execute("SELECT document FROM images ORDER BY id")]
        if image_ids is not None:
            if not isinstance(image_ids, list) or any(not isinstance(i, str) for i in image_ids) or len(set(image_ids)) != len(image_ids):
                raise AnnotationError("image_ids must be a list of unique image IDs.")
            found = {d["id"] for d in documents}
            if set(image_ids) - found:
                raise AnnotationError("One or more selected images do not exist.")
            documents = [d for d in documents if d["id"] in image_ids]
        if approved_only:
            if image_ids is None:
                from src.annotation.primary_baseline import dataset_id, primary_profile
                selected = primary_profile(self)
                if selected:
                    documents = [d for d in documents if dataset_id(d) in {selected["dataset_id"], None}]
            if image_ids is not None and any(d["status"] not in {"approved", "manual_verified"} for d in documents):
                raise AnnotationError("Export selection contains unreviewed images. Approve them first.")
            documents = [d for d in documents if d["status"] in {"approved", "manual_verified"}]
        return documents

    def validate(self, image_ids=None):
        documents = self._selected(image_ids)
        errors, warnings = [], []
        hashes = {}
        for document in documents:
            report = self._validate_document(document)
            errors.extend(report["errors"])
            warnings.extend(report["warnings"])
            previous = hashes.get(document["image_sha256"])
            if previous:
                warnings.append({"image_id": document["id"], "message": f"Identical original image also occurs as {previous['id']}; export groups identical pixels into one split."})
            hashes[document["image_sha256"]] = document
        return {"valid": not errors, "image_count": len(documents), "annotation_count": sum(len(d["annotations"]) for d in documents),
                "approved_image_count": sum(d["status"] in {"approved", "manual_verified"} for d in documents),
                "errors": errors, "warnings": warnings}

    def export(self, format="coco", image_ids=None, split=False):
        if not isinstance(format, str) or format not in {"coco", "yolo_detection", "yolo_segmentation"}:
            raise AnnotationError("Export format must be coco, yolo_detection, or yolo_segmentation.")
        if not isinstance(split, bool):
            raise AnnotationError("split must be true or false.")
        documents = self._selected(image_ids, approved_only=True)
        if not documents:
            raise AnnotationError("No approved images are available for export.")
        errors, warnings = [], []
        for d in documents:
            report = self._validate_document(d)
            errors.extend(report["errors"])
            warnings.extend(report["warnings"])
            if any(a["status"] not in {"approved", "manual_verified", "rejected"} for a in d["annotations"]):
                errors.append({"image_id": d["id"], "message": "Approved image contains unreviewed objects."})
        if errors:
            raise AnnotationError("Export validation failed: " + "; ".join(e["message"] for e in errors[:6]))
        classes = [c for c in self.classes()["classes"] if c["active"]]
        mapping = {c["id"]: index for index, c in enumerate(classes)}
        # Preserve source splits where possible. Identical canonical pixels always
        # share a split, even when the source export leaked them across splits.
        grouped, parents, seen = {}, {d["id"]: d["id"] for d in documents}, {}
        def group_root(identifier):
            while parents[identifier] != identifier:
                parents[identifier] = parents[parents[identifier]]
                identifier = parents[identifier]
            return identifier
        for d in documents:
            metadata = d.get("metadata") or {}
            keys = [("pixels", d["pixels_path"])]
            leakage_group = metadata.get("leakage_group_id") or metadata.get("dataset_group_id")
            if leakage_group:
                keys.append(("declared", leakage_group))
            for key in keys:
                if key in seen:
                    first, second = group_root(d["id"]), group_root(seen[key])
                    parents[max(first, second)] = min(first, second)
                else:
                    seen[key] = d["id"]
        for d in documents:
            grouped.setdefault(group_root(d["id"]), []).append(d)
        assignments = {}
        for group_key, group in grouped.items():
            known = sorted({s for d in group for s in (d.get("split"), (d.get("metadata") or {}).get("protected_split")) if s in SPLITS})
            bucket = int(hashlib.sha256(group_key.encode()).hexdigest()[:8], 16) % 100
            selected_split = next((s for s in ("test", "valid", "train") if s in known), None) if known else ("train" if bucket < 80 else "valid" if bucket < 90 else "test")
            for d in group:
                assignments[d["id"]] = selected_split if split else "all"
            if len(known) > 1:
                warnings.append({"message": f"Identical image content in source splits {known} grouped into {selected_split}."})
        manifest = {"schema_version": "fish-annotation-workspace-v1", "created_at": _now(), "format": format,
                    "source_root": str(self.root), "class_mapping": [{"export_id": mapping[c["id"]], "source_id": c["id"], **{k: v for k, v in c.items() if k != "id"}} for c in classes],
                    "images": [], "validation": {"valid": True, "errors": [], "warnings": warnings}}
        manifest["split_requested"] = split
        manifest["available_splits"] = sorted(set(assignments.values()))
        manifest["validation"]["training_ready"] = split and "train" in manifest["available_splits"] and "valid" in manifest["available_splits"]
        if not manifest["validation"]["training_ready"]:
            warnings.append({"message": "No independent training and validation split is available; create sufficient reviewed groups and export with split=true before evaluating a model."})
        collections = {}
        staging = self.root / "exports" / f".export-{uuid.uuid4().hex}.tmp"
        try:
            with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for number, document in enumerate(documents, 1):
                    subset = assignments[document["id"]]
                    prefix = subset + "/" if split else ""
                    stem = document["id"]
                    image_path = f"{prefix}images/{stem}.png"
                    archive.write(self.root / document["pixels_path"], image_path)
                    original_path = f"originals/{stem}{Path(document['original_path']).suffix}"
                    archive.write(self.root / document["original_path"], original_path)
                    item = {"id": document["id"], "filename": document["filename"], "width": document["width"], "height": document["height"],
                            "path": image_path, "original_path": original_path, "revision": document["revision"], "status": document["status"],
                            "image_sha256": document["image_sha256"], "split": subset, "baseline": document.get("baseline"), "annotations": []}
                    collection = collections.setdefault(subset, {"images": [], "annotations": [], "categories": [{"id": mapping[c["id"]], "name": c["name"], "source_id": c["id"], "kind": c["kind"]} for c in classes]})
                    collection["images"].append({"id": number, "file_name": f"images/{stem}.png", "width": document["width"], "height": document["height"], "workspace_id": document["id"], "revision": document["revision"]})
                    lines = []
                    for index, annotation in enumerate(document["annotations"]):
                        if annotation["status"] == "rejected":
                            continue
                        mask = segmentation_to_mask(annotation["segmentation"], document["height"], document["width"])
                        segmentation = mask_to_rle(mask)
                        bbox = _pixel_bbox(mask)
                        mask_path = f"{prefix}masks/{stem}/{index}.png"
                        archive.write(self.root / annotation["mask_path"], mask_path)
                        category = classes[mapping[annotation["class_id"]]]
                        metadata = {**deepcopy(annotation), "class_name": category["name"], "region": category.get("region"),
                                    "quality_grade": category.get("quality_grade"), "mask_path": mask_path, "export_class_id": mapping[annotation["class_id"]]}
                        # Exact masks in both manifest and COCO; holes stay holes.
                        metadata["segmentation"] = segmentation
                        item["annotations"].append(metadata)
                        collection["annotations"].append({"id": len(collection["annotations"]) + 1, "image_id": number,
                            "category_id": mapping[annotation["class_id"]], "segmentation": segmentation,
                            "bbox": bbox, "area": int(cv2.countNonZero(mask)), "iscrowd": 0, "workspace_id": annotation["id"],
                            "parent_id": annotation.get("parent_id"), "confidence": annotation.get("confidence"),
                            "review_status": annotation["status"], "source": annotation["source"]})
                        if format == "yolo_segmentation":
                            try:
                                coordinates = yolo_polygon(mask)
                            except ValueError as error:
                                raise AnnotationError(f"{document['filename']}, annotation {annotation['id']}: {error}") from error
                            lines.append(str(mapping[annotation["class_id"]]) + " " + " ".join(f"{v:.12g}" for v in coordinates))
                        elif format == "yolo_detection":
                            x, y, width, height = bbox
                            coordinates = [(x + width / 2) / document["width"], (y + height / 2) / document["height"], width / document["width"], height / document["height"]]
                            lines.append(str(mapping[annotation["class_id"]]) + " " + " ".join(f"{v:.12g}" for v in coordinates))
                    if format != "coco":
                        archive.writestr(f"{prefix}labels/{stem}.txt", "\n".join(lines) + ("\n" if lines else ""))
                    manifest["images"].append(item)
                    archive.writestr(f"reviewed_documents/{stem}.json", _json(document))
                if format == "coco":
                    for subset, collection in collections.items():
                        archive.writestr(f"{subset + '/' if split else ''}_annotations.coco.json", _json(collection))
                else:
                    dataset = {"path": ".", "train": "train/images" if split and "train" in collections else None if split else "images",
                               "val": "valid/images" if split and "valid" in collections else None,
                               "test": "test/images" if split and "test" in collections else None,
                               "nc": len(classes), "names": {mapping[c["id"]]: c["name"] for c in classes}}
                    # JSON syntax is valid YAML and avoids adding a serialization dependency.
                    archive.writestr("data.yaml", json.dumps(dataset, indent=2))
                archive.writestr("classes.json", _json(manifest["class_mapping"]))
                archive.writestr("manifest.json", _json(manifest))
                archive.writestr("validation_report.json", _json(manifest["validation"]))
            destination = self.root / "exports" / f"annotations-{format}-{uuid.uuid4().hex[:12]}.zip"
            os.replace(staging, destination)
            return destination
        except ValueError as error:
            raise AnnotationError(str(error)) from error
        finally:
            staging.unlink(missing_ok=True)

    def connection(self, write=False):
        """Shared transaction for optional local learning/index extensions."""
        return self._db(write)

    def _connection(self, write=False):
        return self._db(write)

    def get_revision(self, image_id, revision):
        with self._db() as db:
            self._get(db, image_id)
            row = db.execute("SELECT document FROM revisions WHERE image_id=? AND revision=?", (image_id, revision)).fetchone()
            if row is None:
                raise NotFound("Saved revision not found.")
            return json.loads(row[0])


_shared_store = None
_shared_lock = RLock()


def get_annotation_store():
    """One lazy workspace shared by all API adapters; honor test/operator roots."""
    global _shared_store
    requested_root = Path(os.getenv("FISH_ANNOTATION_ROOT") or project_root() / "dataset" / "annotation_workspace").resolve()
    with _shared_lock:
        if _shared_store is None or _shared_store.root != requested_root:
            _shared_store = AnnotationStore(requested_root)
        return _shared_store
