"""Local annotation API, mounted alongside the existing inspection routes."""
from __future__ import annotations

import asyncio
import sqlite3
from functools import wraps
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.annotation.store import AnnotationError, AnnotationStore, get_annotation_store

_automation = None


def set_automation(callback):
    global _automation
    _automation = callback


def _guard(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except AnnotationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise HTTPException(503, "Annotation storage operation failed. The previous saved revision remains available; retry after checking local disk access.") from error
    return guarded


def create_annotation_router(store: AnnotationStore | None = None, automation=None):
    router = APIRouter(prefix="/api/annotations", tags=["Annotation workspace"])

    def workspace():
        return store if store is not None else get_annotation_store()

    @router.get("/datasets")
    @_guard
    def datasets():
        return workspace().datasets()

    @router.get("/classes")
    @_guard
    def classes():
        return workspace().classes()

    @router.post("/classes")
    @_guard
    def add_class(body: dict):
        return workspace().add_class(body)

    @router.patch("/classes/{class_id}")
    @_guard
    def update_class(class_id: int, body: dict):
        return workspace().update_class(class_id, body)

    @router.delete("/classes/{class_id}")
    @_guard
    def delete_class(class_id: int):
        return workspace().delete_class(class_id)

    @router.get("/images")
    @_guard
    def images():
        return workspace().list()

    @router.post("/images")
    async def upload(request: Request):
        filename = request.headers.get("x-filename", "image.png")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 40 * 1024 * 1024:
                raise HTTPException(413, "Image exceeds the 40 MiB limit.")
        try:
            return await asyncio.to_thread(workspace().upload, bytes(body), filename,
                                           dataset_id=request.headers.get("x-dataset-id") or None)
        except AnnotationError as error:
            raise HTTPException(error.status_code, str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise HTTPException(503, "Image could not be saved. Check local disk access and retry.") from error

    @router.post("/import-manual")
    @_guard
    def import_manual(body: dict | None = None):
        return workspace().import_manual((body or {}).get("splits"))

    @router.get("/images/{image_id}")
    @_guard
    def image(image_id: str):
        return workspace().get(image_id)

    @router.get("/images/{image_id}/pixels")
    @_guard
    def pixels(image_id: str):
        return FileResponse(workspace().pixels_path(image_id), media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.put("/images/{image_id}")
    @_guard
    def save(image_id: str, body: dict):
        return workspace().save(image_id, body.get("expected_revision"), body.get("annotations"), body.get("status"), body.get("metadata"))

    @router.post("/images/{image_id}/approve")
    @_guard
    def approve(image_id: str, body: dict):
        return workspace().approve(image_id, body.get("expected_revision"))

    @router.post("/images/{image_id}/auto")
    @_guard
    def auto(image_id: str, body: dict):
        try:
            return workspace().auto(image_id, body.get("expected_revision"), automation or _automation)
        except (RuntimeError, ImportError) as error:
            raise HTTPException(503, f"Local automation is unavailable: {error}") from error

    @router.get("/images/{image_id}/history")
    @_guard
    def history(image_id: str):
        return workspace().history(image_id)

    @router.get("/images/{image_id}/history/{revision}")
    @_guard
    def revision(image_id: str, revision: int):
        return workspace().get_revision(image_id, revision)

    @router.post("/images/{image_id}/restore")
    @_guard
    def restore(image_id: str, body: dict):
        return workspace().restore(image_id, body.get("expected_revision"), body.get("revision"))

    @router.post("/validate")
    @_guard
    def validate(body: dict | None = None):
        return workspace().validate((body or {}).get("image_ids"))

    @router.post("/export")
    @_guard
    def export(body: dict):
        path = workspace().export(body.get("format", "coco"), body.get("image_ids"), body.get("split", False))
        return FileResponse(path, media_type="application/zip", filename=path.name)

    return router


router = create_annotation_router()
