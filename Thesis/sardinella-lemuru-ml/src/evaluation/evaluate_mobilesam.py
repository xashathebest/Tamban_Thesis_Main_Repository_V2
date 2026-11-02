"""Paired CPU benchmark of unchanged detector outputs and optional segmentation.

No instance-mask/ownership ground truth is available to this harness. Engineering
check counts are diagnostics, never separation accuracy or validated fish masks.
Run with ``python -m src.evaluation.evaluate_mobilesam --output results/qa/mobilesam``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from statistics import median
from time import perf_counter
from unittest.mock import patch

import cv2
import numpy as np

from src.api.image_analysis import StillImageAnalyzer
from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.mask_ownership import validate_candidate_masks
from src.inference.mobilesam_backend import get_mobilesam_service
from src.inference.model_registry import ModelRegistry
from src.inference.preprocessing import RuntimeMaskContext
from src.inference.part_types import PartDetection
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenes():
    """Original files remain read-only; every transformation is recorded."""
    test = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test"
    paths = sorted(test.glob("*.jpg"))
    specifications = [
        ("natural_multi", paths[2], "original pixels", ["multiple_fish", "neighbor_anatomy"]),
        ("natural_severe_overlap", paths[0], "original pixels", ["severe_overlap", "multiple_fish"]),
        ("natural_touching_pair", paths[5], "crop x=390:640,y=140:500; two touching right-hand fish", ["two_overlapping_fish", "clipped"]),
        ("natural_damaged", paths[10], "original pixels", ["damaged_anatomy", "multiple_fish"]),
        ("dark_lighting", paths[2], "multiply BGR channels by 0.35, clip uint8", ["dark_lighting"]),
        ("uneven_lighting", paths[2], "horizontal multiplicative light ramp 0.20 to 1.00", ["uneven_lighting"]),
        ("clipped_fish", paths[2], "crop x=45:580,y=180:430", ["partly_outside_image"]),
        ("isolated_crop", paths[4], "crop x=25:305,y=240:360; horizontal visible fish and retained background", ["isolated_candidate_crop"]),
    ]
    original = Path("C:/Users/User/Downloads/Class B/WIN_20260823_20_47_00_Pro.jpg")
    if original.is_file():
        specifications.append(("recorded_reproduction", original, "resize longest side to 1280 for bounded CPU benchmark", ["multiple_fish", "severe_overlap", "clipped", "neighbor_head", "neighbor_tail"]))
    isolated = Path("C:/Users/User/Downloads/Class B/WIN_20260823_20_46_00_Pro.jpg")
    if isolated.is_file():
        specifications.append(("isolated_clean", isolated,
            "resize 960x540; rotate -47 degrees about (575,330); crop x=325:825,y=260:400; inspected single intact silhouette",
            ["isolated_fish", "rotation_derived_crop"]))
    for name, path, operation, tags in specifications:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Cannot decode benchmark source: {path}")
        native_shape = list(image.shape[:2])
        if name == "natural_touching_pair": image = image[140:500, 390:640].copy()
        elif name == "dark_lighting": image = np.clip(image.astype(float) * .35, 0, 255).astype(np.uint8)
        elif name == "uneven_lighting": image = np.clip(image.astype(float) * np.linspace(.2, 1., image.shape[1])[None, :, None], 0, 255).astype(np.uint8)
        elif name == "clipped_fish": image = image[180:430, 45:580].copy()
        elif name == "isolated_crop": image = image[240:360, 25:305].copy()
        elif name == "recorded_reproduction": image = cv2.resize(image, (1280, 720), interpolation=cv2.INTER_AREA)
        elif name == "isolated_clean":
            image = cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA)
            image = cv2.warpAffine(image, cv2.getRotationMatrix2D((575,330), -47, 1), (960,540))[260:400, 325:825].copy()
        yield name, image, {"path": str(path), "sha256": sha(path), "native_shape": native_shape,
                            "operation": operation, "benchmark_shape": list(image.shape[:2]), "scenario_tags": tags,
                            "tag_basis": "qualitative software review; not expert ownership ground truth"}


def signature(result):
    return [{"id": fish["id"], "grade": fish["quality"], "support": fish["quality_confidence"],
             "scores": fish["analysis"]["weighted_scores"], "parts": fish["parts"]}
            for fish in result["fish"]]


def rectangle_intrusions(parents, associations):
    """Part centers in competing boxes are stress cases, not ownership labels."""
    rows = []
    for association in associations:
        if association.part.region not in {"Head", "Tail"}: continue
        x, y = association.part.center
        contenders = [p.track_id for p in parents if p.bbox[0] <= x <= p.bbox[2] and p.bbox[1] <= y <= p.bbox[3]]
        if len(contenders) > 1:
            rows.append({"region":association.part.region,"part_bbox":list(association.part.bbox),
                         "parent_rectangles_containing_center":contenders,"original_association_status":association.status,
                         "original_assigned_parent":association.track_id,"expert_ownership_verified":False})
    return rows


def masks_from_context(context, parents):
    if context._experimental:
        return context._experimental.candidates
    candidates = {}
    # Inspect cached masks only: do not run additional GrabCut outside the timer.
    for parent in parents:
        choices = [(mask, metadata) for key, (mask, metadata) in context._masks.items()
                   if key[0] == parent.track_id and isinstance(mask, np.ndarray)]
        if not choices:
            candidates[parent.track_id] = {"status": "unavailable", "reason": "No cached foreground mask"}
            continue
        mask, metadata = max(choices, key=lambda pair: pair[0].size)
        left, top, right, bottom = metadata["crop_bounds"]
        native = np.zeros(context._frame.shape[:2], dtype=bool)
        native[top:bottom, left:right] = mask
        candidates[parent.track_id] = {"status": "candidate", "parent_id": parent.track_id,
                                       "mask": native, "score": None}
    return candidates


def summarize(result, context, candidates, parents, parts):
    checks = validate_candidate_masks(candidates, parents, parts, frame_shape=context._frame.shape)
    fish = result["fish"]
    return {"mask_context": context.diagnostics(), "candidate_masks": sum(isinstance(c.get("mask"), np.ndarray) for c in candidates.values()),
            "engineering_check_counts": dict(Counter(item["status"] for item in checks.values())),
            "engineering_checks_passed_unvalidated": sum(v["engineering_checks_passed"] for v in checks.values()),
            "validated_fish_specific_masks": 0, "independent_ownership_accuracy": None,
            "expert_part_ownership_correctness": None,
            "mask_rejection_reasons": dict(Counter(reason for v in checks.values() for reason in v["reasons"])),
            "mask_checks": checks, "grade_signature": signature(result),
            "graded_fish": sum(f["quality"] != "Ungraded" and f["quality"] is not None for f in fish),
            "width_reliability": dict(Counter(str(f["analysis"].get("fish_geometry", {}).get("reliability")) for f in fish)),
            "width_estimate_only_count": sum(f["analysis"].get("fish_geometry", {}).get("reliability") == "Estimated pixel geometry; native boundary not validated" for f in fish),
            "physical_calibration_applied_count": sum(f["analysis"].get("fish_geometry", {}).get("physical_calibration", {}).get("applied") is True for f in fish),
            "width_grading_contribution_count": sum(f["analysis"].get("geometric_support", {}).get("contribution_applied") is True or f["analysis"].get("body_width", {}).get("score_contributed") is True for f in fish),
            "damage_status": dict(Counter(str(f["analysis"].get("surface_damage", {}).get("status")) for f in fish)),
            "confirmed_cracks": 0, "crack_localization_accuracy": None,
            "performance": result["performance"]}


def draw(image, parents, parts, candidates, checks, label):
    canvas = image.copy()
    palette = [(70, 220, 60), (30, 170, 255), (220, 80, 220), (255, 210, 40), (200, 150, 80)]
    for parent in parents:
        color = palette[(parent.track_id - 1) % len(palette)]
        candidate = candidates.get(parent.track_id, {})
        mask = candidate.get("mask")
        if isinstance(mask, np.ndarray):
            canvas[mask] = (.65 * canvas[mask] + .35 * np.array(color)).astype(np.uint8)
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(canvas, contours, -1, color, 1)
        left, top, right, bottom = map(int, parent.bbox)
        cv2.rectangle(canvas, (left, top), (right, bottom), color, 1)
        state = checks.get(parent.track_id, {}).get("status", "no mask")
        cv2.putText(canvas, f"{parent.track_id} {state[:10]}", (max(0,left), max(14,top+14)), 0, .35, color, 1)
    for part in parts:
        left, top, right, bottom = map(int, part.bbox)
        cv2.rectangle(canvas, (left, top), (right, bottom), (235, 235, 235), 1)
        cv2.putText(canvas, part.region[0], (left, top+10), 0, .3, (255,255,255), 1)
    scale = 480 / canvas.shape[1]
    canvas = cv2.resize(canvas, (480, max(1, int(canvas.shape[0]*scale))))
    canvas = cv2.copyMakeBorder(canvas, 45, 0, 0, 0, cv2.BORDER_CONSTANT)
    cv2.putText(canvas, label, (8, 19), 0, .48, (255,255,255), 1)
    cv2.putText(canvas, "Candidate diagnostic only; no expert mask ground truth", (8, 36), 0, .34, (220,220,220), 1)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/qa/mobilesam")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--reuse-detections", type=Path, help="Replay exact recorded M1/M2 outputs instead of rerunning either detector")
    parser.add_argument("--scenarios", nargs="+", help="Optional exact scenario names to measure")
    args = parser.parse_args()
    if not 2 <= args.repeats <= 10: parser.error("repeats must be between 2 and 10")
    import torch
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    if torch.cuda.is_initialized(): raise RuntimeError("This benchmark must not initialize CUDA")
    args.output.mkdir(parents=True, exist_ok=True)
    replay = json.loads(args.reuse_detections.read_text(encoding="utf-8")) if args.reuse_detections else None
    replay_records = {record["scenario"]:record for record in replay["records"]} if replay else {}
    registry = ModelRegistry(ROOT)
    first = registry.get_model(registry.get_default_model1_id())
    second = registry.get_model("yolo26m_partdet")
    checkpoints = {entry.id: {"path": str(ROOT / entry.path), "sha256_before": sha(ROOT / entry.path)} for entry in (first, second)}
    implementation_paths = ["src/inference/experimental_segmentation.py", "src/inference/mask_ownership.py", "src/inference/mobilesam_backend.py",
                            "src/inference/preprocessing.py", "src/inference/fish_geometry_pipeline.py", "src/inference/yolo_quality_model.py", "src/api/image_analysis.py"]
    implementation = {path: sha(ROOT / path) for path in implementation_paths}
    started = perf_counter()
    detector = YoloFishDetector(ROOT / first.path, device="cpu", image_size=first.input_size,
                                confidence_threshold=.5, iou_threshold=.7, max_detections=132)
    quality = YoloQualityModel(ROOT / second.path, model_id=second.id, device="cpu", image_size=second.input_size,
                               confidence_threshold=.25, quality_inference_mode="full_frame")
    if replay:
        # Real detections are retained verbatim; these adapters grade fixed
        # outputs without reloading or running either protected network.
        detector.model = quality.model = object()
    elif not detector.load() or not quality.load():
        raise RuntimeError(f"Model loading failed: {detector.error}; {quality.error}")
    load_ms = (perf_counter() - started) * 1000
    actual_detect, actual_parts = detector.detect, quality._infer_parts
    service = get_mobilesam_service()
    started = perf_counter()
    service._load()
    sam_load_ms = (perf_counter() - started) * 1000
    # Warm the actual encoder/decoder once; per-image embedding remains fresh.
    warm = np.full((128,256,3), 40, np.uint8)
    cv2.ellipse(warm, (128,64), (90,25), 0, 0, 360, (170,160,150), -1)
    with service.open_frame(warm, "benchmark-warmup") as session: session.predict(1, (20,30,235,100))
    records = []
    for name, image, source in scenes():
        if args.scenarios and name not in args.scenarios: continue
        cv2.imwrite(str(args.output / f"{name}.source.png"), image)
        if replay:
            previous = replay_records[name]
            if source != previous["source"]: raise ValueError("Recorded detections differ from requested source pixels/transform")
            from src.inference.yolo_fish_detector import FishDetection
            detections = [FishDetection(tuple(d["bbox"]),d["confidence"]) for d in previous["detections"]]
            def restore(rows):
                return [PartDetection.from_source_class(p["source_class_id"],p["confidence"],tuple(p["bbox"]),p.get("mask")) for p in rows]
            selected, raw = restore(previous["parts"]), restore(previous["raw_parts"])
            m1_ms, m2_ms = previous["detector_ms"], previous["part_model_ms"]
        else:
            started = perf_counter(); detections = actual_detect(image); m1_ms = (perf_counter()-started)*1000
            started = perf_counter(); selected, raw = actual_parts(image); m2_ms = (perf_counter()-started)*1000
        parents = [ParentAnchor(i,d.bbox,d.confidence) for i,d in enumerate(detections,1)]
        associations = associate_parts_to_parents(selected, parents)
        record = {"scenario": name, "source": source, "detector_ms": m1_ms, "part_model_ms": m2_ms,
                  "detections": [{"id":p.track_id,"bbox":list(p.bbox),"confidence":p.confidence} for p in parents],
                  "parts": [p.to_dict() for p in selected], "raw_parts": [p.to_dict() for p in raw],
                  "competing_rectangle_part_centers":rectangle_intrusions(parents, associations),
                  "original_associations": [a.to_dict() for a in associations], "backends": {}}
        detector.detect = lambda _image: list(detections)
        quality._infer_parts = lambda _image: (list(selected), list(raw))
        analyzer = StillImageAnalyzer(detector, quality)
        tiles = []
        for backend in ("grabcut", "mobilesam_experimental", "geometry_only"):
            contexts = []
            def context_factory(*a, **kw):
                context = RuntimeMaskContext(*a, **kw); contexts.append(context); return context
            samples, segmentation_samples = [], []
            with patch("src.api.image_analysis.RuntimeMaskContext", context_factory):
                # Uniform one warm-up per scene/backend, excluded from samples.
                for repetition in range(args.repeats + 1):
                    started = perf_counter()
                    result = analyzer.analyze(image, frame_id=f"benchmark:{name}:{repetition}", segmentation_backend=backend)
                    wall = (perf_counter()-started)*1000
                    if repetition:
                        samples.append(wall)
                        segmentation_samples.append(result["performance"]["segmentation_processing_ms"])
                    contexts[:-1] = []  # Retain only one frame's masks.
            context = contexts[-1]
            candidates = masks_from_context(context, parents)
            summary = summarize(result, context, candidates, parents, selected)
            summary.update(timed_repetitions=args.repeats, post_detection_wall_ms=samples,
                           median_post_detection_wall_ms=median(samples), segmentation_ms=segmentation_samples,
                           median_segmentation_ms=median(segmentation_samples),
                           estimated_total_with_single_detector_pass_ms=median(samples)+m1_ms+m2_ms,
                           total_scope="Measured fixed-detection replay wall time plus one measured M1/M2 pass; excludes checkpoint load, I/O, decode and network",
                           peak_gpu_memory_bytes=None, gpu_reason="CPU-only; CUDA was not initialized")
            record["backends"][backend] = summary
            tiles.append(draw(image, parents, selected, candidates, summary["mask_checks"], backend))
        baseline = record["backends"]["grabcut"]["grade_signature"]
        record["weighted_grades_unchanged"] = all(v["grade_signature"] == baseline for v in record["backends"].values())
        if not record["weighted_grades_unchanged"]: raise AssertionError(f"Segmentation changed grade evidence: {name}")
        cv2.imwrite(str(args.output / f"{name}.comparison.png"), np.hstack(tiles))
        records.append(record)
        print(json.dumps({"scenario":name,"fish":len(parents),"parts":len(selected),"medians_ms":{k:round(v["median_post_detection_wall_ms"],2) for k,v in record["backends"].items()},"grades_unchanged":True}), flush=True)
        del contexts, context, candidates, result
    for entry in (first, second): checkpoints[entry.id]["sha256_after"] = sha(ROOT / entry.path)
    report = {"scope":"REAL_CPU_MODELS_FIXED_DETECTION_PAIRED_REPLAY", "platform":platform.platform(), "python":platform.python_version(),
              "dependencies":{n:importlib.metadata.version(n) for n in ("torch","torchvision","ultralytics","numpy","opencv-python")},
              "device":"cpu", "threads":1, "fp16":False, "peak_gpu_memory_bytes":None,
              "gpu_memory_reason":"CPU-only experiment; RTX 2050 latency and memory were not measured while separate training may be active.",
              "detector_models_loaded_in_this_process":not bool(replay),
              "detector_model_loading_ms":load_ms if not replay else None, "mobilesam_loading_ms":sam_load_ms, "checkpoint":service.status(), "protected_checkpoints":checkpoints,
              "recorded_detections_reused_from":str(args.reuse_detections) if replay else None,
              "implementation_sha256_at_start":implementation,
              "implementation_unchanged_during_run":all(sha(ROOT / path) == digest for path,digest in implementation.items()),
              "ground_truth":{"whole_fish_masks":False,"expert_ownership":False,"crack_localization":False,
                              "note":"Existing dataset polygons label Model2 parts; they are not independent whole-fish instance-mask ground truth. No accuracy percentage is reported."},
              "limitations":["Small convenience sample; not a representative accuracy evaluation.","Derived lighting/crops are synthetic stress cases, not new annotation labels.",
                             "Engineering rejection counts can reject good masks or miss merged fish; they are not correctness labels.",
                             "Isolated crop can retain neighboring pixels and can omit fish tips; review comparison before treating it as isolated anatomy.",
                             "Grading comparison holds neural detections fixed; does not measure detector variability.","MobileSAM FP32 CPU default remains experimental; no claim of RTX 2050 speed improvement.",
                             "Unvalidated measurements and ordinary detector Body boxes do not authorize anatomical measurements or crack grading."],
              "records":records}
    (args.output / "benchmark.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    (args.output / "scenario_manifest.json").write_text(json.dumps([{ "scenario":r["scenario"],**r["source"]} for r in records],indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(args.output / "benchmark.json"),"scenarios":len(records),"grades_unchanged":True}),flush=True)


if __name__ == "__main__":
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    main()
