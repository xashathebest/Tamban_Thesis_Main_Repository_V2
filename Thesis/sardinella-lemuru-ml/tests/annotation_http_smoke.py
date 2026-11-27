"""Explicit real-model ASGI HTTP/save/restart/export smoke, isolated QA data.

The approval action is a test simulation and never writes a verified label to
the user's real annotation workspace. Run from the project root explicitly.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "results/qa/annotation_workflow/real_http"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ.update(CUDA_VISIBLE_DEVICES="", FISH_DETECTOR_DEVICE="cpu", FISH_QUALITY_DEVICE="cpu",
                  MOBILESAM_DEVICE="cpu", FISH_INFERENCE_FP16="off")
workspace = Path(tempfile.mkdtemp(prefix="isolated-", dir=OUTPUT))
os.environ["FISH_ANNOTATION_ROOT"] = str(workspace)

import cv2
import numpy as np
import torch
from fastapi.testclient import TestClient
from src.annotation.masks import segmentation_to_mask
from src.annotation.store import AnnotationStore


def main():
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    app_module = importlib.import_module("src.api.app")
    assert app_module.model.load(), app_module.model.error
    assert app_module.quality_model.load(), app_module.quality_model.error
    source = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/train/WIN_20260823_20_10_07_Pro_jpg.rf.bf4c016dea7d84c6ac57bb19f0cdc76f.jpg"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    paths = [app_module.model.weights_path, app_module.quality_model.weights_path,
             ROOT / "models/yolo_parts/yolo26n_seg_exp4/weights/exp-4.pt"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    counts = {"model1_calls": 0}
    detect = app_module.model.detect

    def counted(*args, **kwargs):
        counts["model1_calls"] += 1
        return detect(*args, **kwargs)

    app_module.model.detect = counted
    client = TestClient(app_module.app)  # No lifespan, camera, or maintenance worker.
    response = client.post("/api/annotations/images", content=source.read_bytes(), headers={"X-Filename": source.name})
    assert response.status_code == 200, response.text
    original = response.json()
    image_id = original["id"]
    response = client.post(f"/api/annotations/images/{image_id}/auto", json={"expected_revision": original["revision"]})
    assert response.status_code == 200, response.text
    predicted = response.json()
    assert predicted["annotations"] and all(a["status"] == "unreviewed" for a in predicted["annotations"])
    assert counts["model1_calls"] == 1
    assert client.post(f"/api/annotations/images/{image_id}/auto", json={"expected_revision": predicted["revision"]}).status_code == 409
    part = next(a for a in predicted["annotations"] if a.get("parent_id") is not None)
    changes = deepcopy(predicted["annotations"])
    chosen = next(a for a in changes if a["id"] == part["id"])
    chosen["class_id"] = 1 if part["class_id"] != 1 else 2
    response = client.put(f"/api/annotations/images/{image_id}", json={"expected_revision": predicted["revision"], "annotations": changes})
    assert response.status_code == 200, response.text
    corrected = response.json()
    actual = next(a for a in corrected["annotations"] if a["id"] == part["id"])
    assert actual["class_id"] == chosen["class_id"] and actual["status"] == "corrected"
    assert all(a == next(b for b in corrected["annotations"] if b["id"] == a["id"]) for a in predicted["annotations"] if a["id"] != part["id"])
    assert client.put(f"/api/annotations/images/{image_id}", json={"expected_revision": predicted["revision"], "annotations": changes}).status_code == 409
    # Restore the detector's original class before simulated export QA.
    changes = deepcopy(corrected["annotations"])
    next(a for a in changes if a["id"] == part["id"])["class_id"] = part["class_id"]
    response = client.put(f"/api/annotations/images/{image_id}", json={"expected_revision": corrected["revision"], "annotations": changes})
    assert response.status_code == 200, response.text
    restored_class = response.json()
    response = client.post(f"/api/annotations/images/{image_id}/approve", json={"expected_revision": restored_class["revision"]})
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    reopened = AnnotationStore(workspace).get(image_id)
    assert reopened == approved
    response = client.post("/api/annotations/validate", json={"image_ids": [image_id]})
    assert response.status_code == 200 and response.json()["valid"], response.text
    validation = response.json()
    response = client.post("/api/annotations/export", json={"format": "coco", "image_ids": [image_id]})
    assert response.status_code == 200, response.text
    (OUTPUT / "simulated_approval_export.zip").write_bytes(response.content)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        coco = json.loads(archive.read("_annotations.coco.json"))
        assert len(coco["annotations"]) == len(approved["annotations"])
        for annotation in manifest["images"][0]["annotations"]:
            source_annotation = next(a for a in approved["annotations"] if a["id"] == annotation["id"])
            mask = segmentation_to_mask(source_annotation["segmentation"], approved["height"], approved["width"])
            saved = cv2.imdecode(np.frombuffer(archive.read(annotation["mask_path"]), np.uint8), cv2.IMREAD_GRAYSCALE)
            assert np.array_equal(mask != 0, saved != 0)
    assert counts["model1_calls"] == 1, "Class edits, approve/export/reopen must never rerun detection."
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after and not torch.cuda.is_initialized()
    report = {"passed": True, "source": str(source), "source_sha256": source_hash,
              "workspace": str(workspace), "annotation_count": len(approved["annotations"]),
              "model1_calls": counts["model1_calls"], "validation": validation, "checkpoints_unchanged": before == after,
              "cuda_initialized": torch.cuda.is_initialized(), "prediction_model_version": predicted["automation"].get("prediction_model_version"),
              "checks": ["real default-model Auto-Annotate through HTTP", "unreviewed predictions persisted", "rerun protects saved labels",
                 "single-object class edit without changing peers", "stale revision conflicts", "simulated approval",
                 "new store after restart matches saved revision", "structural validation", "COCO+PNG pixel equality", "no extra inference"],
              "limitation": "Approval simulated solely to test persistence/export; these isolated QA labels are not human-verified training truth."}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
