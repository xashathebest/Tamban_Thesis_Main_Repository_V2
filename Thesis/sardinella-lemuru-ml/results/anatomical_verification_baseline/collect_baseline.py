"""Bounded actual-checkpoint audit; no anatomy ground truth is inferred."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2
import torch
import ultralytics

from src.evaluation.evaluate_association_repairs import evaluate_scene
from src.inference import association
from src.inference.model_registry import ModelRegistry
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    torch.set_num_threads(1)
    registry = ModelRegistry(ROOT)
    m1path = registry.resolve_checkpoint_path("fish_parent_detector")
    m2path = registry.resolve_checkpoint_path("yolo26m_partdet")
    hashes = {"model1": sha(m1path), "model2": sha(m2path)}
    fixture = json.loads((ROOT / "tests/fixtures/association_repair_real_cases.json").read_text())
    names = [Path(record["source"]["path"]).name for record in fixture["records"]]
    test = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test"
    names += [path.name for path in sorted(test.glob("*.jpg")) if path.name not in names][:max(0, 4 - len(names))]
    names = names[:4]
    model1 = YoloFishDetector(m1path, confidence_threshold=.5, device="cpu", image_size=768)
    model2 = YoloQualityModel(m2path, model_id="yolo26m_partdet", confidence_threshold=.25,
                             device="cpu", image_size=768, quality_inference_mode="full_frame")
    assert model1.load(), model1.error
    assert model2.load(), model2.error
    records = []
    for name in names:
        path = test / name
        image = cv2.imread(str(path))
        assert image is not None, path
        start = perf_counter()
        parents = model1.detect(image)
        model1_ms = (perf_counter() - start) * 1000
        start = perf_counter()
        parts, raw = model2._infer_parts(image)
        model2_ms = (perf_counter() - start) * 1000
        scene = {"scenario": name, "cohort": "bounded_actual_model_baseline",
                 "source": {"path": str(path), "sha256": sha(path), "shape": list(image.shape)},
                 "detections": [{"id": i, "bbox": list(parent.bbox), "confidence": parent.confidence}
                                for i, parent in enumerate(parents, start=1)],
                 "parts": [part.to_dict() for part in parts], "raw_parts": [part.to_dict() for part in raw]}
        replay = evaluate_scene(scene, association, repeats=1)
        missing = []
        for parent in scene["detections"]:
            owned = [r for r in replay["decisions"] if r["status"] == "ASSIGNED" and r["track_id"] == parent["id"]]
            status = {}
            for region in ("Head", "Body"):
                detected = next((r for r in owned if r["part"]["region"] == region), None)
                candidates = []
                for decision in replay["decisions"]:
                    if decision["part"]["region"] != region:
                        continue
                    score = next((c for c in decision["candidates"] if c["track_id"] == parent["id"]), None)
                    if score:
                        candidates.append({"part": decision["part"], "status": decision["status"],
                                           "owner": decision["track_id"], "reason": decision["reason"], **score})
                candidates.sort(key=lambda r: -r["score"])
                status[region] = {"accepted": detected is not None,
                                  "accepted_confidence": detected["part"]["confidence"] if detected else None,
                                  "best_global_same_region_candidate": candidates[0] if candidates else None,
                                  "physical_presence": "NOT_GROUND_TRUTHED"}
            missing.append({"parent_id": parent["id"], "required_regions": status})
        record = {**scene, "model1_ms": model1_ms, "model2_ms": model2_ms,
                  "association": replay, "required_part_diagnostics": missing}
        records.append(record)
        print(name, "parents", len(parents), "parts", dict(Counter(p.region for p in parts)),
              "assigned", replay["assigned_counts"], "ungraded", replay["ungraded_count"], flush=True)
    assert hashes == {"model1": sha(m1path), "model2": sha(m2path)}
    report = {"scope": "actual CPU checkpoint outputs and unchanged association gates on four project development photos",
              "generated_utc": datetime.now(UTC).isoformat(), "model_sha256": hashes,
              "protected_model_bytes_unchanged": True, "device": "cpu", "precision": "FP32", "threads": 1,
              "python": sys.version, "torch": torch.__version__, "ultralytics": ultralytics.__version__,
              "cuda_initialized": torch.cuda.is_initialized(),
              "config_sha256": sha(ROOT / "configs/grading_engine.yaml"),
              "anatomy_ownership_accuracy": None, "physical_absence_accuracy": None,
              "limitations": ["COCO supplies grade-part boxes without fish identity or physical-absence labels.",
                              "Images have known historical training exposure and are development compatibility evidence.",
                              "Missing association or detector output does not establish missing tissue.",
                              "Single-pass timings include first-use effects and are not a repeated performance benchmark.",
                              "No secondary anatomy verifier or mask inference is evaluated by this baseline."],
              "records": records}
    output = Path(__file__).with_name("baseline.json")
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print("Report:", output, flush=True)


if __name__ == "__main__":
    main()
