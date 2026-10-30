"""Evaluate the active Model 2 detector against COCO *part* bounding boxes.

This command deliberately measures only the checkpoint's 12 trained
grade-and-anatomy part classes.  It does not associate parts to physical fish,
invoke Model 1, or claim whole-fish grading accuracy.  The current Roboflow
export also has known historical-training overlap, so its reported metrics are
development/compatibility evidence rather than an independent performance
estimate.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from src.evaluation.comparison_protocol import PROTOCOL, evaluate_boxes
from src.inference.model_registry import ModelEntry, get_model_registry
from src.inference.yolo_quality_model import YoloQualityModel
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES, SOURCE_NAME_TO_ID, source_image_name
from src.preprocessing.dataset_utils import project_root


COCO_SPLITS = ("train", "valid", "test")
SCHEMA = "active-model2-coco-part-compatibility-v1"
PARENT_CATEGORY = "dried-fish-quality-grades"


class CocoPartEvaluationError(ValueError):
    """Raised when a COCO export cannot be safely evaluated as part boxes."""


@dataclass(frozen=True)
class CocoPartSplit:
    """Parsed COCO part records for one export split."""

    name: str
    annotation_path: Path
    annotation_sha256: str
    records: tuple[dict[str, Any], ...]
    image_metadata: tuple[dict[str, Any], ...]
    category_mapping: dict[int, int]

    @property
    def annotation_count(self) -> int:
        return sum(len(record["boxes"]) for record in self.records)


def sha256_file(path: Path) -> str:
    """Return a full SHA-256 digest without loading an entire file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise CocoPartEvaluationError(f"{field} must be an integer, not a boolean.")
    try:
        converted = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CocoPartEvaluationError(f"{field} must be an integer.") from exc
    if converted != value:
        raise CocoPartEvaluationError(f"{field} must be an integer.")
    return converted


def _safe_image_name(value: object, split: str) -> str:
    name = str(value or "").strip()
    candidate = Path(name)
    if not name or candidate.name != name or name in {".", ".."}:
        raise CocoPartEvaluationError(f"Unsafe or empty image filename in {split}: {value!r}")
    return name


def _category_mapping(categories: Iterable[object], split: str) -> dict[int, int]:
    """Map COCO category IDs to the model's immutable source class IDs."""

    mapping: dict[int, int] = {}
    seen_ids: set[int] = set()
    unexpected_names: list[str] = []
    for category in categories:
        if not isinstance(category, dict):
            raise CocoPartEvaluationError(f"{split} contains a non-object category record.")
        category_id = _require_int(category.get("id"), f"{split} category id")
        if category_id in seen_ids:
            raise CocoPartEvaluationError(f"{split} contains duplicate category id {category_id}.")
        seen_ids.add(category_id)
        name = str(category.get("name", "")).strip()
        source_id = SOURCE_NAME_TO_ID.get(name)
        if source_id is not None:
            mapping[category_id] = source_id
        elif name != PARENT_CATEGORY:
            unexpected_names.append(name or "<empty>")

    if unexpected_names:
        raise CocoPartEvaluationError(
            f"{split} has unsupported COCO categories: {', '.join(sorted(unexpected_names))}."
        )
    if set(mapping.values()) != set(SOURCE_CLASSES):
        missing = [name for index, name in SOURCE_CLASSES.items() if index not in mapping.values()]
        raise CocoPartEvaluationError(
            f"{split} does not contain the complete 12-class Model 2 vocabulary; missing: {missing}."
        )
    return mapping


def load_coco_part_split(dataset_root: Path, split: str) -> CocoPartSplit:
    """Read one COCO split as non-mutating box-evaluation records.

    COCO polygons remain untouched because the active checkpoint is a detection
    model.  Its measured target is the export's own bounding-box field.
    """

    if split not in COCO_SPLITS:
        raise CocoPartEvaluationError(f"Unknown COCO split {split!r}; expected one of {COCO_SPLITS}.")
    split_root = dataset_root / split
    annotation_path = split_root / "_annotations.coco.json"
    if not annotation_path.is_file():
        raise CocoPartEvaluationError(f"COCO annotations are missing: {annotation_path}")
    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CocoPartEvaluationError(f"Cannot read {annotation_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CocoPartEvaluationError(f"{annotation_path} must contain a JSON object.")

    images = payload.get("images")
    annotations = payload.get("annotations")
    categories = payload.get("categories")
    if not isinstance(images, list) or not isinstance(annotations, list) or not isinstance(categories, list):
        raise CocoPartEvaluationError(f"{annotation_path} needs images, annotations, and categories arrays.")
    category_mapping = _category_mapping(categories, split)

    image_by_id: dict[int, dict[str, Any]] = {}
    image_paths: dict[int, Path] = {}
    for image in images:
        if not isinstance(image, dict):
            raise CocoPartEvaluationError(f"{split} contains a non-object image record.")
        image_id = _require_int(image.get("id"), f"{split} image id")
        if image_id in image_by_id:
            raise CocoPartEvaluationError(f"{split} contains duplicate image id {image_id}.")
        name = _safe_image_name(image.get("file_name"), split)
        width = _require_int(image.get("width"), f"{split} image {name} width")
        height = _require_int(image.get("height"), f"{split} image {name} height")
        if width <= 0 or height <= 0:
            raise CocoPartEvaluationError(f"{split} image {name} has non-positive dimensions.")
        path = split_root / name
        if not path.is_file():
            raise CocoPartEvaluationError(f"COCO image referenced by {split} is missing: {path}")
        image_by_id[image_id] = {"id": image_id, "file_name": name, "width": width, "height": height}
        image_paths[image_id] = path

    annotations_by_image: dict[int, list[tuple[int, list[float]]]] = {image_id: [] for image_id in image_by_id}
    annotation_ids: set[int] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise CocoPartEvaluationError(f"{split} contains a non-object annotation record.")
        annotation_id = _require_int(annotation.get("id"), f"{split} annotation id")
        if annotation_id in annotation_ids:
            raise CocoPartEvaluationError(f"{split} contains duplicate annotation id {annotation_id}.")
        annotation_ids.add(annotation_id)
        if bool(annotation.get("iscrowd")):
            raise CocoPartEvaluationError(
                f"{split} annotation {annotation_id} uses iscrowd, which this box protocol does not support."
            )
        image_id = _require_int(annotation.get("image_id"), f"{split} annotation {annotation_id} image_id")
        if image_id not in image_by_id:
            raise CocoPartEvaluationError(f"{split} annotation {annotation_id} references an unknown image.")
        category_id = _require_int(annotation.get("category_id"), f"{split} annotation {annotation_id} category_id")
        if category_id not in category_mapping:
            raise CocoPartEvaluationError(
                f"{split} annotation {annotation_id} is not one of the 12 trained part categories."
            )
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise CocoPartEvaluationError(f"{split} annotation {annotation_id} has an invalid COCO bbox.")
        try:
            x, y, width, height = (float(value) for value in bbox)
        except (TypeError, ValueError) as exc:
            raise CocoPartEvaluationError(f"{split} annotation {annotation_id} has non-numeric bbox values.") from exc
        if not all(math.isfinite(value) for value in (x, y, width, height)) or width <= 0 or height <= 0:
            raise CocoPartEvaluationError(f"{split} annotation {annotation_id} has an invalid COCO bbox.")
        image = image_by_id[image_id]
        if x < 0 or y < 0 or x + width > image["width"] + 1e-6 or y + height > image["height"] + 1e-6:
            raise CocoPartEvaluationError(f"{split} annotation {annotation_id} extends outside its image.")
        annotations_by_image[image_id].append(
            (category_mapping[category_id], [x, y, x + width, y + height])
        )

    records: list[dict[str, Any]] = []
    ordered_metadata: list[dict[str, Any]] = []
    for image_id, image in sorted(image_by_id.items(), key=lambda item: item[1]["file_name"]):
        pairs = annotations_by_image[image_id]
        records.append(
            {
                "image": image["file_name"],
                "path": image_paths[image_id],
                "boxes": [box for _, box in pairs],
                "labels": [label for label, _ in pairs],
                "width": image["width"],
                "height": image["height"],
            }
        )
        ordered_metadata.append(dict(image))

    return CocoPartSplit(
        name=split,
        annotation_path=annotation_path,
        annotation_sha256=sha256_file(annotation_path),
        records=tuple(records),
        image_metadata=tuple(ordered_metadata),
        category_mapping=category_mapping,
    )


def _load_active_model(
    model_id: str | None,
    device: str,
    operating_confidence: float,
) -> tuple[YoloQualityModel, ModelEntry]:
    registry = get_model_registry()
    selected_id = model_id or registry.get_persisted_model2_id()
    entry = registry.get_model(selected_id)
    if entry is None:
        raise CocoPartEvaluationError(f"Model ID {selected_id!r} is not in the registry.")
    compatible, reason = registry.validate_compatibility(entry.id, "model2_grading")
    if not compatible:
        raise CocoPartEvaluationError(reason or f"Model {entry.id!r} is not compatible with Model 2 grading.")
    if entry.task != "detect" or entry.input_size <= 0:
        raise CocoPartEvaluationError(
            f"This evaluator requires a registered detection model with a positive input size; got {entry.id!r}."
        )
    normalized_names = {int(index): str(name) for index, name in entry.class_names.items()}
    if normalized_names != SOURCE_CLASSES:
        raise CocoPartEvaluationError("The selected registry entry does not use the expected 12 part classes.")
    checkpoint = registry.resolve_checkpoint_path(entry)
    model = YoloQualityModel(
        checkpoint,
        confidence_threshold=operating_confidence,
        device=device,
        image_size=entry.input_size,
        quality_inference_mode="full_frame",
        model_id=entry.id,
    )
    # The production adapter has already performed integrity, task, and exact
    # class-order checks when this returns True.
    if not model.load():
        raise CocoPartEvaluationError(model.error or "The active Model 2 checkpoint could not be loaded.")
    return model, entry


def predict_part_boxes(
    model: YoloQualityModel,
    records: Iterable[dict[str, Any]],
    *,
    prediction_floor: float,
) -> list[dict[str, Any]]:
    """Run the production Model 2 adapter once per exported image.

    Raw detections use the fixed .001 evaluation floor so ranked AP is not
    artificially cut at the deployment threshold.  Fixed-threshold P/R is
    calculated later at the registered runtime confidence (.25 for the active
    checkpoint).
    """

    if not 0.0 < prediction_floor <= 1.0:
        raise CocoPartEvaluationError("prediction_floor must be in (0, 1].")
    if model.adapter is None or not model.adapter.is_loaded:
        raise CocoPartEvaluationError("The production Model 2 adapter is not loaded.")
    try:
        import cv2
    except ImportError as exc:
        raise CocoPartEvaluationError("OpenCV is required to feed images through the production Model 2 adapter.") from exc

    rows: list[dict[str, Any]] = []
    records = tuple(records)
    for index, record in enumerate(records, start=1):
        image_path = record["path"]
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise CocoPartEvaluationError(f"OpenCV could not read COCO image: {image_path}")
        height, width = image.shape[:2]
        if (width, height) != (record["width"], record["height"]):
            raise CocoPartEvaluationError(
                f"COCO metadata dimensions disagree with the pixels for {image_path.name}: "
                f"metadata={record['width']}x{record['height']}, pixels={width}x{height}."
            )
        # debug_raw=True is the adapter's explicit, documented .001 floor.
        _, raw = model.adapter.predict(
            image=image,
            conf_threshold=prediction_floor,
            image_size=model.image_size,
            debug_raw=True,
        )
        rows.append(
            {
                "image": record["image"],
                "boxes": [list(part.bbox) for part in raw],
                "labels": [part.source_class_id for part in raw],
                "scores": [part.confidence for part in raw],
            }
        )
        if index == len(records) or index % 10 == 0:
            print(f"  inferred {index}/{len(records)} images", flush=True)
    return rows


def _read_manifest_hashes(path: Path) -> set[str]:
    """Read a legacy training manifest only when explicitly supplied."""

    if not path.is_file():
        raise CocoPartEvaluationError(f"Training manifest was not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "original_sha256" not in reader.fieldnames:
            raise CocoPartEvaluationError(f"Training manifest lacks original_sha256: {path}")
        return {
            value.strip().lower()
            for row in reader
            if (value := str(row.get("original_sha256", ""))).strip()
        }


def training_manifest_overlap(records: Iterable[dict[str, Any]], manifest_path: Path | None) -> dict[str, Any] | None:
    """Report exact byte overlap with a supplied historical training manifest."""

    if manifest_path is None:
        return None
    known_hashes = _read_manifest_hashes(manifest_path)
    rows = tuple(records)
    matched = sum(sha256_file(record["path"]) in known_hashes for record in rows)
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_hash_field": "original_sha256",
        "matching_export_images": matched,
        "evaluated_export_images": len(rows),
        "independent": False,
        "interpretation": (
            "Any nonzero exact-byte overlap means this split is not an independent evaluation "
            "against that historical training manifest."
        ),
    }


def _split_payload(
    split: CocoPartSplit,
    predictions: list[dict[str, Any]],
    operating_confidence: float,
    manifest_path: Path | None,
) -> dict[str, Any]:
    truth = [
        {"image": record["image"], "boxes": record["boxes"], "labels": record["labels"]}
        for record in split.records
    ]
    metrics = evaluate_boxes(truth, predictions, confidence=operating_confidence)
    class_counts = {name: 0 for name in SOURCE_CLASSES.values()}
    for record in split.records:
        for label in record["labels"]:
            class_counts[SOURCE_CLASSES[label]] += 1
    return {
        "images": len(split.records),
        "annotations": split.annotation_count,
        "annotation_path": str(split.annotation_path.resolve()),
        "annotation_sha256": split.annotation_sha256,
        "class_support": class_counts,
        "category_id_to_model_class_id": {str(key): value for key, value in sorted(split.category_mapping.items())},
        "metrics": metrics,
        "historical_training_manifest_overlap": training_manifest_overlap(split.records, manifest_path),
    }


def build_report(
    *,
    entry: ModelEntry,
    model: YoloQualityModel,
    dataset_root: Path,
    split_reports: dict[str, dict[str, Any]],
    split_sources: dict[str, CocoPartSplit],
    prediction_floor: float,
    device: str,
) -> dict[str, Any]:
    """Build a fully self-describing, intentionally narrow report."""

    source_groups: dict[str, set[str]] = {}
    for split_name, split in split_sources.items():
        for image in split.image_metadata:
            source_groups.setdefault(source_image_name(image), set()).add(split_name)
    shared_sources = {
        name: sorted(splits)
        for name, splits in sorted(source_groups.items())
        if len(splits) > 1
    }
    return {
        "schema": SCHEMA,
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
        "result_label": "development_compatibility_part_detection_only",
        "scope": {
            "measures": "12-class part bounding-box detection",
            "does_not_measure": [
                "whole-fish detection",
                "part-to-fish ownership association",
                "final weighted fish grade",
                "fish-level accuracy",
                "specimen-independent generalization",
            ],
        },
        "model": {
            "id": entry.id,
            "display_name": entry.display_name,
            "checkpoint_path": str(model.weights_path.resolve()) if model.weights_path else None,
            "checkpoint_sha256": model.checkpoint_sha256_full,
            "checkpoint_integrity": model.checkpoint_integrity,
            "task": entry.task,
            "input_size": model.image_size,
            "runtime_adapter": entry.adapter,
            "class_names": {str(index): name for index, name in SOURCE_CLASSES.items()},
        },
        "inference": {
            "device_requested": device,
            "device_resolved": str(model.device),
            "prediction_floor": prediction_floor,
            "operating_confidence": model.confidence_threshold,
            "nms": "Ultralytics default adapter settings (the production runtime path)",
            "per_image_execution": True,
        },
        "metrics_protocol": {
            "name": PROTOCOL,
            "matching": "class-aware greedy matching",
            "iou_thresholds": "0.50:0.05:0.95",
            "ap_interpolation": "101-point",
            "fixed_operating_point": {"confidence": model.confidence_threshold, "iou": 0.50},
            "undefined_classes": "excluded from macro means; never set to zero",
        },
        "dataset": {
            "root": str(dataset_root.resolve()),
            "source_format": "Roboflow COCO segmentation export; COCO bbox fields evaluated",
            "exported_image_preprocessing": "640x640 fit/white edges plus adaptive equalization (per README.dataset.txt)",
            "selected_splits": list(split_reports),
            "within_selected_export_source_groups_crossing_splits": shared_sources,
        },
        "splits": split_reports,
        "limitations": [
            "COCO labels are independent anatomical-part instances, not adjudicated whole-fish identities or grades.",
            "This report therefore cannot validate Model 1, part ownership, the weighted grading policy, or fish-level accuracy.",
            "A supplied historical training manifest is checked by exact image SHA-256; any matching images make that split non-independent.",
            "Sparse or absent classes in a split yield unstable or unavailable per-class estimates; macro values exclude unavailable classes.",
            "The export's preprocessed 640x640 images are not a substitute for a prospective deployment-camera evaluation.",
        ],
    }


def _default_dataset_root() -> Path:
    return project_root() / "Dried Fish Quality Grading.v7i.coco-segmentation"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=_default_dataset_root())
    parser.add_argument("--model-id", default=None, help="Registered Model 2 ID (defaults to the persisted active ID).")
    parser.add_argument("--device", default="auto", help="Production adapter device request (default: auto).")
    parser.add_argument(
        "--operating-confidence",
        type=float,
        default=0.25,
        help="Fixed Model 2 deployment confidence for P/R (default: 0.25).",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        choices=COCO_SPLITS,
        default=list(COCO_SPLITS),
        help="COCO export splits to evaluate (default: train valid test).",
    )
    parser.add_argument(
        "--prediction-floor",
        type=float,
        default=0.001,
        help="Raw prediction floor used for ranked AP (default: 0.001).",
    )
    parser.add_argument(
        "--training-manifest",
        type=Path,
        default=None,
        help="Optional historical manifest with original_sha256; reports exact exposure overlap.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root() / "results" / "evaluation" / "active_model2_coco_part_compatibility.json",
        help="JSON report path; existing files are replaced only when this explicit path is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    dataset_root = args.dataset_root.resolve()
    requested_splits = tuple(dict.fromkeys(args.splits))
    if not dataset_root.is_dir():
        raise CocoPartEvaluationError(f"Dataset root does not exist: {dataset_root}")
    if not 0.0 < args.prediction_floor <= 1.0:
        raise CocoPartEvaluationError("--prediction-floor must be in (0, 1].")
    if not 0.0 <= args.operating_confidence <= 1.0:
        raise CocoPartEvaluationError("--operating-confidence must be in [0, 1].")

    print("Loading and validating the active Model 2 production adapter...", flush=True)
    model, entry = _load_active_model(args.model_id, args.device, args.operating_confidence)
    split_sources = {split: load_coco_part_split(dataset_root, split) for split in requested_splits}
    reports: dict[str, dict[str, Any]] = {}
    for split, source in split_sources.items():
        print(f"Evaluating {split}: {len(source.records)} images, {source.annotation_count} part boxes", flush=True)
        predictions = predict_part_boxes(model, source.records, prediction_floor=args.prediction_floor)
        reports[split] = _split_payload(
            source,
            predictions,
            operating_confidence=model.confidence_threshold,
            manifest_path=args.training_manifest.resolve() if args.training_manifest else None,
        )
        overall = reports[split]["metrics"]["overall"]
        print(
            f"  {split} part-box compatibility: mAP50={overall['mAP50']:.4f}, "
            f"mAP50-95={overall['mAP50_95']:.4f}, "
            f"P={overall['Precision']:.4f}, R={overall['Recall']:.4f}",
            flush=True,
        )

    report = build_report(
        entry=entry,
        model=model,
        dataset_root=dataset_root,
        split_reports=reports,
        split_sources=split_sources,
        prediction_floor=args.prediction_floor,
        device=args.device,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Compatibility report written: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
