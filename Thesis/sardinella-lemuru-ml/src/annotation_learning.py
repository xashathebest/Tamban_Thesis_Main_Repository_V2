"""Local, verified-only references and gated auxiliary annotation-model learning.

This module does not change the inspection/grading model registry. References
can suggest a class for a low-confidence *existing* polygon; they never copy or
invent a mask. Weight updates happen only in thresholded batches, against the
unchanged manual validation set, and remain separate from live grading.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Mapping
from uuid import uuid4

import numpy as np
from PIL import Image, ImageOps

from src.annotation.masks import segmentation_to_mask, yolo_polygon
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES

_PROCESS_TOKEN = uuid4().hex


def _process_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable process probe on Windows.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied proves no death.
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pixels(image: Image.Image) -> str:
    return sha256(str(image.size).encode() + image.convert("RGB").tobytes()).hexdigest()


def _part(class_id: int) -> str:
    return SOURCE_CLASSES.get(class_id, "Unknown").rsplit("_", 1)[-1]


def _annotations(row: Mapping[str, Any], *, original: bool = False) -> list[dict]:
    preserve_original = row.get("split") in {"val", "valid", "test"} or not row.get("training_verified_after_import")
    value = row.get("original_annotations") if original and row.get("source") == "manual" and preserve_original else None
    return list(value if value is not None else row.get("annotations", []))


def _signature(annotations: list[dict], width: int, height: int) -> str:
    """Compare ground truth without incidental confidence/provenance metadata."""
    labels = [{"class_id": a.get("class_id"), "mask_sha256": sha256(_binary(a, width, height).tobytes()).hexdigest()} for a in annotations]
    return _json(sorted(labels, key=_json))


def _validated(annotations: list[dict], width: int, height: int) -> list[dict]:
    result = []
    seen = set()
    for annotation in annotations:
        class_id = annotation.get("class_id")
        if isinstance(class_id, bool) or class_id not in SOURCE_CLASSES:
            raise ValueError("Unknown source class ID; refusing an inconsistent class mapping.")
        if annotation.get("class_name", SOURCE_CLASSES[class_id]) != SOURCE_CLASSES[class_id]:
            raise ValueError("Class name and source class ID disagree.")
        segmentation = annotation.get("segmentation")
        if segmentation:
            if isinstance(segmentation, dict) and isinstance(segmentation.get("counts"), list):
                # Native COCO runs prove extent and foreground exactly, without
                # allocating a multi-megapixel bitmap for every reference part.
                # Training/export still decode the original runs when needed.
                runs = segmentation["counts"]
                if height <= 0 or width <= 0 or height * width > 64_000_000 or segmentation.get("size") != [height, width]:
                    raise ValueError("Mask RLE dimensions do not match the original image.")
                if not runs or any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in runs) or sum(runs) != height * width:
                    raise ValueError("Mask RLE counts must be nonnegative integers covering the image exactly.")
                foreground = sum(runs[1::2])
            else:
                foreground = np.count_nonzero(segmentation_to_mask(segmentation, height, width))
            if not foreground:
                raise ValueError("Training masks cannot be empty.")
            key = _json([class_id, segmentation])
            if key in seen:
                raise ValueError("Duplicate annotation in one image.")
            seen.add(key)
            result.append(dict(annotation, class_id=int(class_id), class_name=SOURCE_CLASSES[class_id]))
            continue
        points = np.asarray(annotation.get("mask", []), dtype=float)
        if points.ndim != 2 or points.shape[1:] != (2,) or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError("Training labels require a finite segmentation polygon with at least three points.")
        if (points[:, 0] < 0).any() or (points[:, 0] > width).any() or (points[:, 1] < 0).any() or (points[:, 1] > height).any():
            raise ValueError("Segmentation coordinates are outside the source image.")
        area = abs(float(np.dot(points[:, 0], np.roll(points[:, 1], 1)) - np.dot(points[:, 1], np.roll(points[:, 0], 1)))) / 2
        if area < 0.5:
            raise ValueError("Degenerate segmentation polygon cannot enter training.")
        key = _json([class_id, points.tolist()])
        if key in seen:
            raise ValueError("Duplicate annotation in one image.")
        seen.add(key)
        result.append(dict(annotation, class_id=int(class_id), mask=points.tolist(), class_name=SOURCE_CLASSES[class_id]))
    return result


def _binary(annotation: Mapping[str, Any], width: int, height: int) -> np.ndarray:
    segmentation = annotation.get("segmentation")
    if not segmentation:
        segmentation = [[value for point in annotation.get("mask", []) for value in point]]
    return segmentation_to_mask(segmentation, height, width)


def _descriptor(image: Image.Image, annotation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Transparent, small visual descriptor; this is not a learned embedding."""
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    geometry = np.array([1.0, 1.0])
    if annotation is not None:
        width, height = rgb.size
        bbox = annotation.get("bbox")
        if not bbox or len(bbox) != 4:
            points = np.asarray(annotation.get("mask", []), dtype=float)
            bbox = [points[:, 0].min(), points[:, 1].min(), points[:, 0].max()+1, points[:, 1].max()+1]
        bounds = (max(0, int(math.floor(bbox[0]))), max(0, int(math.floor(bbox[1]))),
                  min(width, int(math.ceil(bbox[2]))), min(height, int(math.ceil(bbox[3]))))
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise ValueError("Empty reference crop.")
        rgb = rgb.crop(bounds)
        rgb.thumbnail((256, 256))
        xs = bounds[0] + np.minimum(bounds[2]-bounds[0]-1, ((np.arange(rgb.width)+.5)*(bounds[2]-bounds[0])/rgb.width).astype(int))
        ys = bounds[1] + np.minimum(bounds[3]-bounds[1]-1, ((np.arange(rgb.height)+.5)*(bounds[3]-bounds[1])/rgb.height).astype(int))
        segmentation = annotation.get("segmentation")
        if isinstance(segmentation, dict) and isinstance(segmentation.get("counts"), list):
            # Sample the native COCO runs directly for appearance features.
            # No full-resolution bitmap is copied or changed, and original
            # masks remain authoritative for edits, training and evaluation.
            ends = np.cumsum(segmentation["counts"], dtype=np.int64)
            positions = ys[:, None] + xs[None, :] * height
            crop_mask = np.searchsorted(ends, positions, side="right") % 2 != 0
        else:
            crop_mask = _binary(annotation, width, height)[np.ix_(ys, xs)] != 0
        if not crop_mask.any():
            raise ValueError("Reference mask has no sampled foreground pixels.")
        mask = Image.fromarray(crop_mask.astype(np.uint8) * 255)
        rgb = Image.composite(rgb, Image.new("RGB", rgb.size, (127, 127, 127)), mask)
        geometry = np.array([min(rgb.width / rgb.height, 8.0) / 8.0, float(crop_mask.mean())])
        samples = np.asarray(rgb)[crop_mask]
    else:
        samples = np.asarray(rgb.resize((64, 64))).reshape(-1, 3)
    if not len(samples):
        raise ValueError("Reference mask has no pixels.")
    histogram = np.concatenate([np.histogram(samples[:, channel], bins=8, range=(0, 256))[0] / len(samples) for channel in range(3)])
    gray = np.asarray(ImageOps.grayscale(rgb).resize((8, 8)), dtype=float).reshape(-1) / 255.0
    return {"hist": histogram, "gray": gray, "geometry": geometry}


def _similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    color = float(np.abs(left["hist"] - right["hist"]).sum()) / 6.0
    structure = float(np.abs(left["gray"] - right["gray"]).mean())
    geometry = float(np.abs(left["geometry"] - right["geometry"]).mean())
    return max(0.0, 1.0 - (0.5 * color + 0.35 * structure + 0.15 * geometry))


class UltralyticsAnnotationTrainer:
    """Lazy, local YOLO segmentation fine-tuning; never downloads a checkpoint."""

    def __init__(self, *, epochs: int = 30, image_size: int = 640, batch: int = 4, device: str = "cpu"):
        self.epochs, self.image_size, self.batch, self.device = epochs, image_size, batch, device

    @staticmethod
    def _load(checkpoint: Path):
        if not checkpoint.is_file():
            raise ValueError("An existing local annotation checkpoint is required.")
        from ultralytics import YOLO
        model = YOLO(str(checkpoint))
        names = {int(key): value for key, value in model.names.items()}
        if model.task != "segment" or names != SOURCE_CLASSES:
            raise ValueError("Annotation learning requires a segmentation checkpoint with the exact 12 source classes.")
        return model

    def train(self, checkpoint: Path, data_yaml: Path, output_dir: Path) -> Path:
        model = self._load(checkpoint)
        model.train(data=str(data_yaml), task="segment", epochs=self.epochs, imgsz=self.image_size,
                    batch=self.batch, device=self.device, workers=0, project=str(output_dir), name="fit",
                    exist_ok=False, seed=42, deterministic=True, pretrained=False, plots=False, amp=False)
        best = Path(model.trainer.best)
        if not best.is_file():
            raise ValueError("Training did not produce a candidate checkpoint.")
        return best

    def evaluate(self, checkpoint: Path, data_yaml: Path, output_dir: Path) -> dict[str, float]:
        model = self._load(checkpoint)
        metrics = model.val(data=str(data_yaml), split="val", imgsz=self.image_size, batch=self.batch,
                            device=self.device, workers=0, project=str(output_dir), name="evaluation",
                            exist_ok=False, plots=False, seed=42)
        result = {"segmentation_map50_95": float(metrics.seg.map), "segmentation_map50": float(metrics.seg.map50),
                  "detection_precision": float(metrics.box.mp), "detection_recall": float(metrics.box.mr),
                  "detection_map50_95": float(metrics.box.map)}
        # Ultralytics fills .maps for absent classes with the aggregate mean.
        # Report class metrics only when that class has actual evaluation truth.
        for class_id in map(int, metrics.seg.ap_class_index):
            result[f"class_{class_id}_segmentation_map50_95"] = float(metrics.seg.maps[class_id])
        return result


class LearningService:
    """Verified history, conservative adaptive evidence, and gated batch training."""

    def __init__(self, store: Any, artifacts_dir: Path | str, baseline_root: Path | str | None = None,
                 base_checkpoint: Path | str | None = None, *, min_examples: int = 25,
                 cooldown_seconds: float = 86400, adapter: Any = None, min_improvement: float = 0.005,
                 enable_reference_class_updates: bool = False):
        self.store = store
        self.database = store.database
        self.artifacts_dir = Path(artifacts_dir).resolve()
        self.baseline_root = Path(baseline_root).resolve() if baseline_root else None
        self.base_checkpoint = Path(base_checkpoint).resolve() if base_checkpoint else None
        self.min_examples = max(1, int(min_examples))
        self.cooldown_seconds = max(0, float(cooldown_seconds))
        self.min_improvement = max(1e-8, float(min_improvement))
        self.enable_reference_class_updates = bool(enable_reference_class_updates)
        self.adapter = adapter or UltralyticsAnnotationTrainer()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._reference_cache: dict[str, Any] = {}
        self._stored_reference_cache = None
        self._reference_preparing = False
        self._reference_thread = None
        self._initialize()

    def _initialize(self) -> None:
        self.store.initialize()
        with self.database._connection() as connection:
            schema = """
                CREATE TABLE IF NOT EXISTS annotation_learning_state (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annotation_learning_models (
                    version TEXT PRIMARY KEY, checkpoint TEXT NOT NULL, sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL, parent_version TEXT, run_id TEXT, metrics_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annotation_learning_runs (
                    run_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, dataset_version TEXT, details_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annotation_learning_reference_features (
                    image_id TEXT PRIMARY KEY,cache_key TEXT NOT NULL,features_json TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS annotation_learning_one_running
                    ON annotation_learning_runs((1)) WHERE status IN ('scheduled','training','evaluating');
            """
            required = {"annotation_learning_state", "annotation_learning_models", "annotation_learning_runs",
                        "annotation_learning_reference_features", "annotation_learning_one_running"}
            existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
            if not required <= existing:
                # Acquire the writer before DDL; executescript would implicitly
                # commit between statements and race another importer/worker.
                connection.execute("BEGIN IMMEDIATE")
                for statement in schema.split(";"):
                    if statement.strip():
                        connection.execute(statement)
        self._recover_abandoned_runs()
        if self.base_checkpoint and self.base_checkpoint.is_file() and self._state("original_version") is None:
            self.artifacts_dir.joinpath("models").mkdir(parents=True, exist_ok=True)
            digest = _sha(self.base_checkpoint)
            original = self.artifacts_dir / "models" / f"original-{digest}{self.base_checkpoint.suffix}"
            if not original.exists():
                shutil.copy2(self.base_checkpoint, original)
            if _sha(original) != digest:
                raise ValueError("Original checkpoint preservation failed checksum validation.")
            version = "original-" + digest[:12]
            with self.database._connection() as connection:
                connection.execute("INSERT OR IGNORE INTO annotation_learning_models VALUES (?,?,?,?,?,?,?)",
                                   (version, str(original), digest, _now(), None, None, "{}"))
                connection.execute("INSERT OR IGNORE INTO annotation_learning_state VALUES ('original_version',?)", (_json(version),))
                connection.execute("INSERT OR IGNORE INTO annotation_learning_state VALUES ('deployed_version',?)", (_json(version),))

    def _state(self, key: str, default: Any = None) -> Any:
        with self.database._connection() as connection:
            row = connection.execute("SELECT value_json FROM annotation_learning_state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set_state(self, key: str, value: Any) -> None:
        with self.database._connection() as connection:
            connection.execute("INSERT INTO annotation_learning_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, _json(value)))

    def deployed_version(self) -> str:
        return str(self._state("deployed_version", "reference-only"))

    def deployed_checkpoint(self) -> str | None:
        version = self.deployed_version()
        with self.database._connection() as connection:
            row = connection.execute("SELECT checkpoint,sha256 FROM annotation_learning_models WHERE version=?", (version,)).fetchone()
        if row and Path(row[0]).is_file() and _sha(Path(row[0])) == row[1]:
            return row[0]
        return None

    def _verified(self) -> list[dict]:
        rows = []
        for row in self.store.verified_examples():
            if row.get("status") in {"declined", "pending", "predicted", "quarantined"} or row.get("quarantined"):
                continue
            rows.append(row)
        return rows

    def _reference_rows(self, exclude_image_id: str | None = None, exclude_pixel: str | None = None) -> list[dict]:
        result, seen = [], set()
        if self._stored_reference_cache is None:
            with self.database._connection() as connection:
                self._stored_reference_cache = {row[0]: (row[1], row[2]) for row in connection.execute("SELECT image_id,cache_key,features_json FROM annotation_learning_reference_features")}
        for row in self._verified():
            if row.get("split") != "train" or row.get("image_id") == exclude_image_id:
                continue
            identity = row.get("pixel_sha256") or row.get("image_sha256")
            group = row.get("group_id") or identity
            if identity == exclude_pixel or identity in seen:
                continue
            path = Path(row["image_path"])
            if not path.is_file():
                continue
            # Reference descriptors are rebuilt when labels or source bytes change.
            cache_key = f"visual-v2:{row['image_id']}:{row.get('revision', 0)}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
            cached = self._reference_cache.get(cache_key)
            try:
                stored = self._stored_reference_cache.get(row["image_id"])
                if cached is None and stored and stored[0] == cache_key:
                    values = json.loads(stored[1])
                    def restore(descriptor):
                        return {key: np.asarray(value, dtype=float) for key, value in descriptor.items()}
                    labels = {a["id"]: a for a in _annotations(row)}
                    cached = {"descriptor": restore(values["descriptor"]), "pixel_sha256": values["pixel_sha256"],
                              "objects": [dict(annotation=labels[item["id"]], descriptor=restore(item["descriptor"])) for item in values["objects"]]}
                    self._reference_cache[cache_key] = cached
                if cached is None:
                    with Image.open(path) as opened:
                        image = opened.convert("RGB")
                    actual_pixel = _pixels(image)
                    if actual_pixel == exclude_pixel:
                        continue
                    if row.get("image_sha256") and _sha(path) != row["image_sha256"]:
                        continue
                    labels = _validated(_annotations(row), image.width, image.height)
                    cached = {"descriptor": _descriptor(image), "objects": [dict(annotation=a, descriptor=_descriptor(image, a)) for a in labels],
                              "pixel_sha256": actual_pixel}
                    self._reference_cache[cache_key] = cached
                    def packed(descriptor):
                        return {key: value.tolist() for key, value in descriptor.items()}
                    serialized = _json({"descriptor": packed(cached["descriptor"]), "pixel_sha256": actual_pixel,
                        "objects": [{"id": item["annotation"]["id"], "descriptor": packed(item["descriptor"])} for item in cached["objects"]]})
                    with self.database._connection() as connection:
                        connection.execute("INSERT INTO annotation_learning_reference_features VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET cache_key=excluded.cache_key,features_json=excluded.features_json",
                                           (row["image_id"], cache_key, serialized))
                    self._stored_reference_cache[row["image_id"]] = (cache_key, serialized)
                if cached["pixel_sha256"] == exclude_pixel:
                    continue
            except (ValueError, TypeError, OSError, KeyError):
                continue
            seen.add(identity)
            result.append(dict(row, **cached, reference_group=group))
        return result

    def prepare_references(self) -> bool:
        """Prepare reusable feature evidence in the background, never labels."""
        if self._reference_preparing:
            return False
        self._reference_preparing = True
        def prepare():
            try:
                with self._lock:
                    rows = self._reference_rows()
                self._set_state("reference_index", {"status": "ready", "examples": len(rows)})
            except Exception as error:
                self._set_state("reference_index", {"status": "unavailable", "error": str(error)})
            finally:
                self._reference_preparing = False
        self._reference_thread = threading.Thread(target=prepare, name="annotation-reference-index", daemon=True)
        self._reference_thread.start()
        return True

    @staticmethod
    def _public_reference(row: dict, similarity: float) -> dict:
        return {"image_id": row["image_id"], "dataset_id": row.get("dataset_id"), "revision": row.get("revision"),
                "source": row.get("source"), "similarity": round(similarity, 4),
                "class_counts": dict(Counter(a["annotation"]["class_name"] for a in row["objects"]))}

    def references(self, image_path: Path | str, exclude_image_id: str | None = None, limit: int = 5) -> list[dict]:
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        descriptor = _descriptor(image)
        with self._lock:
            rows = self._reference_rows(exclude_image_id, _pixels(image))
            ranked = sorted(((_similarity(descriptor, row["descriptor"]), row) for row in rows), key=lambda item: item[0], reverse=True)
        return [self._public_reference(row, score) for score, row in ranked[:max(0, int(limit))]]

    def adapt(self, image_path: Path | str, annotations: list[dict], exclude_image_id: str | None = None) -> dict:
        """Use independent, close object references; all output still needs review.

        Class rewrites are disabled by default until separately evaluated.
        Three independent image groups must unanimously support a same-anatomy
        class, each with visual similarity >= .96, and beat contrary examples by
        .04. High-confidence model labels and every mask remain untouched.
        Anatomy conflicts/missing parts become review warnings only.
        """
        if self._reference_preparing:
            return {"annotations": deepcopy(annotations), "references": [], "warnings": ["Verified references are being indexed in the background; inspect this prediction before approving."], "version": self.deployed_version()}
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        result, warnings = deepcopy(annotations), []
        with self._lock:
            rows = self._reference_rows(exclude_image_id, _pixels(image))
            query_descriptor = _descriptor(image)
            ranked = sorted(((_similarity(query_descriptor, row["descriptor"]), row) for row in rows), key=lambda item: item[0], reverse=True)
            references = [self._public_reference(row, score) for score, row in ranked[:5]]
            for annotation in result:
                try:
                    _validated([annotation], image.width, image.height)
                    descriptor = _descriptor(image, annotation)
                    class_id = int(annotation["class_id"])
                    evidence = []
                    for row in rows:
                        candidates = [(_similarity(descriptor, obj["descriptor"]), obj) for obj in row["objects"]]
                        if candidates:
                            score, best = max(candidates, key=lambda item: item[0])
                            evidence.append((score, int(best["annotation"]["class_id"]), row["image_id"], row["reference_group"]))
                    evidence.sort(reverse=True, key=lambda item: item[0])
                    independent = {}
                    for item in evidence:
                        independent.setdefault(item[3], item)
                    close = [item for item in independent.values() if item[0] >= 0.96]
                    votes = Counter(item[1] for item in close)
                    original_confidence = float(annotation.get("confidence", 0.0) or 0.0)
                    if close:
                        winner, support = votes.most_common(1)[0]
                        opposition = max((item[0] for item in independent.values() if item[1] != winner), default=0.0)
                        supporters = [item for item in close if item[1] == winner]
                        strong = support >= 3 and support == len(close) and min(item[0] for item in supporters) - opposition >= 0.04
                        annotation["adaptive_evidence"] = {"suggested_class_id": winner, "supporting_images": support,
                                                           "reference_ids": [item[2] for item in supporters],
                                                           "minimum_similarity": round(min(item[0] for item in supporters), 4),
                                                           "applied": False}
                        annotation["adaptive_evidence"]["strong_support"] = strong
                        if self.enable_reference_class_updates and winner != class_id and strong and _part(winner) == _part(class_id) and original_confidence < 0.6:
                            annotation["adaptive_evidence"].update(applied=True, original_class_id=class_id)
                            annotation.update(class_id=winner, class_name=SOURCE_CLASSES[winner])
                        elif winner != class_id:
                            warnings.append(f"Review annotation {annotation.get('id', '')}: verified visual references disagree with its class.")
                    if not close or original_confidence < 0.6:
                        annotation["needs_review"] = True
                except (ValueError, TypeError, KeyError):
                    annotation["needs_review"] = True
                    warnings.append(f"Annotation {annotation.get('id', '')} needs a valid mask and class before learning.")
            # Relationships are diagnostic only: never add a part from history.
            groups: dict[str, set[str]] = defaultdict(set)
            for annotation in result:
                # Imported parts without actual whole-fish ownership cannot
                # establish relationships or missing-part evidence.
                if annotation.get("fish_id") is not None:
                    groups[str(annotation["fish_id"])].add(_part(int(annotation.get("class_id", -1))))
            for fish_id, present in groups.items():
                missing = {"Head", "Body", "Tail"} - present
                if missing:
                    warnings.append(f"Fish {fish_id}: check for missing {', '.join(sorted(missing))}; no annotation was invented.")
        if not references:
            warnings.append("No independent verified training references are available; review the model output.")
        return {"annotations": result, "references": references, "warnings": list(dict.fromkeys(warnings)), "version": self.deployed_version()}

    def _feedback_tokens(self, rows=None) -> list[str]:
        tokens, seen = [], set()
        for row in self._verified() if rows is None else rows:
            if row.get("split") != "train" or (row.get("source") == "manual" and not row.get("feedback_eligible")):
                continue
            identity = row.get("pixel_sha256") or row.get("image_sha256")
            if identity in seen:
                continue
            seen.add(identity)
            tokens.append(self._feedback_token(row))
        return sorted(tokens)

    @staticmethod
    def _feedback_token(row: dict) -> str:
        labels = _signature(row.get("annotations", []), row["width"], row["height"])
        return f"{row.get('pixel_sha256') or row.get('image_sha256')}:{sha256(labels.encode()).hexdigest()}"

    def _pending_feedback_groups(self, rows=None) -> int:
        trained = set(self._state("trained_feedback_tokens", []))
        return len({(row.get("dataset_id"), row.get("group_id") or row.get("pixel_sha256")) for row in (self._verified() if rows is None else rows)
                    if row.get("split") == "train" and (row.get("source") != "manual" or row.get("feedback_eligible"))
                    and self._feedback_token(row) not in trained})

    def status(self) -> dict:
        stats = dict(self.store.stats())
        verified = self._verified()
        trained = set(self._state("trained_feedback_tokens", []))
        pending = len(set(self._feedback_tokens(verified)) - trained)
        with self.database._connection() as connection:
            latest = connection.execute("SELECT * FROM annotation_learning_runs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
        latest_info = dict(latest) if latest else None
        if latest_info:
            latest_info["details"] = json.loads(latest_info.pop("details_json"))
        missing_validation = self._missing_validation_classes(verified)
        return dict(stats, deployed_model_version=self.deployed_version(), pending_training_examples=pending,
                    latest_evaluation=latest_info, training_threshold=self.min_examples,
                    pending_independent_groups=self._pending_feedback_groups(verified),
                    reference_index={"status": "indexing"} if self._reference_preparing else self._state("reference_index", {"status": "not_started"}),
                    training_available=bool(self.deployed_checkpoint()),
                    missing_validation_classes=missing_validation,
                    training_blocked_reason=("Immutable validation set lacks: " + ", ".join(missing_validation)) if missing_validation else None,
                    mechanism="verified visual references; thresholded local segmentation fine-tuning",
                    measured_improvement=bool(latest_info and latest_info["status"] == "promoted"))

    def _missing_validation_classes(self, rows=None) -> list[str]:
        coverage = {a["class_id"] for row in (self._verified() if rows is None else rows) if row.get("source") == "manual" and row.get("split") in {"val", "valid"}
                    for a in _annotations(row, original=True)}
        return [SOURCE_CLASSES[c] for c in sorted(set(SOURCE_CLASSES) - coverage)]

    def _dataset_rows(self, *, allow_incomplete_validation: bool = False) -> tuple[list[dict], list[dict]]:
        """Preserve original baseline labels and reject cross-split leakage."""
        rows, exclusions = [], []
        identities: dict[str, dict] = {}
        groups: dict[tuple, str] = {}
        for source in self._verified():
            row = dict(source)
            if not row.get("training_eligible", True):
                exclusions.append({"image_id": row.get("image_id"), "reason": "Imported baseline masks await complete human verification before model training."})
                continue
            split = "val" if row.get("split") == "valid" else row.get("split")
            if split not in {"train", "val", "test"}:
                exclusions.append({"image_id": row.get("image_id"), "reason": "No established dataset split."})
                continue
            if split != "train" and row.get("source") != "manual":
                exclusions.append({"image_id": row.get("image_id"), "reason": "Evaluation feedback cannot alter the manual holdout."})
                continue
            path = Path(row["image_path"])
            if not path.is_file():
                raise ValueError(f"Verified source image is missing: {row.get('image_id')}")
            digest = _sha(path)
            if row.get("image_sha256") and row["image_sha256"] != digest:
                raise ValueError("A verified source image changed after annotation.")
            with Image.open(path) as image:
                width, height = image.size
                pixel = _pixels(image)
            if row.get("width", width) != width or row.get("height", height) != height:
                raise ValueError("Verified image dimensions changed.")
            labels = _validated(_annotations(row, original=True), width, height)
            row.update(split=split, annotations=labels, image_sha256=digest, pixel_sha256=pixel, width=width, height=height)
            if source.get("source") == "manual" and _signature(labels, width, height) != _signature(_annotations(source), width, height):
                exclusions.append({"image_id": row.get("image_id"), "reason": "Edited manual labels kept separate; immutable baseline exported."})
            # A content identity crossing datasets is still leakage. Group IDs
            # are scoped by dataset because unrelated datasets can use '1'.
            group = (row.get("dataset_id"), row.get("group_id") or pixel)
            if group in groups and groups[group] != split:
                raise ValueError("An image group crosses training/evaluation splits; preserve the evaluation protocol before training.")
            groups[group] = split
            existing = identities.get(pixel)
            if existing:
                if existing["split"] != split:
                    raise ValueError("Duplicate image pixels cross training/evaluation splits.")
                if _signature(existing["annotations"], width, height) != _signature(labels, width, height):
                    raise ValueError("Contradictory verified annotations exist for the same image pixels.")
                exclusions.append({"image_id": row.get("image_id"), "reason": "Duplicate image pixels; not an independent example."})
                continue
            identities[pixel] = row
            rows.append(row)
        if not any(row["split"] == "train" for row in rows):
            raise ValueError("A verified training baseline is required.")
        if not any(row["split"] == "val" for row in rows):
            raise ValueError("A separate immutable manual validation set is required; evaluation data is never split from feedback automatically.")
        coverage = {a["class_id"] for row in rows if row["split"] == "val" for a in row["annotations"]}
        if coverage != set(SOURCE_CLASSES) and not allow_incomplete_validation:
            raise ValueError("The immutable validation set must cover all 12 source classes before automatic model promotion.")
        return rows, exclusions

    def build_dataset(self, *, allow_incomplete_validation: bool = False) -> dict:
        """Write a new immutable YOLO snapshot, never modifying source labels."""
        with self._lock:
            rows, exclusions = self._dataset_rows(allow_incomplete_validation=allow_incomplete_validation)
            source_rows = rows
            eligible = []
            for row in rows:
                try:
                    polygons = [yolo_polygon(_binary(a, row["width"], row["height"])) for a in row["annotations"]]
                except ValueError as error:
                    if row["split"] != "train":
                        raise ValueError("The immutable evaluation masks cannot be represented losslessly by YOLO: " + str(error)) from error
                    exclusions.append({"image_id": row.get("image_id"), "reason": "Excluded from auxiliary YOLO training; original masks retained: " + str(error)})
                    continue
                eligible.append(dict(row, yolo_polygons=polygons))
            rows = eligible
            if not any(row["split"] == "train" for row in rows):
                raise ValueError("No verified training masks can be represented losslessly by the auxiliary YOLO adapter.")
            version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
            destination = self.artifacts_dir / "datasets" / version
            destination.mkdir(parents=True, exist_ok=False)
            manifest = {"version": version, "created_at": _now(), "class_mapping": SOURCE_CLASSES,
                        "runtime_role": "auxiliary_annotation_only", "examples": [], "exclusions": exclusions,
                        "validation_protocol": "immutable manual val; test is preserved and never used for promotion"}
            validation_classes = {a["class_id"] for row in rows if row["split"] == "val" for a in row["annotations"]}
            manifest["missing_validation_classes"] = [SOURCE_CLASSES[c] for c in sorted(set(SOURCE_CLASSES) - validation_classes)]
            manifest["promotion_eligible"] = not manifest["missing_validation_classes"]
            for row in rows:
                split = row["split"]
                image_dir, label_dir = destination / split / "images", destination / split / "labels"
                image_dir.mkdir(parents=True, exist_ok=True)
                label_dir.mkdir(parents=True, exist_ok=True)
                token = row["pixel_sha256"]
                suffix = Path(row["image_path"]).suffix.lower()
                image_target = image_dir / (token + suffix)
                shutil.copy2(row["image_path"], image_target)
                if _sha(image_target) != row["image_sha256"]:
                    raise ValueError("Source image changed during dataset export.")
                lines = []
                for annotation, coordinates in zip(row["annotations"], row["yolo_polygons"]):
                    lines.append(str(annotation["class_id"]) + " " + " ".join(f"{value:.10f}" for value in coordinates))
                label_target = label_dir / (token + ".txt")
                label_target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                manifest["examples"].append({key: row.get(key) for key in ("image_id", "dataset_id", "split", "group_id", "source", "status", "revision", "image_sha256", "pixel_sha256", "model_version")})
                manifest["examples"][-1].update(label_sha256=_sha(label_target), annotations_sha256=sha256(_signature(row["annotations"], row["width"], row["height"]).encode()).hexdigest(),
                                                    image_file=str(image_target.relative_to(destination)), label_file=str(label_target.relative_to(destination)))
            config = {"path": str(destination), "train": "train/images", "val": "val/images", "names": SOURCE_CLASSES, "nc": len(SOURCE_CLASSES)}
            if any(row["split"] == "test" for row in rows):
                config["test"] = "test/images"
            # JSON is a YAML 1.2 subset and accepted by the existing YOLO loader.
            (destination / "data.yaml").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            manifest["data_yaml_sha256"] = _sha(destination / "data.yaml")
            manifest["validation_fingerprint"] = sha256(_json([a for a in manifest["examples"] if a["split"] == "val"]).encode()).hexdigest()
            source_snapshot = [{key: row.get(key) for key in ("image_id", "image_sha256", "dataset_id", "split", "group_id", "source", "revision", "annotations")} for row in source_rows]
            (destination / "source_annotations.json").write_text(json.dumps(source_snapshot, sort_keys=True) + "\n", encoding="utf-8")
            manifest["lossless_source_annotations_sha256"] = _sha(destination / "source_annotations.json")
            (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return dict(manifest, data_yaml=str(destination / "data.yaml"), manifest_path=str(destination / "manifest.json"))

    @staticmethod
    def verify_dataset(dataset: dict) -> None:
        root = Path(dataset["manifest_path"]).parent
        if _sha(root / "data.yaml") != dataset["data_yaml_sha256"] or _sha(root / "source_annotations.json") != dataset["lossless_source_annotations_sha256"]:
            raise ValueError("Versioned training dataset metadata changed; candidate rejected.")
        for example in dataset["examples"]:
            if _sha(root / example["image_file"]) != example["image_sha256"] or _sha(root / example["label_file"]) != example["label_sha256"]:
                raise ValueError("Versioned training image or labels changed; candidate rejected.")

    @staticmethod
    def compare_metrics(incumbent: Mapping[str, Any], candidate: Mapping[str, Any], min_improvement: float = 0.005) -> dict:
        """Require measured improvement and no regression in any reported metric."""
        mandatory = {"segmentation_map50_95", "detection_precision", "detection_recall"}
        if not mandatory <= set(incumbent) or set(incumbent) != set(candidate):
            return {"promote": False, "reason": "Both models must report the same complete validation metrics."}
        try:
            previous = {key: float(value) for key, value in incumbent.items()}
            proposed = {key: float(value) for key, value in candidate.items()}
            if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (*previous.values(), *proposed.values())):
                raise ValueError("Invalid metric")
        except (ValueError, TypeError):
            return {"promote": False, "reason": "Validation metrics must be finite values between zero and one."}
        regressions = [key for key in previous if proposed[key] + 1e-9 < previous[key]]
        delta = proposed["segmentation_map50_95"] - previous["segmentation_map50_95"]
        promote = not regressions and delta >= min_improvement
        return {"promote": promote, "reason": "Measured validation improvement with no reported regression." if promote else
                ("Validation regression: " + ", ".join(regressions) if regressions else "No measurable segmentation improvement."),
                "segmentation_map50_95_delta": delta, "regressions": regressions}

    def _create_run(self) -> str:
        run_id = uuid4().hex
        with self.database._connection() as connection:
            connection.execute("INSERT INTO annotation_learning_runs VALUES (?,?,?,NULL,NULL,?)", (run_id, "scheduled", _now(), _json({"owner_pid": os.getpid(), "owner_token": _PROCESS_TOKEN})))
        return run_id

    def _recover_abandoned_runs(self) -> None:
        """A dead worker cannot promote anything or block later batches forever."""
        with self.database._connection() as connection:
            rows = connection.execute("SELECT run_id,created_at,details_json FROM annotation_learning_runs WHERE status IN ('scheduled','training','evaluating')").fetchall()
            for row in rows:
                details = json.loads(row[2])
                pid = details.get("owner_pid")
                if isinstance(pid, int):
                    abandoned = not _process_alive(pid) or (pid == os.getpid() and details.get("owner_token") != _PROCESS_TOKEN)
                else:
                    # Legacy runs did not record ownership. Retain a short
                    # conservative grace period before marking interrupted.
                    created = datetime.fromisoformat(row[1]).timestamp()
                    abandoned = time.time() - created > 300
                if abandoned:
                    details["interrupted_reason"] = "Learning worker exited before completing evaluation; deployed checkpoint preserved."
                    connection.execute("UPDATE annotation_learning_runs SET status='interrupted',finished_at=?,details_json=? WHERE run_id=?", (_now(), _json(details), row[0]))

    def _update_run(self, run_id: str, status: str, details: dict, dataset_version: str | None = None) -> None:
        final = status in {"failed", "rejected", "promoted", "superseded"}
        with self.database._connection() as connection:
            connection.execute("UPDATE annotation_learning_runs SET status=?,finished_at=?,dataset_version=COALESCE(?,dataset_version),details_json=? WHERE run_id=?",
                               (status, _now() if final else None, dataset_version, _json(details), run_id))

    def train_candidate(self, *, _run_id: str | None = None, allow_incomplete_validation: bool = False) -> dict:
        """One controlled batch; fake adapters test the actual gate and registry."""
        import sqlite3
        with self._lock:
            try:
                run_id = _run_id or self._create_run()
            except sqlite3.IntegrityError:
                return {"status": "busy", "reason": "Another annotation learning run is active."}
            self._set_state("last_attempt_at", time.time())
            tokens = self._feedback_tokens()
            incumbent_version = self.deployed_version()
            checkpoint = self.deployed_checkpoint()
            details = {"incumbent_version": incumbent_version, "role": "auxiliary_annotation_only", "feedback_tokens": tokens,
                       "owner_pid": os.getpid(), "owner_token": _PROCESS_TOKEN}
        # Do not hold the service lock during expensive model work. Reviews,
        # references, status reads, and rollback must remain usable throughout.
        try:
            if not checkpoint:
                raise ValueError("No preserved local annotation segmentation checkpoint is configured; verified reference learning remains available.")
            dataset = self.build_dataset(allow_incomplete_validation=allow_incomplete_validation)
            details.update(dataset_manifest=dataset["manifest_path"], validation_fingerprint=dataset["validation_fingerprint"])
            self._update_run(run_id, "training", details, dataset["version"])
            self.verify_dataset(dataset)
            run_dir = self.artifacts_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            incumbent_path = Path(checkpoint)
            original_digest = _sha(incumbent_path)
            candidate_path = Path(self.adapter.train(incumbent_path, Path(dataset["data_yaml"]), run_dir / "training"))
            if _sha(incumbent_path) != original_digest:
                raise ValueError("Training altered the incumbent checkpoint; candidate rejected.")
            if not candidate_path.is_file() or candidate_path.resolve() == incumbent_path.resolve():
                raise ValueError("Training must produce a separate local candidate checkpoint.")
            candidate_digest = _sha(candidate_path)
            version = "annotation-" + candidate_digest[:12] + "-" + run_id[:8]
            preserved = self.artifacts_dir / "models" / (version + candidate_path.suffix)
            preserved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_path, preserved)
            if _sha(preserved) != candidate_digest:
                raise ValueError("Candidate checkpoint changed during preservation.")
            self._update_run(run_id, "evaluating", details)
            current_metrics = self.adapter.evaluate(incumbent_path, Path(dataset["data_yaml"]), run_dir / "incumbent")
            proposed_metrics = self.adapter.evaluate(preserved, Path(dataset["data_yaml"]), run_dir / "candidate")
            self.verify_dataset(dataset)
            decision = self.compare_metrics(current_metrics, proposed_metrics, self.min_improvement)
            if not dataset["promotion_eligible"]:
                decision.update(promote=False, reason="Incomplete immutable validation coverage: " + ", ".join(dataset["missing_validation_classes"]))
            details.update(incumbent_metrics=current_metrics, candidate_metrics=proposed_metrics,
                           comparison=decision, candidate_version=version, candidate_checkpoint=str(preserved), candidate_sha256=candidate_digest)
            with self._lock:
                # A rollback or explicit selection made during training wins.
                if self.deployed_version() != incumbent_version:
                    self._update_run(run_id, "superseded", details)
                    return dict(details, status="superseded", run_id=run_id)
                with self.database._connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current = connection.execute("SELECT value_json FROM annotation_learning_state WHERE key='deployed_version'").fetchone()
                    if current is None or json.loads(current[0]) != incumbent_version:
                        details["superseded_reason"] = "Annotation model selection changed during candidate evaluation."
                        connection.execute("UPDATE annotation_learning_runs SET status='superseded',finished_at=?,details_json=? WHERE run_id=?", (_now(), _json(details), run_id))
                        return dict(details, status="superseded", run_id=run_id)
                    connection.execute("INSERT INTO annotation_learning_models VALUES (?,?,?,?,?,?,?)", (version, str(preserved), candidate_digest,
                                       _now(), incumbent_version, run_id, _json(proposed_metrics)))
                    if decision["promote"]:
                        connection.execute("UPDATE annotation_learning_state SET value_json=? WHERE key='deployed_version'", (_json(version),))
                    connection.execute("INSERT INTO annotation_learning_state VALUES ('trained_feedback_tokens',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (_json(tokens),))
                    result = "promoted" if decision["promote"] else "rejected"
                    # Selection, source-data consumption and completed
                    # evaluation commit together. A crash cannot select a
                    # candidate whose evaluation is still marked unfinished.
                    connection.execute("UPDATE annotation_learning_runs SET status=?,finished_at=?,details_json=? WHERE run_id=?",
                                       (result, _now(), _json(details), run_id))
            return dict(details, status=result, run_id=run_id)
        except Exception as error:
            details["error"] = str(error)
            self._update_run(run_id, "failed", details)
            return dict(details, status="failed", run_id=run_id)

    def maybe_schedule(self) -> dict:
        """Nonblocking, threshold + cooldown scheduling, never every approval."""
        import sqlite3
        with self._lock:
            self._recover_abandoned_runs()
            pending = len(set(self._feedback_tokens()) - set(self._state("trained_feedback_tokens", [])))
            if pending < self.min_examples:
                return {"scheduled": False, "reason": "Accumulating verified examples.", "pending": pending}
            if self._pending_feedback_groups() < self.min_examples:
                return {"scheduled": False, "reason": "Accumulating independent verified source groups.", "pending": pending}
            missing_validation = self._missing_validation_classes()
            if missing_validation:
                return {"scheduled": False, "reason": "Immutable validation coverage is incomplete.", "missing_validation_classes": missing_validation, "pending": pending}
            if not self.deployed_checkpoint():
                return {"scheduled": False, "reason": "No compatible local annotation checkpoint is configured.", "pending": pending}
            if time.time() - self._state("last_attempt_at", 0) < self.cooldown_seconds:
                return {"scheduled": False, "reason": "Learning cooldown is active.", "pending": pending}
            try:
                run_id = self._create_run()
            except sqlite3.IntegrityError:
                return {"scheduled": False, "reason": "An annotation learning run is already active.", "pending": pending}
            self._thread = threading.Thread(target=self.train_candidate, kwargs={"_run_id": run_id}, name="annotation-learning", daemon=True)
            self._thread.start()
            return {"scheduled": True, "run_id": run_id, "pending": pending}

    def rollback(self, version: str | None = None) -> dict:
        """Select a preserved prior accepted model; rejected candidates stay rejected."""
        with self._lock:
            version = version or self._state("original_version")
            with self.database._connection() as connection:
                row = connection.execute("SELECT m.*,r.status AS run_status FROM annotation_learning_models m LEFT JOIN annotation_learning_runs r ON r.run_id=m.run_id WHERE m.version=?", (version,)).fetchone()
                if row is None or (row["run_id"] is not None and row["run_status"] != "promoted"):
                    raise ValueError("Rollback requires an original or previously promoted annotation model.")
                path = Path(row["checkpoint"])
                if not path.is_file() or _sha(path) != row["sha256"]:
                    raise ValueError("Rollback checkpoint is missing or has changed.")
                previous = self.deployed_version()
                connection.execute("UPDATE annotation_learning_state SET value_json=? WHERE key='deployed_version'", (_json(version),))
                connection.execute("INSERT INTO annotation_learning_state VALUES ('latest_rollback',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (_json({"from": previous, "to": version, "at": _now()}),))
            return {"deployed_model_version": version, "previous_version": previous}
