"""Disposable real-store fixture server for opt-in browser acceptance.

Run ``python -B tests/annotation_library_fixture_server.py`` from the project.
Only synthetic files under ../tmp/annotation-browser-fixture are created. The
application's default dataset and the service on port 8000 are never accessed.
"""
from pathlib import Path
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from src.annotation.store import AnnotationStore
from src.api.annotation_library import create_library_router
from src.api.annotation_workspace import create_annotation_router

ROOT = PROJECT.parent / "tmp" / "annotation-browser-fixture"
SOURCE = ROOT / "manual"
split = SOURCE / "train"
split.mkdir(parents=True, exist_ok=True)
categories = [
    {"id": 1, "name": "A_Head", "supercategory": "anatomy"},
    {"id": 2, "name": "A_Body", "supercategory": "anatomy"},
    {"id": 3, "name": "A_Tail", "supercategory": "anatomy"},
]
images, annotations = [], []
for index in range(1, 4):
    name = f"review_{index:03d}.png"
    image = Image.new("RGB", (640, 360), (235, 239, 232 + index))
    draw = ImageDraw.Draw(image)
    draw.polygon([(70, 100), (120, 65), (260, 80), (300, 110), (270, 135), (115, 145)], fill=(90, 120, 105))
    draw.polygon([(330, 245), (380, 210), (520, 225), (570, 250), (510, 280), (375, 285)], fill=(110, 125, 115))
    image.save(split / name)
    images.append({"id": index, "file_name": name, "width": 640, "height": 360,
                   "extra": {"capture_note": "synthetic browser QA"}})
    annotations.append({"id": index, "image_id": index, "category_id": 1,
                        "bbox": [70, 65, 65, 80], "segmentation": [[70, 100, 120, 65, 135, 95, 115, 145]],
                        "iscrowd": 0, "custom_metadata": "must survive export"})
(split / "_annotations.coco.json").write_text(json.dumps({
    "images": images, "annotations": annotations, "categories": categories,
}), encoding="utf-8")
store = AnnotationStore(ROOT / "workspace", SOURCE)
report = store.import_manual(["train"])
first = sorted(store.list()["images"], key=lambda document: document["filename"])[0]
if first["revision"] == 1:
    document = store.get(first["id"])
    fish_class = next(category["id"] for category in store.classes()["classes"] if category["kind"] == "whole_fish")
    objects = []
    for fish_id, polygon in [
        ("fish-1", [70, 100, 120, 65, 260, 80, 300, 110, 270, 135, 115, 145]),
        ("fish-2", [330, 245, 380, 210, 520, 225, 570, 250, 510, 280, 375, 285]),
    ]:
        objects.append({"id": fish_id, "class_id": fish_class, "parent_id": None,
                        "segmentation": [polygon], "bbox": [1, 1, 1, 1], "confidence": .95})
    objects += [
        {"id": "head-1", "class_id": 1, "parent_id": "fish-1",
         "segmentation": [[70, 100, 120, 65, 135, 95, 115, 145]], "bbox": [1, 1, 1, 1], "confidence": .9},
        {"id": "head-2", "class_id": 1, "parent_id": "fish-2",
         "segmentation": [[330, 245, 380, 210, 395, 240, 375, 285]], "bbox": [1, 1, 1, 1], "confidence": .91},
    ]
    store.save(document["id"], document["revision"], objects, metadata={"test_fixture": True})


def automate(document, frame, classes):
    """An explicit synthetic callback; this fixture does not load model weights."""
    return {"annotations": [{"id": "test-ai", "class_id": 1, "parent_id": None,
                              "segmentation": [[20, 20, 50, 25, 35, 55]], "bbox": [20, 20, 30, 35],
                              "confidence": .8}], "automation": {"test_fixture": True}}


app = FastAPI()
app.mount("/assets", StaticFiles(directory=PROJECT / "frontend"), name="assets")
app.include_router(create_library_router(store))
app.include_router(create_annotation_router(store, automate))


@app.get("/api/auth/mode")
def mode():
    return {"lan_security": False}


@app.get("/annotations")
def page():
    return FileResponse(PROJECT / "frontend" / "annotations.html")


@app.get("/api/qa/documents")
def documents():
    return [store.get(document["id"]) for document in store.list()["images"]]


if __name__ == "__main__":
    print(json.dumps({"fixture_root": str(ROOT), "manual_import": report}), flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
