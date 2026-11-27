"""Explicit complete primary COCO export/readback; never edits source labels."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from src.annotation.primary_baseline import dataset_id
from src.annotation.store import get_annotation_store


def main():
    cv2.setNumThreads(1)
    store = get_annotation_store()
    registry = store.datasets()
    selected = registry["primary_dataset_id"]
    profile = next(d for d in registry["datasets"] if d["id"] == selected)
    assert profile["status"] == "ready", "Finish the existing primary import first."
    documents = [d for d in store._selected(approved_only=True) if dataset_id(d) == selected]
    assert len(documents) == 345
    before = {d["id"]: d["revision"] for d in documents}
    started = time.monotonic()
    print("Exporting complete primary COCO dataset with protected splits", flush=True)
    path = store.export("coco", split=True)
    exported = time.monotonic()
    counts = Counter()
    with zipfile.ZipFile(path) as archive:
        damaged = archive.testzip()
        assert damaged is None, damaged
        manifest = json.loads(archive.read("manifest.json"))
        assert {i["id"] for i in manifest["images"]} == set(before)
        report = json.loads(archive.read("validation_report.json"))
        assert report["valid"] and not report["errors"]
        names = set(archive.namelist())
        for item in manifest["images"]:
            document = store.get(item["id"])
            assert item["revision"] == before[item["id"]]
            assert dataset_id(document) == selected
            assert item["path"] in names and item["original_path"] in names
            assert archive.read(item["path"]) == (store.root / document["pixels_path"]).read_bytes()
            assert hashlib.sha256(archive.read(item["original_path"])).hexdigest() == document["image_sha256"]
            assert json.loads(archive.read(f"reviewed_documents/{item['id']}.json")) == document
            counts[item["split"]] += 1
            originals = {a["id"]: a for a in document["annotations"] if a["status"] != "rejected"}
            assert {a["id"] for a in item["annotations"]} == set(originals)
            for annotation in item["annotations"]:
                source = originals[annotation["id"]]
                assert annotation["segmentation"] == source["segmentation"]
                assert archive.read(annotation["mask_path"]) == (store.root / source["mask_path"]).read_bytes()
        coco_count = 0
        for split in counts:
            coco = json.loads(archive.read(f"{split}/_annotations.coco.json"))
            image_ids = {i["id"] for i in coco["images"]}
            category_ids = {c["id"] for c in coco["categories"]}
            assert len(coco["images"]) == counts[split]
            for annotation in coco["annotations"]:
                assert annotation["image_id"] in image_ids and annotation["category_id"] in category_ids
                assert isinstance(annotation["segmentation"], dict) and annotation["segmentation"]["counts"]
            coco_count += len(coco["annotations"])
        assert coco_count == 4867
    assert before == {d["id"]: store.get(d["id"])["revision"] for d in documents}
    result = {
        "passed": True, "dataset_id": selected, "path": str(path), "bytes": path.stat().st_size,
        "images": len(documents), "annotations": coco_count, "split_counts": dict(counts),
        "archive_crc_valid": True, "all_image_original_and_mask_bytes_exact": True,
        "all_reviewed_documents_equal": True, "source_revisions_unchanged": True,
        "validation": report, "export_seconds": round(exported - started, 3),
        "export_and_readback_seconds": round(time.monotonic() - started, 3),
        "limitation": "Structural and byte fidelity check; not an independent model accuracy or all-class validation certificate.",
    }
    output = ROOT / "results/qa/annotation_workflow/primary_complete_export.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "validation"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
