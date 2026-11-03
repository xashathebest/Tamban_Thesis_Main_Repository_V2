"""Actual CPU detector/SAM pipeline checks; coverage is not reviewed accuracy."""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from time import perf_counter
from unittest.mock import patch
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "results/qa/runtime_e2e"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_current_source(output=OUTPUT):
    """Snapshot current working files, including the preceding uncommitted fixes."""
    output.mkdir(parents=True, exist_ok=True)
    target = output / "baseline_source.zip"
    if target.exists():
        raise FileExistsError("Refusing to overwrite the end-to-end task baseline")
    manifest = {"construction": "Actual working-file snapshot before this end-to-end task's production edits; includes prior additional.md fixes.",
                "sha256": {}}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in ("src", "frontend", "configs"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file() and path.suffix.lower() in {".py", ".js", ".html", ".css", ".yaml", ".yml", ".json"} and "__pycache__" not in path.parts:
                    name = path.relative_to(ROOT).as_posix()
                    data = path.read_bytes()
                    archive.writestr(name, data)
                    manifest["sha256"][name] = hashlib.sha256(data).hexdigest()
        archive.writestr("baseline_manifest.json", json.dumps(manifest, indent=2))
    (output / "baseline_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"snapshot": str(target), "files": len(manifest["sha256"]), "sha256": sha(target)}


def activate_source(output, phase):
    if phase == "before":
        source = output / "baseline_workspace"
        if not source.exists():
            source.mkdir()
            with zipfile.ZipFile(output / "baseline_source.zip") as archive:
                archive.extractall(source)
    else:
        source = ROOT
    # This orchestrator is already __main__; every runtime import below must
    # come from the chosen frozen/current package, rather than a mixed snapshot.
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]
    sys.path.insert(0, str(source))
    return source


def build_scenes(output, all_test_images=False):
    """Use real pixels; each derived input records its exact construction."""
    stress = json.loads((ROOT / "results/qa/mobilesam/benchmark.json").read_text(encoding="utf-8"))
    records = {r["scenario"]: r for r in stress["records"]}
    scenes = []
    original = Path("C:/Users/User/Downloads/Class B/WIN_20260823_20_49_53_Pro.jpg")
    if not original.is_file():
        raise FileNotFoundError("The exact historical CSV source is required for this run")
    source = cv2.imread(str(original))
    scenes.append(("original_csv_photo_current_model1", source, {"path": str(original), "sha256": sha(original),
                   "operation": "original native image; current Model1 V2 parents, not historical seven parents", "tags": ["native_original", "multiple_fish"]}))
    for name in ("natural_severe_overlap", "natural_touching_pair", "natural_damaged", "clipped_fish", "isolated_clean"):
        path = ROOT / f"results/qa/mobilesam/{name}.source.png"
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Recorded exact real-image stress pixels unavailable: {path}")
        provenance = deepcopy(records[name]["source"])
        if list(image.shape[:2]) != provenance["benchmark_shape"]:
            raise ValueError(f"Recorded source shape changed: {name}")
        provenance.update(derived_source_path=str(path), derived_source_sha256=sha(path), tags=provenance.pop("scenario_tags", []))
        scenes.append((name, image, provenance))
    isolated = scenes[-1][1]
    matrix = cv2.getRotationMatrix2D((isolated.shape[1] / 2, isolated.shape[0] / 2), 25, 1.)
    corners = cv2.transform(np.array([[[0., 0.], [isolated.shape[1], 0.], [0., isolated.shape[0]],
                                     [isolated.shape[1], isolated.shape[0]]]], np.float32), matrix)[0]
    low, high = np.floor(corners.min(axis=0)), np.ceil(corners.max(axis=0))
    matrix[:, 2] -= low
    rotated = cv2.warpAffine(isolated, matrix, tuple((high - low).astype(int)), borderValue=(30, 30, 30))
    scenes.append(("isolated_rotated_25deg", rotated, {**deepcopy(scenes[-1][2]),
                   "operation": "25 degree rotation of recorded isolated_clean pixels, enclosing canvas without new clipping",
                   "tags": ["isolated_fish", "controlled_rotation"], "affine_matrix": matrix.tolist()}))
    if all_test_images:
        for path in sorted((ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test").glob("*.jpg")):
            scenes.append(("test_" + path.stem, cv2.imread(str(path)), {"path": str(path), "sha256": sha(path),
                           "operation": "original project test pixels", "tags": ["project_test_set", "known_training_exposure_not_independent"]}))
    manifest = []
    (output / "sources").mkdir(exist_ok=True)
    for name, image, provenance in scenes:
        if image is None:
            raise ValueError(name)
        path = output / "sources" / f"{name}.png"
        cv2.imwrite(str(path), image)
        manifest.append({"scenario": name, "source": provenance, "shape": list(image.shape),
                         "pixel_sha256": hashlib.sha256(memoryview(np.ascontiguousarray(image))).hexdigest(),
                         "frozen_pixels": str(path.relative_to(output))})
    (output / "scenes.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def part_key(part):
    return (part["source_class_id"], tuple(part["bbox"]), part["confidence"])


def audit_payload(payload, frozen):
    """Check engineering invariants, never infer physical ownership labels."""
    violations, accepted, ug = [], Counter(), []
    height, width = frozen["shape"][:2]
    original = {part_key(p): p for p in frozen["raw_parts"]}
    selected = {part_key(p): p for p in frozen["parts"]}
    for fish in payload["fish"]:
        analysis = fish["analysis"]
        association = analysis.get("quality_inference", {}).get("association", {})
        debug = analysis.get("model2_debug", {})
        own = [r for r in association.get("parts", []) if r.get("status") == "ASSIGNED" and r.get("track_id") == fish["id"]]
        if len(own) != len({r["part"]["region"] for r in own}):
            violations.append({"fish_id": fish["id"], "code": "duplicate_region_assignment"})
        for row in own:
            accepted[row["part"]["region"]] += 1
            if part_key(row["part"]) not in selected:
                violations.append({"fish_id": fish["id"], "code": "assigned_part_not_in_detector_selected"})
            exposed = [p for p in fish.get("parts", []) if p["source_class_id"] == row["part"]["source_class_id"]]
            if len(exposed) != 1 or not np.allclose(exposed[0]["bbox"], row["part"]["bbox"], atol=.011, rtol=0):
                violations.append({"fish_id": fish["id"], "code": "accepted_native_box_changed_by_crop_or_serialization", "native": row["part"]["bbox"], "exposed": exposed})
        if {part_key(p) for p in debug.get("raw_detections", [])} != set(original):
            violations.append({"fish_id": fish["id"], "code": "native_raw_trace_lost_or_changed"})
        for p in fish.get("parts", []):
            x1, y1, x2, y2 = p["bbox"]
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                violations.append({"fish_id": fish["id"], "code": "part_outside_native_source"})
        if analysis.get("body_width", {}).get("score_contributed"):
            violations.append({"fish_id": fish["id"], "code": "unexpected_uncalibrated_width_contribution"})
        fusion = analysis.get("feature_fusion", {})
        if fusion.get("contributions_applied"):
            violations.append({"fish_id": fish["id"], "code": "unexpected_unreviewed_feature_contribution"})
        if fusion.get("original_grade") != fusion.get("final_grade"):
            violations.append({"fish_id": fish["id"], "code": "unreviewed_geometry_changed_grade"})
        segmentation = analysis.get("segmentation", {})
        ownership = segmentation.get("ownership", {})
        if segmentation.get("used_for_grading") or ownership.get("approved_for_grading") or ownership.get("ownership_validated"):
            violations.append({"fish_id": fish["id"], "code": "automatic_mask_claimed_independent_validation"})
        expected_frame = payload.get("inspection_source", {}).get("frame_id")
        if segmentation.get("frame_id") != expected_frame:
            violations.append({"fish_id": fish["id"], "code": "mask_frame_identity_mismatch"})
        if fish.get("quality") == "Ungraded":
            required = {"Head", "Body"}
            observed = {r["part"]["region"] for r in own}
            ug.append({"fish_id": fish["id"], "accepted_regions": sorted(observed), "missing_required": sorted(required - observed),
                       "reason_codes": analysis.get("reason_codes", []),
                       "required_candidate_decisions": [r for r in association.get("parts", []) if r["part"]["region"] in required and r["status"] != "ASSIGNED"],
                       "mask_reasons": segmentation.get("reasons", []), "mask_geometry_checks_passed": ownership.get("mask_geometry_checks_passed"),
                       "mask_ownership_checks_passed": ownership.get("engineering_checks_passed")})
    return {"violations": violations, "raw_counts": dict(Counter(p["region"] for p in frozen["raw_parts"])),
            "selected_counts": dict(Counter(p["region"] for p in frozen["parts"])), "accepted_counts": dict(accepted),
            "fish_count": len(payload["fish"]), "grade_counts": dict(Counter(f["quality"] for f in payload["fish"])),
            "ungraded": ug, "grading_accuracy": None, "false_association_rate": None,
            "independent_ground_truth_available": False}


def verify_graded_arithmetic(payload):
    """Policy arithmetic compliance is distinct from expert grading accuracy."""
    violations, checked = [], 0
    for fish in payload["fish"]:
        if fish["quality"] == "Ungraded": continue
        checked += 1
        analysis = fish["analysis"]
        rows = analysis.get("quality_inference", {}).get("association", {}).get("parts", [])
        own = [r["part"] for r in rows if r["status"] == "ASSIGNED" and r.get("track_id") == fish["id"]]
        observed = {p["region"] for p in own}
        weights = {"Head": .3, "Body": .5, "Tail": .2} if "Tail" in observed else {"Head": .375, "Body": .625, "Tail": 0.}
        if not {"Head", "Body"}.issubset(observed):
            violations.append({"fish_id": fish["id"], "code": "graded_without_required_regions"})
        if any(not np.isclose(analysis.get("effective_weights", {}).get(region, np.nan), value, atol=1e-10, rtol=0) for region, value in weights.items()):
            violations.append({"fish_id": fish["id"], "code": "incorrect_50_30_20_or_optional_tail_weights"})
        expected = {grade: sum(weights[p["region"]] * p["confidence"] for p in own if p["grade"] == grade)
                    for grade in ("Class A", "Class B", "Class C", "Rejected")}
        if any(not np.isclose(analysis.get("weighted_scores", {}).get(grade, np.nan), support, atol=1e-10, rtol=0) for grade, support in expected.items()):
            violations.append({"fish_id": fish["id"], "code": "weighted_support_does_not_match_owned_raw_confidences"})
        if not np.isclose(fish.get("quality_confidence", np.nan), expected[fish["quality"]], atol=1e-10, rtol=0):
            violations.append({"fish_id": fish["id"], "code": "final_support_does_not_match_weighted_support"})
    return {"graded_verdicts_checked": checked, "violations": violations,
            "scope": "Deterministic grading arithmetic, not expert-reference grading accuracy"}


class FrozenSamSession:
    """Exact source-bound cached neural outputs; runtime validation still runs."""
    def __init__(self, service, image, frame_key):
        self.service, self.frame_key = service, frame_key
        digest = hashlib.sha256(memoryview(np.ascontiguousarray(image))).hexdigest()
        if digest != service.frozen["pixel_sha256"]:
            raise ValueError("Frozen SAM replay refuses different pixels")
        self.requests = 0

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def predict(self, parent_id, bbox_global, **kwargs):
        saved = self.service.frozen["candidates"][str(parent_id)]
        expected = saved.get("provenance", {}).get("original_bbox_global")
        if expected is not None and not np.allclose(expected, bbox_global, rtol=0, atol=.000001):
            raise ValueError("Frozen SAM replay refuses changed parent prompts")
        if saved.get("provenance", {}).get("frame_key") != self.frame_key:
            raise ValueError("Frozen SAM replay refuses changed frame identity")
        recorded = saved.get("reviewed_point_prompts", {})
        for name in ("point_coords", "point_labels"):
            supplied = kwargs.get(name)
            supplied = [] if supplied is None else np.asarray(supplied).tolist()
            if supplied != recorded.get(name, []):
                raise ValueError("Frozen SAM replay refuses changed anatomical point prompts")
        self.requests += 1
        row = deepcopy(saved)
        row["mask"] = self.service.masks.get(str(parent_id))
        row.update(embedding_ms=0., prompt_ms=0., cache_hit=True, frozen_neural_replay=True)
        return row

    def diagnostics(self):
        return {"backend": "mobilesam_experimental", "embedding_calls": 0, "actual_encoder_forward_calls": 0,
                "embedding_ms": 0., "prompt_ms": 0., "prompt_calls": 0, "prompt_cache_hits": self.requests,
                "frame_key": self.frame_key, "scope": "Exact frozen neural outputs; not fresh inference latency", "device": "cpu"}


class FrozenSamService:
    def __init__(self, frozen, masks):
        from src.inference.mobilesam_backend import MobileSamSettings
        self.frozen, self.masks = frozen, masks
        self.settings = MobileSamSettings.from_environment()
    def open_frame(self, image, frame_key): return FrozenSamSession(self, image, frame_key)
    def status(self): return {"loaded": True, "device": "cpu", "scope": "frozen_candidate_replay"}


def runtime_models(actual):
    from src.inference import model_registry
    from src.inference.model_registry import ModelRegistry
    from src.inference.yolo_fish_detector import YoloFishDetector
    from src.inference.yolo_quality_model import YoloQualityModel
    registry = ModelRegistry(ROOT)
    model_registry._REGISTRY_INSTANCE = registry
    first = registry.get_model(registry.get_default_model1_id())
    second = registry.get_model("yolo26m_partdet")
    detector = YoloFishDetector(ROOT / first.path, device="cpu", image_size=first.input_size,
                               confidence_threshold=.5, iou_threshold=.7, max_detections=132)
    quality = YoloQualityModel(ROOT / second.path, device="cpu", model_id=second.id,
                              image_size=second.input_size, confidence_threshold=.25, quality_inference_mode="full_frame")
    if actual:
        if not detector.load() or not quality.load():
            raise RuntimeError(f"Protected CPU model load failed: {detector.error}; {quality.error}")
    else:
        detector.model = quality.model = object()
    return detector, quality, {"model1": ROOT / first.path, "model2": ROOT / second.path,
                               "mobilesam": ROOT / "models/experimental/mobilesam/mobile_sam.pt"}


def serialize_candidates(candidates, directory):
    metadata, masks = {}, {}
    for identity, row in candidates.items():
        metadata[str(identity)] = {k: deepcopy(v) for k, v in row.items() if k != "mask"}
        if isinstance(row.get("mask"), np.ndarray): masks[str(identity)] = row["mask"]
    np.savez_compressed(directory / "masks.npz", **masks)
    return metadata


def run_phase(output, phase, all_test_images=False):
    if phase == "before" and (output / "before.json").exists():
        raise FileExistsError("Refusing to overwrite captured before results; choose a new output directory")
    os.environ.update(CUDA_VISIBLE_DEVICES="", MOBILESAM_DEVICE="cpu", FISH_INFERENCE_FP16="off",
                      MOBILESAM_CHECKPOINT=str(ROOT / "models/experimental/mobilesam/mobile_sam.pt"))
    source = activate_source(output, phase)
    import torch
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    from src.api.image_analysis import StillImageAnalyzer
    from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
    from src.inference import mobilesam_backend
    from src.inference.part_types import PartDetection
    from src.inference.yolo_fish_detector import FishDetection
    manifest = build_scenes(output, all_test_images) if phase == "before" else json.loads((output / "scenes.json").read_text(encoding="utf-8"))
    detector, quality, paths = runtime_models(actual=phase == "before")
    hashes = {k: sha(path) for k, path in paths.items()}
    if phase == "after" and hashes != json.loads((output / "before.json").read_text(encoding="utf-8"))["checkpoint_sha256"]:
        raise AssertionError("Frozen replay refuses changed checkpoint identities")
    analyzer = StillImageAnalyzer(detector, quality)
    records = []
    for scene in manifest:
        name = scene["scenario"]
        directory = output / phase / name
        directory.mkdir(parents=True, exist_ok=True)
        image = cv2.imread(str(output / scene["frozen_pixels"]))
        frame_id = "runtime-e2e:" + name
        captured, counts = {}, {"model1_calls": 0, "model2_calls": 0, "grabcut_calls": 0}
        before_service = mobilesam_backend._SERVICE
        if phase == "after":
            frozen = json.loads((output / "before" / name / "frozen.json").read_text(encoding="utf-8"))
            with np.load(output / "before" / name / "masks.npz") as saved:
                masks = {key: saved[key].copy() for key in saved.files}
            mobilesam_backend._SERVICE = FrozenSamService(frozen, masks)
            def detect(frame):
                counts["model1_calls"] += 1
                return [FishDetection(tuple(d["bbox"]), d["confidence"]) for d in frozen["detections"]]
            def infer(frame):
                counts["model2_calls"] += 1
                def restore(rows): return [PartDetection.from_source_class(p["source_class_id"], p["confidence"], tuple(p["bbox"]), p.get("mask")) for p in rows]
                return restore(frozen["parts"]), restore(frozen["raw_parts"])
        else:
            detect_original, infer_original = detector.detect, quality._infer_parts
            def detect(frame):
                counts["model1_calls"] += 1
                result = detect_original(frame)
                captured["detections"] = [{"bbox": list(d.bbox), "confidence": d.confidence} for d in result]
                return result
            def infer(frame):
                counts["model2_calls"] += 1
                selected, raw = infer_original(frame)
                captured.update(parts=[p.to_dict() for p in selected], raw_parts=[p.to_dict() for p in raw])
                return selected, raw
        prepare_original = ExperimentalFrameSegmentation.prepare
        def prepare(provider, *args, **kwargs):
            result = prepare_original(provider, *args, **kwargs)
            captured["candidates"] = provider.candidates
            captured["provider_diagnostics"] = provider.diagnostics()
            return result
        def grabcut(*args, **kwargs):
            counts["grabcut_calls"] += 1
            raise RuntimeError("Unexpected duplicate GrabCut in MobileSAM validation")
        with ExitStack() as stack:
            stack.enter_context(patch.object(detector, "detect", detect))
            stack.enter_context(patch.object(quality, "_infer_parts", infer))
            stack.enter_context(patch.object(ExperimentalFrameSegmentation, "prepare", prepare))
            stack.enter_context(patch.object(cv2, "grabCut", grabcut))
            started = perf_counter()
            payload = analyzer.analyze(image, frame_id=frame_id, source_type="uploaded_photo", segmentation_backend="mobilesam_experimental")
            elapsed_ms = (perf_counter() - started) * 1000
        if phase == "before":
            frozen = {**scene, "frame_id": frame_id, "detections": captured.get("detections", []),
                      "parts": captured.get("parts", []), "raw_parts": captured.get("raw_parts", []),
                      "candidates": serialize_candidates(captured.get("candidates", {}), directory),
                      "provider_diagnostics": captured.get("provider_diagnostics", {})}
            (directory / "frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
        audit = audit_payload(payload, frozen)
        expected_calls = {"model1_calls": 1, "model2_calls": 1 if payload["fish"] else 0, "grabcut_calls": 0}
        if counts != expected_calls:
            audit["violations"].append({"code": "unexpected_model_or_grabcut_call_count", "actual": counts, "expected": expected_calls})
        diagnostics = captured.get("provider_diagnostics", {})
        expected_embeddings = 1 if payload["fish"] and phase == "before" else 0
        if diagnostics.get("embedding_calls", 0) != expected_embeddings:
            audit["violations"].append({"code": "unexpected_embedding_count", "actual": diagnostics.get("embedding_calls"), "expected": expected_embeddings})
        record = {"scenario": name, "source": scene["source"], "phase": phase,
                  "input_pixel_sha256": scene["pixel_sha256"], "audit": audit, "model_wrapper_calls": counts,
                  "actual_neural_calls": counts if phase == "before" else {"model1_calls": 0, "model2_calls": 0, "grabcut_calls": 0},
                  "actual_sam_encoder_calls": diagnostics.get("actual_encoder_forward_calls", diagnostics.get("embedding_calls")),
                  "elapsed_ms": elapsed_ms, "timing_scope": "Actual CPU analysis inclSAMfirstload, annotation/previewencoding; excludes decode/network/model1+2load" if phase == "before" else "Frozen neural outputs through current software; not new NN inference latency",
                  "performance": payload.get("performance", {}), "segmentation_diagnostics": diagnostics}
        (directory / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (directory / "audit.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        records.append(record)
        mobilesam_backend._SERVICE = before_service if phase == "after" else mobilesam_backend._SERVICE
        print(f"{phase}: {name}: fish={audit['fish_count']} raw={audit['raw_counts']} accepted={audit['accepted_counts']} grades={audit['grade_counts']} violations={len(audit['violations'])} {elapsed_ms:.1f}ms", flush=True)
        (output / f"{phase}.json").write_text(json.dumps({"phase": phase, "source_workspace": str(source), "checkpoint_sha256": hashes,
            "checkpoint_sha256_after": {k: sha(path) for k, path in paths.items()}, "cuda_initialized": torch.cuda.is_initialized(), "records": records}, indent=2), encoding="utf-8")
    if torch.cuda.is_initialized() or hashes != {k: sha(path) for k, path in paths.items()}:
        raise AssertionError("CPU/checkpoint integrity guard failed")
    return records


def summarize_phase(output, phase):
    payload = json.loads((output / f"{phase}.json").read_text(encoding="utf-8"))
    groups = {"representative_cases": [], "project_17_test_images": []}
    for record in payload["records"]:
        groups["project_17_test_images" if record["scenario"].startswith("test_") else "representative_cases"].append(record)
    summary = {"phase": phase, "accuracy": None, "independent_expert_parent_and_grade_labels": False,
               "cohorts_overlap_do_not_aggregate_accuracy": True, "groups": {}}
    details = []
    for group, records in groups.items():
        raw, accepted, grades, primary, all_reasons, missing, gates, mask_reasons, mask_status = (Counter() for _ in range(9))
        complete_ug, violations = 0, []
        for record in records:
            raw.update(record["audit"]["raw_counts"])
            accepted.update(record["audit"]["accepted_counts"])
            grades.update(record["audit"]["grade_counts"])
            violations.extend(record["audit"]["violations"])
            scene = json.loads((output / phase / record["scenario"] / "payload.json").read_text(encoding="utf-8"))
            frozen = json.loads((output / "before" / record["scenario"] / "frozen.json").read_text(encoding="utf-8"))
            for fish in scene["fish"]:
                analysis = fish["analysis"]
                seg = analysis.get("segmentation", {})
                ownership = seg.get("ownership", {})
                mask_status["engineering_passed_unvalidated" if ownership.get("engineering_checks_passed") else "engineering_withheld"] += 1
                mask_status["geometry_checks_passed"] += int(ownership.get("mask_geometry_checks_passed") is True)
                mask_reasons.update(ownership.get("reasons", []))
                if fish["quality"] != "Ungraded": continue
                reasons = analysis.get("reason_codes", [])
                primary[analysis.get("verdict_reason_code") or (reasons[0] if reasons else "not_recorded")] += 1
                all_reasons.update(reasons)
                assoc = analysis.get("quality_inference", {}).get("association", {})
                own = [r for r in assoc.get("parts", []) if r.get("status") == "ASSIGNED" and r.get("track_id") == fish["id"]]
                observed = {r["part"]["region"] for r in own}
                missing_regions = {"Head", "Body"} - observed
                complete_ug += int(not missing_regions)
                for region in missing_regions:
                    missing[region] += 1
                    candidates = []
                    for decision in assoc.get("parts", []):
                        if decision["part"]["region"] != region: continue
                        for candidate in decision.get("candidates", []):
                            if candidate.get("track_id") == fish["id"]:
                                candidates.append((candidate, decision))
                    best = max(candidates, key=lambda row: row[0].get("score", 0), default=None)
                    if not any(p["region"] == region for p in frozen["parts"]):
                        gate = "no_detector_candidate_in_scene"
                    elif best is None:
                        gate = "no_candidate_decision_recorded_for_parent"
                    elif best[0].get("part_inside_fraction") == 0:
                        gate = "no_candidate_intersects_parent"
                    elif best[0].get("failed_checks"):
                        gate = "+".join(sorted(best[0]["failed_checks"]))
                    else:
                        gate = best[1].get("reason") or "candidate_owned_by_other_parent"
                    gates[f"{region}:{gate}"] += 1
                    details.append({"scenario": record["scenario"], "fish_id": fish["id"], "missing_required_region": region,
                                    "gate": gate, "best_candidate": best[0] if best else None,
                                    "best_decision": best[1] if best else None, "grade_reasons": reasons,
                                    "independently_reviewed_physical_absence": False})
        times = [r["elapsed_ms"] for r in records]
        summary["groups"][group] = {"scenes": len(records), "fish": sum(r["audit"]["fish_count"] for r in records),
            "raw_counts": dict(raw), "accepted_counts": dict(accepted), "grades": dict(grades),
            "ungraded_primary_reason_codes": dict(primary), "ungraded_all_reason_codes": dict(all_reasons),
            "missing_required_regions_among_UG": dict(missing), "complete_required_but_UG": complete_ug,
            "required_part_bottlenecks": dict(gates), "mask_status": dict(mask_status), "mask_reasons": dict(mask_reasons),
            "audit_violations": violations, "median_elapsed_ms": float(np.median(times)) if times else None,
            "p95_elapsed_ms": float(np.percentile(times, 95)) if times else None}
    summary["per_required_part_failures"] = details
    (output / f"{phase}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_required_part_failures"}, indent=2), flush=True)
    return summary


def write_comparison(output):
    before = json.loads((output / "before.json").read_text(encoding="utf-8"))
    after = json.loads((output / "after.json").read_text(encoding="utf-8"))
    old = {r["scenario"]: r for r in before["records"]}
    result = {"scope": "Same exact detector outputs and native SAM arrays through frozen baseline versus current software",
              "grading_accuracy": None, "independent_expert_labels_available": False,
              "raw_definition": "Production post-confidence/post-NMS candidates, not pre-NMS logits",
              "fresh_neural_runs_before": len(before["records"]), "fresh_neural_runs_paired_after": 0,
              "checkpoints_unchanged": before["checkpoint_sha256"] == before["checkpoint_sha256_after"] == after["checkpoint_sha256"] == after["checkpoint_sha256_after"],
              "cuda_initialized": before["cuda_initialized"] or after["cuda_initialized"], "records": []}
    (output / "visuals").mkdir(exist_ok=True)
    for row in after["records"]:
        name = row["scenario"]
        if old[name]["input_pixel_sha256"] != row["input_pixel_sha256"]:
            raise AssertionError("Paired comparison source mismatch")
        payloads = [json.loads((output / phase / name / "payload.json").read_text(encoding="utf-8")) for phase in ("before", "after")]
        def signatures(payload):
            return [{"id": f["id"], "bbox": f["bbox"], "quality": f["quality"], "support": f["quality_confidence"],
                     "weighted_scores": f["analysis"]["weighted_scores"], "effective_weights": f["analysis"]["effective_weights"],
                     "parts": f["parts"]} for f in payload["fish"]]
        arithmetic = [verify_graded_arithmetic(p) for p in payloads]
        masks_changed = []
        for first, second in zip(payloads[0]["fish"], payloads[1]["fish"]):
            old_seg, new_seg = first["analysis"].get("segmentation", {}), second["analysis"].get("segmentation", {})
            if (old_seg.get("reasons"), old_seg.get("ownership_status")) != (new_seg.get("reasons"), new_seg.get("ownership_status")):
                masks_changed.append({"fish_id": first["id"], "before": {"reasons": old_seg.get("reasons"), "ownership_status": old_seg.get("ownership_status")},
                                      "after": {"reasons": new_seg.get("reasons"), "ownership_status": new_seg.get("ownership_status")}})
        for phase, payload in zip(("before", "after"), payloads):
            encoded = payload.get("annotated_image", "")
            if encoded.startswith("data:image/jpeg;base64,"):
                (output / "visuals" / f"{name}.{phase}.jpg").write_bytes(base64.b64decode(encoded.split(",", 1)[1]))
        result["records"].append({"scenario": name, "source_sha256_same": True,
            "raw_counts_before": old[name]["audit"]["raw_counts"], "raw_counts_after": row["audit"]["raw_counts"],
            "accepted_before": old[name]["audit"]["accepted_counts"], "accepted_after": row["audit"]["accepted_counts"],
            "grades_before": old[name]["audit"]["grade_counts"], "grades_after": row["audit"]["grade_counts"],
            "weighted_grading_and_native_parts_identical": signatures(payloads[0]) == signatures(payloads[1]),
            "arithmetic_before": arithmetic[0], "arithmetic_after": arithmetic[1], "mask_diagnostic_changes": masks_changed,
            "violations_before": old[name]["audit"]["violations"], "violations_after": row["audit"]["violations"],
            "actual_CPU_pipeline_before_ms": old[name]["elapsed_ms"], "software_replay_after_ms_excludes_neural_inference": row["elapsed_ms"],
            "latency_not_paired_end_to_end_speed_measurement": True})
    protected = {"src/inference/model_adapters.py": "predict", "src/inference/yolo_fish_detector.py": "_detect",
                 "src/inference/yolo_quality_model.py": "_infer_parts"}
    result["protected_predictor_AST_unchanged"] = {}
    with zipfile.ZipFile(output / "baseline_source.zip") as archive:
        for filename, function in protected.items():
            def methods(source):
                tree = ast.parse(source)
                return [ast.dump(node, include_attributes=False) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function]
            result["protected_predictor_AST_unchanged"][filename + ":" + function] = methods(archive.read(filename).decode("utf-8-sig")) == methods((ROOT / filename).read_text(encoding="utf-8-sig"))
        manifest = json.loads(archive.read("baseline_manifest.json"))
        result["current_source_changes_since_runtime_baseline"] = [
            {"file": name, "baseline_sha256": expected,
             "current_sha256": sha(ROOT / name) if (ROOT / name).is_file() else None}
            for name, expected in manifest["sha256"].items()
            if not (ROOT / name).is_file() or sha(ROOT / name) != expected]
    (output / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, indent=2), flush=True)
    return result


def compare_legacy_csv(output):
    from src.evaluation.evaluate_association_repairs import csv_scene, evaluate_scene, load_baseline
    from src.inference import association
    scene = csv_scene()
    previous = load_baseline(output / "baseline_workspace/src/inference/association.py")
    report = {"scope": "Exact seven historical Model1 boxes and 22 recorded Model2 candidates; no new neural inference",
              "source": scene["source"], "historical_export_grades": scene["original_export_grades"],
              "before": evaluate_scene(scene, previous, repeats=3), "after": evaluate_scene(scene, association, repeats=3),
              "grading_accuracy": None, "independent_expert_labels_available": False}
    (output / "legacy_csv_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({side: {k: report[side][k] for k in ("assigned_counts", "ungraded_count", "parent_count")}
                      for side in ("before", "after")}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--phase", choices=("before", "after"))
    parser.add_argument("--all-test-images", action="store_true")
    parser.add_argument("--summarize", choices=("before", "after"))
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--legacy-csv", action="store_true")
    args = parser.parse_args()
    if args.snapshot_only:
        print(json.dumps(snapshot_current_source(args.output)), flush=True)
    elif args.phase:
        run_phase(args.output, args.phase, args.all_test_images)
        summarize_phase(args.output, args.phase)
    elif args.summarize:
        summarize_phase(args.output, args.summarize)
    elif args.compare:
        write_comparison(args.output)
    elif args.legacy_csv:
        compare_legacy_csv(args.output)


if __name__ == "__main__":
    main()
