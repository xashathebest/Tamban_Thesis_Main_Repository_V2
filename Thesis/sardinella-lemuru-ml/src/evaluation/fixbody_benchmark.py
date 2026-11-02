"""Paired software timings with scripted detections; never an accuracy/FPS study."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from src.api.image_analysis import StillImageAnalyzer, VideoUploadAnalyzer
from src.features.damage import analyze_surface_damage
from src.features.texture import TextureSettings, extract_texture_features
from src.inference.association import ParentAnchor
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import generate_runtime_fish_mask
from src.inference.yolo_fish_detector import FishDetection
from src.inference.yolo_quality_model import YoloQualityModel

ROOT = Path(__file__).resolve().parents[2]
PARENT = (90., 110., 390., 210.)
PARTS = (PartDetection.from_source_class(0, .9, (180, 118, 300, 202)),
         PartDetection.from_source_class(4, .8, (104, 140, 156, 180)),
         PartDetection.from_source_class(2, .7, (330, 142, 376, 178)))


def scene(kind):
    image = np.full((320, 480, 3), 35, np.uint8)
    cv2.ellipse(image, (240, 160), (140, 40), 0, 0, 360, (170, 150, 130), -1)
    if kind == "dark_line":
        cv2.line(image, (190, 145), (290, 175), (20, 20, 20), 4)
    if kind == "stripes":
        for x in range(170, 310, 16):
            cv2.line(image, (x, 136), (x + 12, 183), (40, 40, 40), 3)
    return image


def quality(mode):
    model = YoloQualityModel(Path("scripted-software-benchmark.pt"), device="cpu",
                             model_id="scripted-benchmark-only", quality_inference_mode=mode,
                             grading_engine=WeightedGradingEngine(GradingConfig()))
    model.model = object()
    if mode == "full_frame":
        parts = PARTS
    else:
        parts = tuple(PartDetection.from_source_class(p.source_class_id, p.confidence,
                      (p.bbox[0] - 90, p.bbox[1] - 110, p.bbox[2] - 90, p.bbox[3] - 110)) for p in PARTS)
    model._infer_parts = lambda _: (list(parts), list(parts))
    return model


def verdict_signature(result):
    return [{"id": f["id"], "bbox": f["bbox"], "quality": f["quality"],
             "support": f["quality_confidence"], "weighted_scores": f["analysis"]["weighted_scores"],
             "parts": f["parts"]} for f in result["fish"]]


def timed(function, repeats):
    function()  # Unreported warm-up, same policy for both snapshots.
    samples, result = [], None
    for _ in range(repeats):
        started = perf_counter()
        result = function()
        samples.append((perf_counter() - started) * 1000)
    return {"median_ms": round(median(samples), 4), "p95_ms": round(float(np.percentile(samples, 95)), 4),
            "samples_ms": [round(v, 4) for v in samples]}, result


def collect(repeats=5):
    counters = {"segmentation_calls": 0, "texture_extractions": 0}
    def mask(*args, **kwargs):
        counters["segmentation_calls"] += 1
        return generate_runtime_fish_mask(*args, **kwargs)
    def texture(*args, **kwargs):
        counters["texture_extractions"] += 1
        return extract_texture_features(*args, **kwargs)
    report = {"scope": "SOFTWARE_ONLY_SCRIPTED_DETECTIONS", "real_camera_fps": "NOT_MEASURED",
              "accuracy": "NOT_VALIDATED", "python": platform.python_version(), "platform": platform.platform(),
              "opencv": cv2.__version__, "repeats": repeats, "components": {}, "pipelines": {}}
    for kind in ("clean", "dark_line", "stripes"):
        image = scene(kind)[110:210, 90:390]
        binary, _ = generate_runtime_fish_mask(image)
        rgb = image[..., ::-1]
        timing, result = timed(lambda: analyze_surface_damage(rgb, binary), repeats)
        report["components"][kind] = {**timing, "status": result["status"], "label": result["label"],
            "confidence": result["confidence"], "locations": len(result["locations"]),
            "estimated_length_px": result["estimated_length_px"]}
    fixture = ROOT / "results/qa/body_width/fish-inspection-upload-all.repaired.csv"
    with fixture.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream))
    events = [json.loads(row["Complete fish event"]) for row in saved]
    report["csv_diagnostic"] = {"path": str(fixture.relative_to(ROOT)), "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "records": len(events), "grades": [e["quality"] for e in events],
        "weighted_scores": [e["analysis"]["weighted_scores"] for e in events],
        "historically_recorded_timings_not_new_measurements": [e["analysis"].get("performance", {}) for e in events]}
    patches = [patch(name, mask) for name in (
        "src.inference.preprocessing.generate_runtime_fish_mask", "src.api.image_analysis.generate_runtime_fish_mask",
        "src.inference.fish_geometry_pipeline.generate_runtime_fish_mask")]
    patches += [patch(name, texture, create=True) for name in (
        "src.inference.grading_engine.extract_texture_features", "src.features.damage.extract_texture_features")]
    for item in patches: item.start()
    try:
        for mode in ("crop", "full_frame"):
            model = quality(mode)
            detector = SimpleNamespace(model=object(), detect=lambda _: [FishDetection(PARENT, .98)])
            analyzer = StillImageAnalyzer(detector, model)
            for kind in ("clean", "dark_line"):
                image = scene(kind)
                for name in counters: counters[name] = 0
                timing, result = timed(lambda: analyzer.analyze(image), repeats)
                report["pipelines"][f"image_{mode}_{kind}"] = {**timing, "calls_including_one_warmup": dict(counters),
                    "verdicts": verdict_signature(result), "texture_status": result["fish"][0]["analysis"].get("supporting_image_measurements", {}).get("texture", {}).get("status")}
        with TemporaryDirectory(prefix="tamban_fixbody_video_") as directory:
            path = Path(directory) / "scene.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (480, 320))
            if not writer.isOpened():
                report["pipelines"]["video"] = {"status": "NOT_MEASURED", "reason": "MJPG encoder unavailable"}
            else:
                for _ in range(4): writer.write(scene("clean"))
                writer.release()
                video = VideoUploadAnalyzer(StillImageAnalyzer(detector, quality("full_frame")))
                timing, result = timed(lambda: video.analyze(path, progress=lambda *_: None), min(3, repeats))
                report["pipelines"]["video"] = {**timing, "frames_processed": result["frames_processed"], "verdicts": verdict_signature(result)}
        live_model = quality("full_frame")
        image = scene("clean")
        sequence = []
        started = perf_counter()
        for frame_id in range(4):
            observation = live_model.predict_full_frame(image, [ParentAnchor(1, PARENT, .98)], frame_id=frame_id)[1][0]
            sequence.append({"frame_id": frame_id, "grade": observation.quality, "support": observation.quality_confidence,
                             "scores": observation.analysis["weighted_scores"]})
        report["pipelines"]["temporal_quality_replay_not_camera_fps"] = {
            "total_ms": round((perf_counter() - started) * 1000, 4), "frames": 4, "sequence": sequence}
    finally:
        for item in reversed(patches): item.stop()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 3 <= args.repeats <= 20: parser.error("repeats must be between 3 and 20")
    result = collect(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scope": result["scope"],
                      "pipeline_medians_ms": {k: v.get("median_ms", v.get("total_ms")) for k, v in result["pipelines"].items()}}))


if __name__ == "__main__": main()
