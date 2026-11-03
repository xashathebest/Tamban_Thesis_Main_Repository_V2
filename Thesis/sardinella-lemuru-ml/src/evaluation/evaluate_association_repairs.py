"""Read-only, fixed-detection before/after association benchmark.

This measures trace completeness, changed decisions and latency, not ownership
accuracy. No independent parent/part ownership labels are available. The optional
``--collect-test-images`` pass runs the protected detectors once on CPU, freezes
their native-coordinate outputs, and never trains or writes model weights.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import zipfile

import cv2
import numpy as np

from src.inference import association as current_association
from src.inference.grading_engine import load_grading_config
from src.inference.grading_policy import FishGradingInput, GRADE_NAMES, grade_fish
from src.inference.part_types import PartDetection


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "results/qa/additional"
CSV_FIXTURE = ROOT / "tests/fixtures/fish-inspection-upload-all.csv"
TEST_IMAGES = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_parts(rows):
    return [PartDetection.from_source_class(int(p["source_class_id"]), float(p["confidence"]),
                                           tuple(p["bbox"]), p.get("mask")) for p in rows]


def part_key(part):
    """Exact raw identities: never merge nearby but distinct detections."""
    if isinstance(part, PartDetection):
        part = part.to_dict()
    return (int(part["source_class_id"]), float(part["confidence"]), tuple(part["bbox"]))


def csv_scene(path=CSV_FIXTURE, image_root=Path("C:/Users/User/Downloads/Class B")):
    """Recover all original global detections, not crop-clamped debug copies.

    Per-fish association summaries omit ambiguities unrelated to that fish.
    Their exact-identity union recovers the complete 22-candidate original run.
    """
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        exported = list(csv.DictReader(source))
    fish = [json.loads(row["Complete fish event"]) for row in exported]
    metadata = json.loads(exported[0]["Source metadata"])
    original = image_root / metadata["source_name"]
    recovered = {}
    for record in fish:
        for item in record["analysis"]["quality_inference"]["association"]["parts"]:
            recovered.setdefault(part_key(item["part"]), item["part"])
    parts = list(recovered.values())
    expected = metadata["model_info"]["quality"]["diagnostics"].get("last_raw_candidate_count")
    if expected is not None and len(parts) != expected:
        raise ValueError(f"CSV global trace is incomplete: recovered {len(parts)} of {expected} candidates")
    return {"scenario": "original_seven_record_csv", "cohort": "original_csv",
            "source": {"path": str(original), "sha256": sha(original) if original.is_file() else None,
                       "operation": "original native pixels; original recorded parent/part boxes",
                       "native_shape": [2160, 3840], "benchmark_shape": [2160, 3840],
                       "csv_sha256": sha(Path(path)), "analyzed_at": metadata.get("analyzed_at")},
            "detections": [{"id": f["id"], "bbox": f["bbox"], "confidence": f["detector_confidence"]} for f in fish],
            "parts": parts, "raw_parts": parts,
            "detector_ms": None, "part_model_ms": None,
            "original_export_grades": [{"id": f["id"], "grade": f["quality"],
                                        "weighted_scores": f["analysis"]["weighted_scores"]} for f in fish],
            "provenance": "Exact recorded legacy Model1 parents + original full-frame Model2 outputs. No current Model1 substitution."}


def load_baseline(path):
    name = "_tamban_association_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import baseline: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def grades_for(module, decisions, parents, policy):
    """Same canonical grade policy on both sides; association is the variable."""
    output = []
    for parent in parents:
        assigned = [r.part for r in decisions if r.status == "ASSIGNED" and r.track_id == parent.track_id]
        scores = {region: {grade: 0.0 for grade in GRADE_NAMES} for region in ("Head", "Body", "Tail")}
        presence = {region: 0.0 for region in scores}
        for part in assigned:
            scores[part.region][part.grade] = max(scores[part.region][part.grade], part.confidence)
            presence[part.region] = max(presence[part.region], part.confidence)
        summary = module.association_summary(decisions, parent.track_id)
        ambiguous = any(item["status"] == "AMBIGUOUS" and item.get("part", {}).get("region") in policy.required_regions()
                        for item in summary["parts"])
        verdict = grade_fish(FishGradingInput(part_scores=scores, presence_confidence=presence,
                            association_status="ambiguous" if ambiguous else "valid"), policy).to_dict()
        output.append({"id": parent.track_id, **verdict})
    return output


def evaluate_scene(scene, module, *, repeats=7):
    parents = [module.ParentAnchor(int(d["id"]), tuple(d["bbox"]), d.get("confidence")) for d in scene["detections"]]
    parts = restore_parts(scene["parts"])
    policy = load_grading_config().to_policy()
    samples = []
    for _ in range(repeats):
        started = perf_counter()
        decisions = module.associate_parts_to_parents(parts, parents)
        samples.append((perf_counter() - started) * 1000)
    started = perf_counter()
    grades = grades_for(module, decisions, parents, policy)
    grade_ms = (perf_counter() - started) * 1000
    assigned = [row for row in decisions if row.status == "ASSIGNED"]
    identities = [(row.track_id, row.part.region) for row in assigned]
    if len(identities) != len(set(identities)):
        raise AssertionError("More than one selected part for a parent/region")
    if len(decisions) != len(parts) or Counter(part_key(r.part) for r in decisions) != Counter(part_key(p) for p in parts):
        raise AssertionError("A raw selected part disappeared or was fabricated during association")
    return {"selected_counts": dict(Counter(p.region for p in parts)),
            "assigned_counts": dict(Counter(row.part.region for row in assigned)),
            "status_counts": dict(Counter(row.status for row in decisions)),
            "reasons": dict(Counter(row.reason or "no_explicit_reason" for row in decisions if row.status != "ASSIGNED")),
            "ungraded_count": sum(v["final_grade"] == "Ungraded" for v in grades),
            "parent_count": len(parents), "grades": grades,
            "association_latency_ms": {"median": median(samples), "samples": samples, "repeats": repeats},
            "policy_replay_ms": grade_ms, "decisions": [row.to_dict() for row in decisions],
            "correct_assignments": None, "false_associations": None, "correct_grading_coverage": None,
            "independent_ownership_labels_available": False}


def changes_between(before, after):
    old = {part_key(r["part"]): r for r in before["decisions"]}
    changed = []
    for new in after["decisions"]:
        previous = old[part_key(new["part"])]
        if (previous["status"], previous["track_id"], previous.get("reason")) != (new["status"], new["track_id"], new.get("reason")):
            changed.append({"part": new["part"], "before": previous, "after": new,
                            "expert_ownership_verified": False})
    return changed


def draw_decisions(image, scene, result, title):
    scale = min(1., 1200. / image.shape[1])
    canvas = cv2.resize(image, None, fx=scale, fy=scale)
    for parent in scene["detections"]:
        x1, y1, x2, y2 = [int(v * scale) for v in parent["bbox"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (210, 210, 210), 1)
        cv2.putText(canvas, f"F{parent['id']}", (x1, max(12, y1 + 13)), 0, .45, (255, 255, 255), 1, cv2.LINE_AA)
    for index, row in enumerate(result["decisions"], 1):
        x1, y1, x2, y2 = [int(v * scale) for v in row["part"]["bbox"]]
        color = {"ASSIGNED": (60, 230, 60), "AMBIGUOUS": (0, 190, 255), "REJECTED": (200, 80, 230)}.get(row["status"], (70, 70, 255))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        owner = f"F{row['track_id']}" if row["track_id"] is not None else row["status"][:3]
        cv2.putText(canvas, f"{index}:{row['part']['region'][0]} {owner}", (x1, max(12, y1 - 3)), 0, .35, color, 1, cv2.LINE_AA)
    canvas = cv2.copyMakeBorder(canvas, 50, 0, 0, 0, cv2.BORDER_CONSTANT)
    cv2.putText(canvas, title, (8, 19), 0, .48, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, "Green assigned | Orange ambiguous | Red unassigned. No expert ownership ground truth.", (8, 39), 0, .34, (230, 230, 230), 1, cv2.LINE_AA)
    return canvas


def source_image(scene, recorded_root):
    if scene["cohort"] == "recorded_stress_scenes":
        path = recorded_root / f"{scene['scenario']}.source.png"
    else:
        path = Path(scene["source"]["path"])
        if not path.is_file():
            return None
        if sha(path) != scene["source"]["sha256"]:
            raise ValueError(f"Source bytes changed: {path}")
    image = cv2.imread(str(path))
    if image is not None and list(image.shape[:2]) != scene["source"]["benchmark_shape"]:
        raise ValueError(f"Source pixel shape differs from frozen detections: {path}")
    return image


def collect_test_images(path):
    """CPU inference once, preserving adapter-native coords and all candidates."""
    import torch
    from src.inference.model_registry import ModelRegistry
    from src.inference.yolo_fish_detector import YoloFishDetector
    from src.inference.yolo_quality_model import YoloQualityModel

    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    registry = ModelRegistry(ROOT)
    first = registry.get_model(registry.get_default_model1_id())
    second = registry.get_model("yolo26m_partdet")
    model_hashes = {e.id: sha(ROOT / e.path) for e in (first, second)}
    detector = YoloFishDetector(ROOT / first.path, device="cpu", image_size=first.input_size,
                               confidence_threshold=.5, iou_threshold=.7, max_detections=132)
    quality = YoloQualityModel(ROOT / second.path, model_id=second.id, device="cpu", image_size=second.input_size,
                               confidence_threshold=.25, quality_inference_mode="full_frame")
    if not detector.load() or not quality.load():
        raise RuntimeError(f"Protected model CPU load failed: {detector.error}; {quality.error}")
    records = []
    for image_path in sorted(TEST_IMAGES.glob("*.jpg")):
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Cannot decode {image_path}")
        started = perf_counter()
        detections = detector.detect(image)
        detector_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        selected, raw = quality._infer_parts(image)
        part_ms = (perf_counter() - started) * 1000
        records.append({"scenario": image_path.stem, "cohort": "current_17_test_images",
                        "source": {"path": str(image_path), "sha256": sha(image_path), "operation": "original native pixels",
                                   "native_shape": list(image.shape[:2]), "benchmark_shape": list(image.shape[:2])},
                        "detections": [{"id": i, "bbox": list(d.bbox), "confidence": d.confidence} for i, d in enumerate(detections, 1)],
                        "parts": [p.to_dict() for p in selected], "raw_parts": [p.to_dict() for p in raw],
                        "detector_ms": detector_ms, "part_model_ms": part_ms,
                        "provenance": "Actual unchanged CPU FP32 detectors; one frozen pass, no segmentation or association during collection."})
        print(f"Frozen {len(records)}/17: {image_path.name}; parents={len(detections)}, selected/raw={len(selected)}/{len(raw)}", flush=True)
    for entry in (first, second):
        if sha(ROOT / entry.path) != model_hashes[entry.id]:
            raise AssertionError("Protected model bytes changed")
    if torch.cuda.is_initialized():
        raise AssertionError("CPU benchmark initialized CUDA")
    payload = {"scope": "CPU_FP32_NATIVE_COORDINATE_FIXED_DETECTIONS", "device": "cpu", "threads": 1,
               "model_sha256": model_hashes, "records": records, "cuda_initialized": False,
               "small_parts_below_threshold_not_recorded": True,
               "raw_definition": "Post-Ultralytics predict outputs at production .25 confidence; not pre-NMS logits."}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def audit_postprocessing(output):
    """Inspect real trusted local checkpoints and predictor defaults on CPU."""
    import torch
    from ultralytics import __version__ as ultralytics_version
    from ultralytics.utils import DEFAULT_CFG_DICT
    from src.inference.yolo_fish_detector import validate_yolo_fish_detector_class_mapping
    from src.inference.yolo_quality_model import validate_yolo_quality_class_mapping

    torch.set_num_threads(1)
    registry = json.loads((ROOT / "models/MODEL_REGISTRY.json").read_text(encoding="utf-8"))
    payload = {"scope": "read-only checkpoint metadata and installed predictor defaults; no inference",
               "ultralytics_version": ultralytics_version, "models": [],
               "torch_cuda_initialized_before": torch.cuda.is_initialized(),
               "installed_predictor_defaults": {key: DEFAULT_CFG_DICT.get(key) for key in
                   ("iou", "agnostic_nms", "classes", "max_det", "rect", "imgsz", "conf", "half", "end2end")}}
    for entry in registry["models"]:
        if entry["id"] not in {"fish_parent_detector", "yolo26m_partdet"}:
            continue
        path = ROOT / entry["path"]
        # These are the same user-owned local checkpoints loaded by production.
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        model = checkpoint.get("ema") or checkpoint.get("model")
        names = getattr(model, "names", {})
        validator = validate_yolo_fish_detector_class_mapping if entry["id"] == "fish_parent_detector" else validate_yolo_quality_class_mapping
        validator(names)
        payload["models"].append({"id": entry["id"], "sha256": sha(path),
                                  "registry_sha256_matches": sha(path) == entry["sha256"],
                                  "actual_names": names, "input_size": entry["input_size"],
                                  "confidence": entry["default_conf"], "end2end": getattr(model, "end2end", None),
                                  "head_end2end": getattr(model.model[-1], "end2end", None),
                                  "checkpoint_args": {key: (checkpoint.get("train_args") or {}).get(key)
                                      for key in ("imgsz", "iou", "conf", "agnostic_nms", "max_det", "rect")}})
        del model, checkpoint
    payload["torch_cuda_initialized_after"] = torch.cuda.is_initialized()
    baseline_zip = output / "baseline_source.zip"
    if not baseline_zip.is_file():
        baseline_zip = ROOT / "results/qa/sam_features/baseline_source.zip"
    payload["predictor_source_baseline"] = str(baseline_zip) if baseline_zip.is_file() else None
    payload["source_ast_comparison"] = {}
    if baseline_zip.is_file():
        with zipfile.ZipFile(baseline_zip) as saved:
            if "baseline_manifest.json" in saved.namelist():
                manifest = json.loads(saved.read("baseline_manifest.json"))
                payload["predictor_source_baseline_provenance"] = {
                    key: manifest.get(key) for key in ("head", "construction")}
            for name, function in (("src/inference/model_adapters.py", "predict"),
                                   ("src/inference/yolo_fish_detector.py", "_detect"),
                                   ("src/inference/yolo_quality_model.py", "_infer_parts")):
                if name not in saved.namelist():
                    continue
                def signature(source):
                    tree = ast.parse(source)
                    return [ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function]
                old = saved.read(name).decode("utf-8-sig")
                new = (ROOT / name).read_text(encoding="utf-8-sig")
                payload["source_ast_comparison"][f"{name}:{function}"] = signature(old) == signature(new)
    if payload["torch_cuda_initialized_after"] or not all(m["registry_sha256_matches"] for m in payload["models"]):
        raise AssertionError("Read-only audit failed its CPU/model-integrity guard")
    (output / "postprocessing_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def audit_csv_crops(output):
    """Measure crop-only truncation of accepted native evidence, without models."""
    from src.inference.preprocessing import crop_assigned_evidence, crop_fish

    scene = csv_scene()
    frame = source_image(scene, output)
    if frame is None:
        raise ValueError("Original CSV image unavailable: cannot inspect source crops")
    parents = [current_association.ParentAnchor(d["id"], tuple(d["bbox"]), d["confidence"])
               for d in scene["detections"]]
    associations = current_association.associate_parts_to_parents(restore_parts(scene["parts"]), parents)
    rows = []
    for parent in parents:
        owned = [a.part for a in associations if a.status == "ASSIGNED" and a.track_id == parent.track_id]
        _, old = crop_fish(frame, parent.bbox, padding=0)
        _, new = crop_assigned_evidence(frame, parent.bbox, [p.bbox for p in owned], padding=0)
        def bounds(crop):
            return [crop.x1, crop.y1, crop.x2, crop.y2]
        def lost(part, crop):
            box = part.bbox
            retained = max(0., min(box[2], crop.x2) - max(box[0], crop.x1)) * max(0., min(box[3], crop.y2) - max(box[1], crop.y1))
            return {"edge_trim_px_left_top_right_bottom": [max(0., crop.x1 - box[0]), max(0., crop.y1 - box[1]),
                                                         max(0., box[2] - crop.x2), max(0., box[3] - crop.y2)],
                    "lost_bbox_area_fraction": 1. - retained / ((box[2] - box[0]) * (box[3] - box[1]))}
        details = [{"region": part.region, "native_bbox": list(part.bbox), "old": lost(part, old), "adaptive": lost(part, new)} for part in owned]
        if any(any(part["adaptive"]["edge_trim_px_left_top_right_bottom"]) for part in details):
            raise AssertionError("Adaptive crop still truncates accepted native evidence")
        rows.append({"fish_id": parent.track_id, "original_model1_anchor": list(parent.bbox),
                     "old_crop_bounds": bounds(old), "adaptive_crop_bounds": bounds(new),
                     "outward_expansion_px_left_top_right_bottom": [old.x1-new.x1, old.y1-new.y1, new.x2-old.x2, new.y2-old.y2],
                     "parent_anchor_touches_native_frame": parent.bbox[0] <= 0 or parent.bbox[1] <= 0 or parent.bbox[2] >= frame.shape[1] or parent.bbox[3] >= frame.shape[0],
                     "adaptive_crop_touches_native_frame": new.x1 == 0 or new.y1 == 0 or new.x2 == frame.shape[1] or new.y2 == frame.shape[0],
                     "accepted_parts": details})
    payload = {"scope": "Read-only crop geometry; original CSV native detections with current unchanged global ownership decisions",
               "source": scene["source"], "models_run": False, "ownership_decisions_changed_by_crop": False,
               "old_truncated_accepted_parts": sum(any(p["old"]["edge_trim_px_left_top_right_bottom"]) for r in rows for p in r["accepted_parts"]),
               "adaptive_truncated_accepted_parts": 0, "records": rows}
    (output / "csv_crop_truncation_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def verify_csv_model2(output):
    """Compare one fresh native-image CPU pass to the exact exported raw trace."""
    import torch
    from src.inference.model_registry import ModelRegistry
    from src.inference.yolo_quality_model import YoloQualityModel

    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    scene = csv_scene()
    image = source_image(scene, output)
    if image is None:
        raise ValueError("Original CSV image unavailable: cannot verify fresh predictor output")
    entry = ModelRegistry(ROOT).get_model("yolo26m_partdet")
    checkpoint_hash = sha(ROOT / entry.path)
    model = YoloQualityModel(ROOT / entry.path, model_id=entry.id, device="cpu", image_size=entry.input_size,
                             confidence_threshold=.25, quality_inference_mode="full_frame")
    if not model.load():
        raise RuntimeError(model.error)
    started = perf_counter()
    selected, raw = model._infer_parts(image)
    duration = (perf_counter() - started) * 1000
    predictor = model.adapter.model.predictor
    original = sorted(scene["parts"], key=lambda p: (p["source_class_id"], *p["bbox"]))
    actual = sorted((p.to_dict() for p in selected), key=lambda p: (p["source_class_id"], *p["bbox"]))
    aligned = len(original) == len(actual) and all(a["source_class_id"] == b["source_class_id"] for a, b in zip(original, actual))
    box_error = max((abs(x - y) for a, b in zip(original, actual) for x, y in zip(a["bbox"], b["bbox"])), default=0.) if aligned else None
    confidence_error = max((abs(a["confidence"] - b["confidence"]) for a, b in zip(original, actual)), default=0.) if aligned else None
    payload = {"scope": "One fresh CPU FP32 Model2 pass on original native CSV image; recorded parents remain unchanged",
               "source": scene["source"], "checkpoint_sha256_before": checkpoint_hash,
               "checkpoint_sha256_after": sha(ROOT / entry.path), "input_size": entry.input_size,
               "confidence": .25, "device": "cpu", "original_selected_count": len(original),
               "current_selected_count": len(selected), "current_raw_count": len(raw),
               "exact_raw_identity_sets_equal": {part_key(p) for p in original} == {part_key(p) for p in actual},
               "same_class_sorted_max_coordinate_difference_px": box_error,
               "same_class_sorted_max_confidence_difference": confidence_error,
               "within_one_pixel_and_1e_minus5_confidence": aligned and box_error <= 1 and confidence_error <= 1e-5,
               "actual_predictor_args": {key: getattr(predictor.args, key, None) for key in
                   ("conf", "iou", "imgsz", "rect", "classes", "max_det", "agnostic_nms", "half", "end2end")},
               "actual_letterboxed_shape_hwc": list(predictor.pre_transform([image])[0].shape),
               "native_result_coordinate_extent": [max(p.bbox[2] for p in selected), max(p.bbox[3] for p in selected)],
               "single_pass_model2_ms_excludes_load": duration, "current_parts": actual,
               "cuda_initialized": torch.cuda.is_initialized()}
    if checkpoint_hash != payload["checkpoint_sha256_after"] or payload["cuda_initialized"]:
        raise AssertionError("Read-only predictor verification failed CPU/model-integrity guard")
    (output / "csv_fresh_model2_verification.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_summary(payload, path):
    lines = ["# Fixed-detection association reproduction", "",
             "All numbers below are engineering diagnostics. Expert parent/part ownership labels are absent; correct assignment, false association and correct grading coverage are **not measured**.", "",
             "Raw denotes post-inference candidates at the unchanged operating confidence, after any predictor postprocessing. Frozen detections are identical before and after. No model or calibration thresholds were changed.", "",
             "| Cohort | Scenes | Parents | Raw H/B/T | Assigned before H/B/T | Assigned after H/B/T | Ungraded before/after | Median association ms before/after |",
             "|---|---:|---:|---|---|---|---|---|"]
    for cohort in dict.fromkeys(r["cohort"] for r in payload["records"]):
        rows = [r for r in payload["records"] if r["cohort"] == cohort]
        def counts(side=None):
            counter = Counter()
            for row in rows:
                counter.update(row[side]["assigned_counts"] if side else row["raw_counts"])
            return "/".join(str(counter[region]) for region in ("Head", "Body", "Tail"))
        ug = [sum(r[side]["ungraded_count"] for r in rows) for side in ("before", "after")]
        latency = [median(r[side]["association_latency_ms"]["median"] for r in rows) for side in ("before", "after")]
        lines.append(f"| {cohort} | {len(rows)} | {sum(r['before']['parent_count'] for r in rows)} | {counts()} | {counts('before')} | {counts('after')} | {ug[0]}/{ug[1]} | {latency[0]:.3f}/{latency[1]:.3f} |")
    lines.extend(["", "The original CSV source is `WIN_20260823_20_49_53_Pro.jpg`. Its seven legacy Model1 parents and 22 native Model2 candidates are replayed exactly. The separate 20_47_00 photo from the earlier MobileSAM benchmark is a different stress scene, never substituted for that CSV.", "",
                  "Before/after grades use the same current canonical tail-optional 50/30/20 policy; only association changes. Historical exported grades are separately retained. This is not a full image-analysis latency benchmark: association and deterministic grading are measured separately; detector timings are one-pass provenance, while segmentation, API, UI, model load and GPU are excluded.", "",
                  "The current 17-image project test set is development compatibility data, with known prior training exposure. Its COCO part labels do not provide fish-parent ownership ground truth. Increased graded count alone does not establish improved quality.", "",
                  f"Baseline association SHA256: `{payload['baseline_sha256']}`.",
                  f"After association SHA256: `{payload['current_sha256']}`.", "",
                  "Per-candidate boxes, confidences, candidate parents, scores, rejection reasons, old/new decisions, and every fish's grade/reason/weights are in `association_comparison.json`. Paired real-image overlays are under `visuals/`; these visualize decisions, not expert approval."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--baseline", type=Path, default=OUTPUT / "association.before.py")
    parser.add_argument("--recorded", type=Path, default=ROOT / "results/qa/mobilesam/benchmark.json")
    parser.add_argument("--collect-test-images", action="store_true")
    parser.add_argument("--audit-models", action="store_true", help="Read-only CPU checkpoint names, hashes and installed predictor defaults")
    parser.add_argument("--verify-csv-model2", action="store_true", help="One fresh CPU-only Model2 pass compared with exported native detections")
    parser.add_argument("--audit-csv-crops", action="store_true", help="Read-only old/adaptive crop geometry around already accepted native evidence")
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 50:
        parser.error("repeats must be from 1 to 50")
    args.output.mkdir(parents=True, exist_ok=True)
    frozen = args.output / "current_17_native_detections.json"
    if args.collect_test_images:
        collect_test_images(frozen)
    if args.audit_models:
        audit_postprocessing(args.output)
    if args.verify_csv_model2:
        verify_csv_model2(args.output)
    if args.audit_csv_crops:
        audit_csv_crops(args.output)
    baseline = load_baseline(args.baseline)
    scenes = [csv_scene()]
    if frozen.is_file():
        scenes.extend(json.loads(frozen.read_text(encoding="utf-8"))["records"])
    recorded = json.loads(args.recorded.read_text(encoding="utf-8"))
    for previous in recorded["records"]:
        scenes.append({**previous, "cohort": "recorded_stress_scenes"})
    current_sha = sha(Path(current_association.__file__))
    payload = {"schema": "tamban.fixed-association-repair.v1", "scope": "same selected detections and parent boxes, no segmentation influence",
               "baseline_sha256": sha(args.baseline), "current_sha256": current_sha,
               "grading_policy": load_grading_config().to_policy().to_dict(),
               "correct_assignment_accuracy": None, "false_association_rate": None, "expert_ownership_labels_available": False,
               "recorded_input_sha256": sha(args.recorded), "records": []}
    visuals = args.output / "visuals"
    visuals.mkdir(exist_ok=True)
    for index, scene in enumerate(scenes):
        before = evaluate_scene(scene, baseline, repeats=args.repeats)
        after = evaluate_scene(scene, current_association, repeats=args.repeats)
        row = {"scenario": scene["scenario"], "cohort": scene["cohort"], "source": scene["source"],
               "raw_counts": dict(Counter(p["region"] for p in scene["raw_parts"])),
               "original_export_grades": scene.get("original_export_grades"),
               "detector_ms_original_single_pass": scene.get("detector_ms"), "model2_ms_original_single_pass": scene.get("part_model_ms"),
               "before": before, "after": after, "changes": changes_between(before, after)}
        image = source_image(scene, args.recorded.parent)
        row["original_image_available"] = image is not None
        if image is not None:
            first = draw_decisions(image, scene, before, f"Before: {scene['scenario'][:70]}")
            second = draw_decisions(image, scene, after, f"After: {scene['scenario'][:70]}")
            filename = f"{index:02d}_{scene['scenario']}.png"
            cv2.imwrite(str(visuals / filename), np.hstack((first, second)))
            row["visualization"] = f"visuals/{filename}"
        payload["records"].append(row)
    if sha(Path(current_association.__file__)) != current_sha:
        raise RuntimeError("Association implementation changed during benchmark; rerun after edits finish")
    (args.output / "association_comparison.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_summary(payload, args.output / "association_comparison.md")
    print((args.output / "association_comparison.md").read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
