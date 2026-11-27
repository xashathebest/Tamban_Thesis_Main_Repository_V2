"""Explicit read-only source hashes and optional official COCO pixel parity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "results/qa/annotation_workflow"

from src.annotation.masks import coco_segmentation_to_mask
import numpy as np


def main():
    from pycocotools import mask as official
    snapshot = json.loads((OUTPUT / "source_integrity_before.json").read_text())
    changed = []
    for entry in snapshot["files"]:
        path = ROOT / entry["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            changed.append(entry["path"])
    started = perf_counter()
    mismatches, checked, by_split = [], 0, {}
    for split in ("train", "valid", "test"):
        data = json.loads((ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation" / split / "_annotations.coco.json").read_bytes())
        images = {im["id"]: im for im in data["images"]}
        for annotation in data["annotations"]:
            image = images[annotation["image_id"]]
            height, width = image["height"], image["width"]
            segmentation = annotation["segmentation"]
            expected = official.decode(official.merge(official.frPyObjects(segmentation, height, width))) if isinstance(segmentation, list) else official.decode(segmentation)
            actual = coco_segmentation_to_mask(segmentation, height, width)
            if not np.array_equal(expected != 0, actual != 0):
                mismatches.append({"split": split, "annotation_id": annotation["id"]})
            checked += 1
        by_split[split] = len(data["annotations"])
    result = {"source_files_checked": len(snapshot["files"]), "changed_or_missing": changed,
              "masks_checked": checked, "masks_by_split": by_split, "pixel_mismatches": mismatches,
              "official_reference": "already-installed pycocotools (QA only, not a runtime dependency)",
              "elapsed_mask_seconds": round(perf_counter() - started, 3), "passed": not changed and not mismatches}
    (OUTPUT / "final_source_integrity_and_mask_parity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["passed"]


if __name__ == "__main__":
    main()
