"""CPU feature replay on the recorded photo; no detector or GPU is executed."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    source_root, project = Path(args.source_root).resolve(), Path(args.project_root).resolve()
    sys.path.insert(0, str(source_root))
    os.environ.update(FISH_INFERENCE_FP16="off", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    import cv2
    import numpy as np
    from src.api.image_analysis import StillImageAnalyzer
    from src.inference.grading_engine import WeightedGradingEngine
    from src.inference.part_types import PartDetection
    from src.inference.yolo_fish_detector import FishDetection
    from src.inference.yolo_quality_model import YoloQualityModel

    cv2.setNumThreads(1)
    csv.field_size_limit(16 * 1024 * 1024)
    qa = project / "results/qa/qualitycheck"
    inventory = json.loads((qa / "reproduction_inventory.json").read_text(encoding="utf-8"))
    image_path = Path(inventory["source_image_search"]["matches"][0])
    image = cv2.imread(str(image_path))
    assert image is not None and image.shape[:2] == (2160, 3840)
    with (qa / "reproduction.csv").open(encoding="utf-8-sig", newline="") as stream:
        event = json.loads(next(csv.DictReader(stream))["Complete fish event"])
    confidence = event.get("detection_confidence", event["analysis"]["model1_detection"]["confidence"])
    detector = SimpleNamespace(model=object(), weights_path=None, confidence_threshold=None,
                               detect=lambda _: [FishDetection(tuple(event["bbox"]), confidence)])
    parts = [PartDetection.from_source_class(p["source_class_id"], p["confidence"], tuple(p["bbox"])) for p in event["parts"]]
    quality = YoloQualityModel(Path("recorded-model2-output-only.pt"), device="cpu",
                              model_id="qualitycheck-recorded-output-only", quality_inference_mode="full_frame",
                              grading_engine=WeightedGradingEngine())
    quality.model = object()
    quality._infer_parts = lambda _: (list(parts), list(parts))
    analyzer = StillImageAnalyzer(detector, quality)
    samples, signatures, diagnostics = [], [], []
    for index in range(args.repeats + 1):
        cv2.setRNGSeed(0)
        started = perf_counter()
        result = analyzer.analyze(image, frame_id="qualitycheck-recorded-photo")
        elapsed = (perf_counter() - started) * 1000
        fish = result["fish"][0]
        signature = {key: fish[key] for key in ("id", "bbox", "quality", "quality_confidence", "parts")}
        signature["grading"] = {key: fish["analysis"][key] for key in (
            "weighted_scores", "effective_weights", "reason_codes", "original_weight_coverage",
        )}
        if index:
            samples.append(elapsed)
            signatures.append(signature)
            diagnostics.append({"frame": result.get("performance", {}),
                                "fish": fish["analysis"].get("performance", {}),
                                "geometry_status": fish["analysis"]["fish_geometry"]["status"],
                                "geometry_reasons": fish["analysis"]["fish_geometry"]["reasons"]})
    assert all(signature == signatures[0] for signature in signatures)
    report = {"scope": "One exported parent and its two recorded Model 2 parts on the original photo; not the original full-frame detection workload",
              "source_root": str(source_root), "image_path": str(image_path),
              "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "image_shape": list(image.shape),
              "models_executed": False, "gpu_work": False, "opencv_threads": cv2.getNumThreads(),
              "warmups": 1, "measured_repeats": args.repeats, "samples_ms": samples,
              "median_ms": float(np.median(samples)), "verdict_signature": signatures[0], "diagnostics": diagnostics,
              "recorded_original_grade": event["quality"], "recorded_original_support": event["quality_confidence"]}
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "median_ms": report["median_ms"], "grade": signatures[0]["quality"]}))


if __name__ == "__main__":
    main()
