"""Annotation management views over the shared annotation workspace store.

This module owns no database, images, annotation engine, or competing state.
It adapts the canonical workspace documents for a paginated review library and
exports saved snapshots with their original source records and mask geometry.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
import json
import math
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import unquote
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image
from starlette.background import BackgroundTask

from src.annotation.store import AnnotationError, AnnotationStore, NotFound, RevisionConflict


LIBRARY_STATUSES = {"not_annotated", "ai_annotated", "needs_review", "approved", "edited", "rejected"}
REVIEW_STATUSES = {"pending", "needs_review", "reviewed", "approved", "needs_correction", "rejected"}


def _dataset_identity(document: dict) -> str:
    """Read dataset ownership without rewriting saved revisions or source data."""
    metadata = document.get("metadata") or {}
    baseline = document.get("baseline") or {}
    for value in (document.get("dataset_id"), metadata.get("dataset_id"), baseline.get("dataset_id")):
        if isinstance(value, str) and value.strip():
            return value
    # Historical V2 baseline documents predate the dataset registry. They stay
    # in their own collection; importing the cleaned ZIP never moves them.
    if baseline:
        return "v2-coco-v7"
    source_path = document.get("source_path") or metadata.get("source_path")
    if isinstance(source_path, str) and source_path:
        return Path(source_path).parent.parent.name or "uploads"
    return "uploads"


def _dataset_catalog(store: AnnotationStore, rows: list[dict]) -> dict:
    """Wrap the canonical registry, deriving only unregistered historical views."""
    counts: dict[str, int] = {}
    for row in rows:
        identity = _dataset_identity(row)
        counts[identity] = counts.get(identity, 0) + 1
    registry = getattr(store, "datasets", None)
    if callable(registry):
        catalog = deepcopy(registry())
        if not isinstance(catalog, dict) or not isinstance(catalog.get("datasets"), list):
            raise AnnotationError("The annotation dataset registry is unavailable. Retry loading the library.")
    else:
        catalog = {"datasets": [], "primary_dataset_id": None}
    seen = set()
    for dataset in catalog["datasets"]:
        if not isinstance(dataset, dict) or not isinstance(dataset.get("id"), str) or not dataset["id"] or dataset["id"] in seen:
            raise AnnotationError("The annotation dataset registry contains an invalid dataset identity.")
        seen.add(dataset["id"])
        dataset["dataset_id"] = dataset["id"]
        dataset["image_count"] = counts.get(dataset["id"], 0)
    # Older uploads can exist before a registry is introduced. Expose their
    # saved ownership as a view, without creating another registry or database.
    for identity, count in sorted(counts.items()):
        if identity not in seen:
            catalog["datasets"].append({"id": identity, "dataset_id": identity,
                "name": "Uploaded annotation images" if identity == "uploads" else identity,
                "primary": False, "registered": False, "image_count": count})
    return catalog


def _dataset_filter(value: object, catalog: dict, *, optional: bool = True) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 240 or any(ord(character) < 32 for character in value):
        raise AnnotationError("Choose a valid dataset ID, or omit dataset_id to include all saved datasets.")
    if value not in {dataset["id"] for dataset in catalog["datasets"]}:
        raise AnnotationError(f"Unknown annotation dataset: {value}. Reload the dataset list before retrying.")
    return value


def _json(value: object) -> str:
    """Fail before a download if saved metadata cannot be encoded as valid JSON."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _source(annotation: dict) -> str:
    metadata = annotation.get("metadata", {})
    source = annotation.get("source")
    if annotation.get("status") == "corrected" or metadata.get("human_corrected"):
        return "human_corrected"
    if source in {"automated", "ai", "ai_generated"}:
        return "ai_generated"
    if source == "manual" and (annotation.get("original_annotation") or annotation.get("source_annotation_id") is not None or metadata.get("source_record") or metadata.get("source_annotation_id") is not None or metadata.get("source_coco_id") is not None):
        return "imported"
    if source in {"imported", "human_corrected"}:
        return source
    return "manual"


def normalize_document(document: dict, classes: list[dict], *, summary: bool = False) -> dict:
    """Expose one saved native document without inventing approval or association.

    The workspace's registry IDs remain canonical. An imported COCO category ID
    is additionally retained in ``metadata.source_record.category_id``; IDs from
    different source/model namespaces are never silently equated.
    """
    class_map = {item["id"]: item for item in classes}
    metadata = deepcopy(document.get("metadata", {}))
    native_status = document.get("status", "draft")
    annotations = document.get("annotations", [])
    sources = {_source(annotation) for annotation in annotations}
    if native_status == "approved":
        status, review_status = "approved", "approved"
    elif native_status == "rejected":
        status, review_status = "rejected", "rejected"
    elif not annotations:
        status, review_status = "not_annotated", "pending"
    else:
        status = "edited" if any(annotation.get("status") == "corrected" for annotation in annotations) else "ai_annotated" if sources == {"ai_generated"} else "needs_review"
        review_status = "needs_review"
    if native_status != "approved" and metadata.get("library_review_revision") == document.get("revision"):
        if metadata.get("library_status") in LIBRARY_STATUSES - {"approved"}:
            status = metadata["library_status"]
        if metadata.get("library_review_status") in REVIEW_STATUSES - {"approved"}:
            review_status = metadata["library_review_status"]
    image_id = str(document["id"])
    result = {"image_id": image_id, "file_name": document.get("filename", document.get("file_name", image_id)),
              "width": document["width"], "height": document["height"], "status": status,
              "review_status": review_status, "version": document.get("revision", 1),
              "created_at": document.get("created_at"), "updated_at": document.get("updated_at", document.get("modified_at", document.get("created_at"))),
              "saved": True, "dataset_id": _dataset_identity(document)}
    if "source_metadata" in document:
        result["source_metadata"] = deepcopy(document["source_metadata"])
    mapped = []
    for annotation in annotations:
        category = class_map.get(annotation.get("class_id"))
        if category is None:
            raise ValueError(f"Saved annotation {annotation.get('id')} refers to an unknown registry class.")
        annotation_metadata = deepcopy(annotation.get("metadata", {}))
        # Preserve fields added by automation, review, or future schema versions.
        annotation_metadata["workspace_fields"] = {key: deepcopy(value) for key, value in annotation.items()
                                                    if key not in {"id", "class_id", "parent_id", "segmentation", "bbox", "confidence", "status", "source", "metadata"}}
        annotation_metadata["workspace_source"] = annotation.get("source")
        annotation_metadata["workspace_status"] = annotation.get("status")
        annotation_metadata["class_registry"] = deepcopy(category)
        annotation_id = str(annotation["id"])
        parent_id = annotation.get("parent_id")
        fish_id = str(parent_id) if parent_id is not None else annotation_id if category.get("kind") == "whole_fish" else None
        bbox = deepcopy(annotation.get("bbox"))
        segmentation = deepcopy(annotation.get("segmentation"))
        mapped.append({"annotation_id": annotation_id, "object_id": annotation_id, "fish_id": fish_id,
                       "class_id": annotation["class_id"], "class_name": category["name"],
                       "bbox": bbox, "segmentation": segmentation, "confidence": annotation.get("confidence"),
                       "status": "approved" if annotation.get("status") == "approved" or native_status == "approved" and annotation.get("status") == "manual_verified" else "rejected" if annotation.get("status") == "rejected" else "edited" if annotation.get("status") == "corrected" else status,
                       "review_status": "approved" if annotation.get("status") == "approved" or native_status == "approved" and annotation.get("status") == "manual_verified" else "rejected" if annotation.get("status") == "rejected" else "needs_review",
                       "source": _source(annotation), "created_at": annotation.get("created_at", result["created_at"]),
                       "updated_at": annotation.get("updated_at", result["updated_at"]), "metadata": annotation_metadata})
    result.update(annotation_count=len(mapped), fish_count=len({ann["fish_id"] for ann in mapped if ann["fish_id"] is not None}),
                  part_count=sum(class_map[ann["class_id"]].get("kind") in {"part", "anatomy"} or ann["class_name"].lower().rsplit("_", 1)[-1] in {"head", "body", "tail"} for ann in mapped),
                  has_masks=any(ann["segmentation"] is not None for ann in mapped))
    if not summary:
        metadata["workspace_fields"] = {key: deepcopy(value) for key, value in document.items()
                                        if key not in {"id", "filename", "file_name", "width", "height", "annotations", "metadata"}}
        result.update(annotations=mapped, categories=deepcopy(classes), metadata=metadata)
    return result


def json_export(documents: list[dict], classes: list[dict], scope: str) -> dict:
    """Return validated JSON built exclusively from complete saved documents."""
    if not documents:
        raise ValueError("No saved annotations match this export selection.")
    images = []
    for document in documents:
        image = normalize_document(document, classes)
        if not image["annotations"]:
            raise ValueError(f"{image['file_name']} has no saved annotations to export.")
        for annotation in image["annotations"]:
            if annotation["bbox"] is None and annotation["segmentation"] in (None, []):
                raise ValueError(f"Annotation {annotation['annotation_id']} has no saved geometry.")
            for name in ("width", "height"):
                if not isinstance(image[name], int) or image[name] <= 0:
                    raise ValueError("Saved image dimensions are invalid.")
        images.append(image)
    result = {"dataset": {"name": "Dried Fish Annotation Dataset", "format_version": "1.0",
                          "export_date": datetime.now(timezone.utc).isoformat(), "scope": scope,
                          "image_count": len(images), "annotation_count": sum(len(image["annotations"]) for image in images),
                          "coordinate_system": "original_image_pixels", "bbox_format": "xywh",
                          "segmentation_format": "COCO polygons or RLE; null means bounding-box-only",
                          "class_id_namespace": "shared annotation class registry; source category/model IDs are preserved in metadata"},
              "images": images}
    return json.loads(_json(result))


def _read_document(store: AnnotationStore, image_id: str, version: int | None = None,
                   baseline_cache: dict | None = None) -> dict:
    if version is None:
        document = store.get(image_id)
    else:
        with store.connection() as connection:
            row = connection.execute("SELECT document FROM revisions WHERE image_id=? AND revision=?", (image_id, version)).fetchone()
        if row is None:
            raise NotFound("Saved annotation version not found.")
        document = json.loads(row[0])
    # Full original image metadata is in the immutable COCO baseline, not in
    # the editable registry document. Include it without modifying the source.
    baseline = document.get("baseline")
    if baseline:
        baseline_path = store.root / baseline["path"]
        cache = {} if baseline_cache is None else baseline_cache
        if baseline_path not in cache:
            store._verify_artifact(baseline_path)
            data = json.loads(baseline_path.read_bytes())
            cache[baseline_path] = (data, {image["id"]: image for image in data["images"]})
        data, image_index = cache[baseline_path]
        original_image = image_index.get(baseline["source_image_id"])
        metadata = document.setdefault("metadata", {})
        metadata.setdefault("source_record", deepcopy(original_image))
        metadata.setdefault("source_dataset_metadata", {key: deepcopy(value) for key, value in data.items() if key not in {"images", "annotations"}})
        metadata.setdefault("dataset_id", _dataset_identity(document))
    return document


def _listing_status(row: dict) -> tuple[str, str]:
    metadata = row.get("metadata", {})
    if row["status"] == "approved":
        return "approved", "approved"
    if row["status"] == "rejected":
        return "rejected", "rejected"
    if metadata.get("library_review_revision") == row["revision"]:
        status = metadata.get("library_status")
        review = metadata.get("library_review_status")
        if status in LIBRARY_STATUSES - {"approved"} and review in REVIEW_STATUSES - {"approved"}:
            return status, review
    if not row.get("annotation_count"):
        return "not_annotated", "pending"
    return ("edited" if row["status"] == "corrected" else "ai_annotated" if row.get("automation") else "needs_review"), "needs_review"


def _native_annotations(values: object, current: dict, classes: list[dict]) -> list[dict]:
    if not isinstance(values, list):
        raise AnnotationError("Annotations must be a list.")
    previous = {annotation["id"]: annotation for annotation in current["annotations"]}
    categories = {category["id"]: category for category in classes}
    result, seen = [], set()
    timestamp = datetime.now(timezone.utc).isoformat()
    for value in values:
        if not isinstance(value, dict):
            raise AnnotationError("Every annotation must be an object.")
        annotation_id = value.get("annotation_id")
        if not isinstance(annotation_id, str) or not annotation_id or annotation_id in seen:
            raise AnnotationError("Annotation IDs must be unique nonempty strings.")
        seen.add(annotation_id)
        category = categories.get(value.get("class_id"))
        if category is None or value.get("class_name", category["name"]) != category["name"]:
            raise AnnotationError("Class ID and name must match the shared class registry.")
        old = previous.get(annotation_id)
        annotation = deepcopy(old) if old else {"id": annotation_id, "source": "user", "status": "corrected", "flags": [], "created_at": timestamp}
        fish_id = value.get("fish_id")
        parent_id = None if category["kind"] == "whole_fish" else fish_id
        annotation.update(class_id=value["class_id"], parent_id=parent_id,
                          bbox=deepcopy(value.get("bbox")), segmentation=deepcopy(value.get("segmentation")),
                          confidence=value.get("confidence"))
        changed = old is None or any(old.get(key) != annotation.get(key) for key in ("class_id", "parent_id", "bbox", "segmentation", "confidence"))
        if value.get("status") == "rejected":
            annotation["status"] = "rejected"
        elif value.get("status") == "approved" and not changed:
            annotation["status"] = "approved"
        elif changed:
            annotation["status"] = "corrected"
        if changed or old is None or annotation["status"] != old.get("status"):
            annotation["updated_at"] = timestamp
        result.append(annotation)
    return result


def _guard(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except AnnotationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise HTTPException(status_code=503, detail="Annotation storage operation failed. Your previous saved version remains available. Retry the operation.") from error
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return guarded


def create_library_router(store: AnnotationStore | None = None) -> APIRouter:
    """Mount management views on the same store as automation and human review."""
    if store is None:
        # A shared singleton is supplied by the canonical store when available.
        from src.annotation.store import get_annotation_store
        store = get_annotation_store()
    router = APIRouter(prefix="/api/annotation-library", tags=["annotation-library"])
    no_store = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

    def classes() -> list[dict]:
        return store.classes()["classes"]

    @router.get("/datasets")
    @_guard
    def datasets():
        return JSONResponse(_dataset_catalog(store, store.list()["images"]), headers=no_store)

    @router.get("/summary")
    @_guard
    def summary(dataset_id: str | None = None):
        rows = store.list()["images"]
        catalog = _dataset_catalog(store, rows)
        selected_dataset = _dataset_filter(dataset_id, catalog)
        rows = [row for row in rows if selected_dataset is None or _dataset_identity(row) == selected_dataset]
        statuses = [_listing_status(row) for row in rows]
        visible_datasets = [dataset for dataset in catalog["datasets"] if selected_dataset is None or dataset["id"] == selected_dataset]
        return JSONResponse({"total_images": len(rows), "completed_annotations": sum(row["annotation_count"] > 0 for row in rows),
            "pending_annotations": sum(row["annotation_count"] == 0 and status[0] != "rejected" for row, status in zip(rows, statuses)),
            "approved_annotations": sum(status[0] == "approved" for status in statuses),
            "needs_correction": sum(status[1] == "needs_correction" for status in statuses),
            "needs_review": sum(status[1] == "needs_review" for status in statuses),
            "rejected_images": sum(status[0] == "rejected" for status in statuses), "saved_datasets": len(visible_datasets),
            "total_annotated_objects": sum(row["annotation_count"] for row in rows),
            "datasets": visible_datasets, "dataset_id": selected_dataset, "primary_dataset_id": catalog.get("primary_dataset_id"),
            "storage_path": str(store.root / "annotations.sqlite3"), "originals_path": str(store.root / "images")}, headers=no_store)

    @router.get("/images")
    @_guard
    def images(page: int = 1, page_size: int = 24, search: str = "", status: str = "", sort: str = "date_desc", completed: bool = False, dataset_id: str | None = None):
        if page < 1 or not 1 <= page_size <= 100:
            raise AnnotationError("Page must be positive and page_size must be between 1 and 100.")
        if status and status not in LIBRARY_STATUSES | {"saved", "needs_correction"}:
            raise AnnotationError("Unknown annotation status filter.")
        rows = store.list()["images"]
        selected_dataset = _dataset_filter(dataset_id, _dataset_catalog(store, rows))
        selected = []
        for row in rows:
            if selected_dataset is not None and _dataset_identity(row) != selected_dataset:
                continue
            row_status, review_status = _listing_status(row)
            if search.casefold() not in row["filename"].casefold() or completed and not row["annotation_count"]:
                continue
            if status == "needs_correction" and review_status != "needs_correction" or status not in {"", "saved", "needs_correction"} and row_status != status:
                continue
            selected.append(row)
        sort = {"updated_desc": "date_desc", "updated_asc": "date_asc", "filename_asc": "filename"}.get(sort, sort)
        if sort in {"date", "date_desc", "date_asc"}:
            key, reverse = lambda row: (row.get("updated_at", row.get("created_at", "")), row["id"]), sort != "date_asc"
        elif sort in {"filename", "filename_desc"}:
            key, reverse = lambda row: (row["filename"].casefold(), row["id"]), sort == "filename_desc"
        elif sort == "status":
            key, reverse = lambda row: (_listing_status(row)[0], row["filename"].casefold(), row["id"]), False
        else:
            raise AnnotationError("Unknown gallery sort order.")
        selected.sort(key=key, reverse=reverse)
        categories = classes()
        visible = selected[(page - 1) * page_size:page * page_size]
        # Only this page's annotations are read for object/part counts. Neither
        # full-resolution image bytes nor masks are sent in gallery responses.
        items = [normalize_document(store.get(row["id"]), categories, summary=True) for row in visible]
        return JSONResponse({"images": items, "total": len(selected), "page": page, "page_size": page_size,
                             "pages": math.ceil(len(selected) / page_size), "dataset_id": selected_dataset}, headers=no_store)

    @router.get("/images/{image_id}")
    @_guard
    def detail(image_id: str, version: int | None = None):
        return JSONResponse(normalize_document(_read_document(store, image_id, version), classes()), headers=no_store)

    @router.put("/images/{image_id}")
    @_guard
    def save(image_id: str, payload: dict):
        current = store.get(image_id)
        version = payload.get("base_version")
        if isinstance(version, bool) or version != current["revision"]:
            raise RevisionConflict("A newer annotation version is saved. Your draft was retained; load the latest saved version before retrying.")
        status, review_status = payload.get("status", "edited"), payload.get("review_status", "needs_review")
        if status not in LIBRARY_STATUSES or review_status not in REVIEW_STATUSES:
            raise AnnotationError("Unknown image or review status.")
        if status == "approved" or review_status == "approved":
            raise AnnotationError("Use Approve after reviewing this image; ordinary saves do not grant approval.")
        values = payload.get("annotations")
        if values is None:
            values = normalize_document(current, classes())["annotations"]
        annotations = _native_annotations(values, current, classes())
        if status == "not_annotated" and annotations:
            raise AnnotationError("An image with annotations cannot be marked Not Annotated.")
        metadata = {**deepcopy(current.get("metadata", {})), "library_status": status,
                    "library_review_status": review_status, "library_review_revision": current["revision"] + 1}
        native_status = "rejected" if status == "rejected" else "unreviewed" if current["status"] == "approved" else None
        saved = store.save(image_id, version, annotations, status=native_status, metadata=metadata)
        return JSONResponse(normalize_document(_read_document(store, saved["id"]), classes()), headers=no_store)

    @router.get("/images/{image_id}/history")
    @_guard
    def history(image_id: str):
        revisions = store.history(image_id)["revisions"]
        return JSONResponse({"image_id": image_id, "versions": [{"version": item["revision"], "created_at": item["created_at"],
                             "status": "approved" if item["status"] == "approved" else "edited" if item["status"] == "corrected" else "rejected" if item["status"] == "rejected" else "needs_review"} for item in revisions]}, headers=no_store)

    @router.get("/images/{image_id}/media")
    @_guard
    def media(image_id: str, thumbnail: bool = False, original: bool = False):
        document = store.get(image_id)
        path = store.pixels_path(image_id)
        if original:
            path = store.root / document["original_path"]
            store._verify_artifact(path)
        if not thumbnail:
            return FileResponse(path, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((400, 300))
            output = BytesIO()
            image.save(output, format="JPEG", quality=80)
        return Response(output.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

    @router.post("/scan")
    @_guard
    def scan(payload: dict | None = None):
        catalog = _dataset_catalog(store, store.list()["images"])
        selected = _dataset_filter((payload or {}).get("dataset_id", catalog.get("primary_dataset_id")), catalog,
                                   optional="dataset_id" not in (payload or {}))
        dataset = next((item for item in catalog["datasets"] if item["id"] == selected), None)
        if dataset and dataset.get("source_type") == "coco_zip":
            # Only a previously registered source may be resumed. A caller can
            # select its dataset, but cannot provide a filesystem import path.
            if not dataset.get("source_path"):
                raise AnnotationError("This dataset has no registered source archive. Its saved annotations remain available.")
            result = store.import_primary_zip(dataset["source_path"], dataset_id=selected, name=dataset["name"])
        elif selected in (None, "v2-coco-v7"):
            result = store.import_manual()
        else:
            raise AnnotationError("This dataset has no discoverable annotation source. Add images with Upload images instead.")
        return JSONResponse({"imported": result["imported"], "existing": result["skipped"], "errors": result["errors"],
                             "dataset_id": selected,
                             "message": "Manual source annotations are indexed. Saved edits and source files are preserved."}, headers=no_store)

    @router.post("/upload")
    async def upload(request: Request):
        try:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 40 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Image exceeds the 40 MiB upload limit.")
                chunks.append(chunk)
            filename = unquote(request.headers.get("x-filename", ""))
            if not filename:
                raise HTTPException(status_code=400, detail="An X-Filename image header is required.")
            requested_dataset = request.headers.get("x-dataset-id")
            if requested_dataset is not None:
                selected_dataset = _dataset_filter(requested_dataset, _dataset_catalog(store, store.list()["images"]), optional=False)
                document = store.upload(b"".join(chunks), filename, dataset_id=selected_dataset)
            else:
                document = store.upload(b"".join(chunks), filename)
            return JSONResponse(normalize_document(document, classes()), headers=no_store)
        except AnnotationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise HTTPException(status_code=503, detail="The original image could not be saved. Retry the upload.") from error

    @router.post("/approve")
    @_guard
    def approve(payload: dict):
        selections = payload.get("images")
        if not isinstance(selections, list) or not selections or len(selections) > 1000 or any(not isinstance(item, dict) for item in selections):
            raise AnnotationError("Select between 1 and 1000 reviewed images to approve.")
        ids = [item.get("image_id") for item in selections]
        if any(not isinstance(image_id, str) for image_id in ids) or len(set(ids)) != len(ids):
            raise AnnotationError("Approval selection requires unique image IDs.")
        # One outer canonical transaction prevents a partial bulk approval. The
        # store's per-image public approve method owns validation and revisioning.
        results, categories = [], classes()
        with store.connection(write=True) as connection:
            documents = []
            for selection in selections:
                current = store._get(connection, selection["image_id"])
                store._check_revision(current, selection.get("base_version"))
                normalized = normalize_document(current, categories)
                if normalized["review_status"] not in {"reviewed", "approved"}:
                    raise AnnotationError(f"Review {current['filename']} before approving it.")
                report = store._validate_document(current)
                if report["errors"]:
                    raise AnnotationError("Cannot approve: " + "; ".join(item["message"] for item in report["errors"][:6]))
                if not any(annotation.get("status") != "rejected" for annotation in current["annotations"]):
                    raise AnnotationError("An image without non-rejected annotations cannot be approved as annotated.")
                documents.append(current)
            for document in documents:
                if document["status"] != "approved":
                    for annotation in document["annotations"]:
                        if annotation["status"] not in {"rejected", "manual_verified"}:
                            annotation["status"] = "approved"
                    document["status"] = "approved"
                    document["revision"] += 1
                    document = store._persist(connection, document)
                results.append(normalize_document(document, categories, summary=True))
        return JSONResponse({"approved": len(results), "images": results}, headers=no_store)

    @router.post("/export")
    @_guard
    def export(payload: dict):
        scope = payload.get("scope", "all")
        if scope not in {"current", "selected", "all", "approved"}:
            raise AnnotationError("Choose current, selected, all or approved annotations.")
        image_ids = payload.get("image_ids", [])
        package = payload.get("package", False)
        if not isinstance(package, bool):
            raise AnnotationError("The package option must be true or false.")
        catalog = _dataset_catalog(store, store.list()["images"])
        selected_dataset = _dataset_filter(payload.get("dataset_id"), catalog, optional="dataset_id" not in payload)
        with store.connection() as connection:
            connection.execute("BEGIN")
            export_classes = [json.loads(row[0]) for row in connection.execute("SELECT document FROM classes ORDER BY id")]
            if scope in {"current", "selected"}:
                if not isinstance(image_ids, list) or not image_ids or any(not isinstance(image_id, str) for image_id in image_ids) or len(set(image_ids)) != len(image_ids):
                    raise AnnotationError("Choose unique saved image IDs to export.")
                if scope == "current" and len(image_ids) != 1:
                    raise AnnotationError("A current-image export requires exactly one image.")
                documents = [store._get(connection, image_id) for image_id in image_ids]
                if selected_dataset is not None:
                    outside = [document for document in documents if _dataset_identity(document) != selected_dataset]
                    if outside:
                        raise AnnotationError(f"Selected image {outside[0]['filename']} belongs to another dataset. Choose images from {selected_dataset}, or explicitly select all saved datasets.")
            else:
                documents = [json.loads(row[0]) for row in connection.execute("SELECT document FROM images ORDER BY id")]
                documents = [document for document in documents if document["annotations"] and (scope != "approved" or document["status"] == "approved")
                             and (selected_dataset is None or _dataset_identity(document) == selected_dataset)]
        # Add original source metadata from the immutable baseline to each
        # selected saved snapshot. Never accept frontend annotation values here.
        complete, baseline_cache = [], {}
        excluded_annotations, excluded_images = 0, 0
        for document in documents:
            augmented = _read_document(store, document["id"], document["revision"], baseline_cache)
            if scope == "approved":
                retained = [annotation for annotation in augmented["annotations"] if annotation.get("status") != "rejected"]
                excluded_annotations += len(augmented["annotations"]) - len(retained)
                augmented["annotations"] = retained
                if not retained:
                    excluded_images += 1
                    continue
            complete.append(augmented)
        exported = json_export(complete, export_classes, scope)
        if scope == "approved":
            exported["dataset"].update(excluded_annotation_count=excluded_annotations,
                excluded_image_count=excluded_images,
                review_filter="Review-rejected objects are excluded. Class names such as Rejected_Body remain valid classes. All saved annotations exports retain rejected objects and their metadata.")
        exported["dataset"]["dataset_id"] = selected_dataset
        included_datasets = {image["dataset_id"] for image in exported["images"]}
        exported["dataset"]["source_datasets"] = [dataset for dataset in catalog["datasets"] if dataset["id"] in included_datasets]
        if selected_dataset is not None:
            exported["dataset"]["name"] = next(dataset.get("name", selected_dataset) for dataset in catalog["datasets"] if dataset["id"] == selected_dataset)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"fish-annotations-{scope}-{stamp}"
        if not package:
            return Response(_json(exported).encode("utf-8"), media_type="application/json",
                            headers={**no_store, "Content-Disposition": f'attachment; filename="{filename}.json"'})
        # Build on disk before returning a download, so any missing image/mask
        # aborts the whole operation and no incomplete dataset is advertised.
        descriptor, temporary_name = tempfile.mkstemp(prefix="fish-library-", suffix=".zip")
        import os
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
                for image, document in zip(exported["images"], complete):
                    original = store.root / document["original_path"]
                    store._verify_artifact(original)
                    pixels = store.pixels_path(document["id"])
                    image_member = f"images/{image['image_id']}/pixels.png"
                    archive.write(pixels, image_member)
                    original_member = f"originals/{image['image_id']}/{Path(image['file_name']).name}"
                    archive.write(original, original_member)
                    image.update(image_path=image_member, original_image_path=original_member)
                    for native in document["annotations"]:
                        if native.get("mask_path"):
                            mask = store.root / native["mask_path"]
                            store._verify_artifact(mask)
                            archive.write(mask, f"masks/{image['image_id']}/{Path(native['mask_path']).name}")
                archive.writestr("annotations/dataset.json", _json(exported).encode("utf-8"))
                archive.writestr("README.txt", "Saved annotation library export. annotations/dataset.json uses original-image pixel coordinates, xywh boxes, and COCO polygon/RLE masks. images/ contains canonical unrotated pixels used by the annotations. originals/ preserves original uploads. null fish_id means that association remains unassigned. Source IDs and source metadata are retained; imported annotations are not automatically approved.\n")
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip():
                    raise AnnotationError("Dataset package integrity validation failed.")
            return FileResponse(temporary, media_type="application/zip", filename=filename + ".zip", headers=no_store,
                                background=BackgroundTask(temporary.unlink, missing_ok=True))
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return router


router = create_library_router()
