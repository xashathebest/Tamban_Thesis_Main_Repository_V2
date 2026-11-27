"""Explicit CPU training smoke with real manual labels in an isolated workspace.

This is a functional check at a deliberately tiny resolution, not an accuracy
benchmark. It never changes the deployed workspace, source dataset or weights.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.annotation.store import AnnotationStore as CanonicalStore
from src.annotation_learning import LearningService, UltralyticsAnnotationTrainer
from src.api.annotation_store import AnnotationStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models/yolo_parts/yolo26n_seg_exp4/weights/exp-4.pt")
    parser.add_argument("--epochs", type=int, default=1)
    args = parser.parse_args()
    source = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    originals = {str(path): sha256(path.read_bytes()).hexdigest() for path in source.glob("*/_annotations.coco.json")}
    checkpoint_hash = sha256(args.checkpoint.read_bytes()).hexdigest()
    import torch
    torch.set_num_threads(2)
    # Preserve all established validation cases, but bound CPU fitting to two
    # original training images. No validation/test image supplies a gradient.
    for split, limit in (("train", 2), ("valid", None)):
        data = json.loads((source / split / "_annotations.coco.json").read_bytes())
        selected = data["images"][:limit] if limit else data["images"]
        ids = {image["id"] for image in selected}
        data["images"] = selected
        data["annotations"] = [a for a in data["annotations"] if a["image_id"] in ids]
        destination = output / "manual" / split
        destination.mkdir(parents=True)
        for image in selected:
            shutil.copy2(source / split / image["file_name"], destination / image["file_name"])
        (destination / "_annotations.coco.json").write_text(json.dumps(data), encoding="utf-8")
    canonical = CanonicalStore(output / "workspace", output / "manual")
    imported = canonical.import_manual(["train", "valid"])
    if imported["errors"]:
        raise RuntimeError(imported["errors"])
    learner = LearningService(AnnotationStore(canonical), output / "learning", base_checkpoint=args.checkpoint,
        adapter=UltralyticsAnnotationTrainer(epochs=args.epochs, image_size=64, batch=2, device="cpu"))
    original_version = learner.deployed_version()
    # A functional smoke may evaluate incomplete historical coverage, but that
    # explicit QA path is permanently ineligible for model promotion.
    result = learner.train_candidate(allow_incomplete_validation=True)
    result.update(qa_only=True, training_images=2, validation_images=len(data["images"]), image_size=64,
        original_version=original_version, deployed_version=learner.deployed_version(), original_source_hashes=originals,
        source_annotations_unchanged=all(sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in originals.items()),
        original_checkpoint_unchanged=sha256(args.checkpoint.read_bytes()).hexdigest() == checkpoint_hash)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"promoted", "rejected"} and result["source_annotations_unchanged"] and result["original_checkpoint_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
