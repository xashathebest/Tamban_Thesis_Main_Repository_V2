"""Benchmark Model 1 and Model 2 on requested devices without changing weights."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.inference.compute import resolve_compute, synchronize
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel


def _measure(label: str, fn, device: str, warmup: int, repetitions: int) -> dict[str, object]:
    for _ in range(warmup):
        fn()
    synchronize(device)
    started = perf_counter()
    for _ in range(repetitions):
        fn()
    synchronize(device)
    elapsed = perf_counter() - started
    return {
        "stage": label,
        "device": device,
        "repetitions": repetitions,
        "elapsed_seconds": round(elapsed, 6),
        "average_ms": round(elapsed * 1000 / repetitions, 3),
        "inference_fps": round(repetitions / elapsed, 3) if elapsed else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model1", type=Path, required=True)
    parser.add_argument("--model2", type=Path, required=True)
    parser.add_argument("--devices", default="cpu,cuda:0")
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    if image is None:
        raise SystemExit(f"Could not read image: {args.image}")
    output: dict[str, object] = {"image": str(args.image), "runs": []}
    for requested in (item.strip() for item in args.devices.split(",")):
        compute = resolve_compute(requested, "auto")
        if compute.device == "cpu" and requested.startswith("cuda"):
            output.setdefault("skipped", []).append({"requested_device": requested, "reason": compute.fallback_reason})
            continue
        detector = YoloFishDetector(args.model1, device=compute.device)
        quality = YoloQualityModel(args.model2, device=compute.device)
        if not detector.load() or not quality.load():
            raise SystemExit(f"Could not load models on {compute.device}: {detector.error or quality.error}")
        model1_parameters = getattr(getattr(detector.model, "model", detector.model), "parameters", None)
        model2_parameters = getattr(getattr(quality.adapter, "model", quality.model), "parameters", None)
        output["runs"].append({
            "compute": compute.to_dict(),
            "model1_parameter_device": str(next(model1_parameters()).device) if callable(model1_parameters) else None,
            "model2_parameter_device": str(next(model2_parameters()).device) if callable(model2_parameters) else None,
            "model1": _measure("model1", lambda: detector.detect(image), compute.device, args.warmup, args.repetitions),
            "model2": _measure("model2", lambda: quality._infer_parts(image), compute.device, args.warmup, args.repetitions),
        })
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
