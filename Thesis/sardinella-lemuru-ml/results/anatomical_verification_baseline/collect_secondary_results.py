"""Run actual local detectors and MobileSAM through the current upload pipeline."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# Set only this audit process; no source/config/environment files are changed.
os.environ["MOBILESAM_DEVICE"] = "cpu"
os.environ["FISH_INFERENCE_FP16"] = "off"
catalog_was_configured = bool(os.environ.pop("FISH_ANATOMICAL_EVIDENCE_PATH", ""))

import cv2
import torch
import ultralytics

from src.api.image_analysis import StillImageAnalyzer
from src.inference.mobilesam_backend import get_mobilesam_service
from src.inference.model_registry import ModelRegistry
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    torch.set_num_threads(1)
    registry = ModelRegistry(ROOT)
    paths = {"model1": registry.resolve_checkpoint_path("fish_parent_detector"),
             "model2": registry.resolve_checkpoint_path("yolo26m_partdet"),
             "mobilesam": ROOT / "models/experimental/mobilesam/mobile_sam.pt"}
    hashes = {name: sha(path) for name, path in paths.items()}
    model1 = YoloFishDetector(paths["model1"], confidence_threshold=.5, device="cpu", image_size=768)
    model2 = YoloQualityModel(paths["model2"], model_id="yolo26m_partdet", confidence_threshold=.25,
                             device="cpu", image_size=768, quality_inference_mode="full_frame")
    assert model1.load(), model1.error
    assert model2.load(), model2.error
    assert model1.fp16 is False and model2.fp16 is False
    baseline = json.loads(Path(__file__).with_name("baseline.json").read_text())
    analyzer = StillImageAnalyzer(model1, model2)
    records = []
    totals = Counter()
    for index, prior in enumerate(baseline["records"], 1):
        path = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test" / prior["scenario"]
        assert sha(path) == prior["source"]["sha256"]
        image = cv2.imread(str(path))
        assert image is not None, path
        start = perf_counter()
        payload = analyzer.analyze(image, frame_id=f"anatomy-secondary-audit:{index}",
                                   segmentation_backend="mobilesam_experimental")
        elapsed_ms = round((perf_counter() - start) * 1000, 3)
        fish_rows = []
        for fish in payload["fish"]:
            analysis = fish["analysis"]
            anatomy = analysis.get("anatomical_verification", {})
            segmentation = analysis.get("segmentation", {})
            ownership = segmentation.get("ownership", {})
            assert anatomy, "Secondary anatomical evidence missing from actual upload payload"
            both = all(anatomy["primary"][region]["detected"] for region in ("Head", "Body"))
            assert (not anatomy["activated"]) if both else anatomy["activated"]
            assert not both or not anatomy.get("geometry"), "Secondary geometry ran with both primary regions detected"
            assert anatomy.get("automatic_rejection") is False, "Unreviewed silhouettes must not authorize rejection"
            assert anatomy["status"] == ("PRESENT" if both else "UNCERTAIN")
            totals["fish"] += 1
            totals["both_primary_detected_skipped"] += int(both)
            totals["secondary_activated"] += int(anatomy["activated"])
            totals["automatic_anatomical_rejections"] += int(anatomy.get("automatic_rejection", False))
            totals["anatomy_" + anatomy["status"]] += 1
            totals["native_mask_geometry_pass"] += int(ownership.get("mask_geometry_checks_passed") is True)
            totals["silhouette_geometry_candidate"] += int(anatomy.get("geometry", {}).get("status") == "candidate")
            totals["overlap_or_ownership_uncertainty"] += int(anatomy["status"] == "UNCERTAIN" and (
                "overlap" in json.dumps(anatomy).lower() or "neighbor" in json.dumps(anatomy).lower()
                or "association_ambiguous" in json.dumps(anatomy).lower()))
            fish_rows.append({"id": fish["id"], "bbox": fish["bbox"], "quality": fish["quality"],
                              "primary_both_detected_secondary_skipped": both,
                              "anatomical_verification": anatomy,
                              "segmentation": {key: segmentation.get(key) for key in (
                                  "backend", "status", "engineering_checks_passed", "validation_status", "used_for_grading",
                                  "mask_score_unvalidated", "checkpoint_sha256", "reasons", "backend_error", "timings")},
                              "mask_geometry": {key: ownership.get(key) for key in (
                                  "mask_geometry_checks_passed", "engineering_checks_passed", "ownership_validated", "reasons", "metrics")}})
        performance = payload.get("performance", {})
        record = {"scenario": prior["scenario"], "source_sha256": sha(path),
                  "shape": list(image.shape), "elapsed_ms": elapsed_ms,
                  "fish_detected": payload["fish_detected"], "quality_counters": payload["quality_counters"],
                  "frame_mask_context": performance.get("mask_context"),
                  "segmentation_ms": performance.get("segmentation_ms"),
                  "model2_inference_ms": performance.get("model2_inference_ms"),
                  "fish": fish_rows}
        records.append(record)
        print(prior["scenario"], "fish", len(fish_rows), "anatomy", dict(Counter(
            row["anatomical_verification"]["status"] for row in fish_rows)), "elapsed_ms", elapsed_ms, flush=True)
    unchanged = hashes == {name: sha(path) for name, path in paths.items()}
    assert unchanged
    service = get_mobilesam_service().status()
    assert service["loaded"] and service["precision"] == "FP32" and service["device"] == "cpu"
    assert service["embedding_count"] == len(records), "Expected one actual MobileSAM embedding per original frame"
    assert not torch.cuda.is_initialized()
    result = {"scope": "Actual current StillImageAnalyzer + Model1 + Model2 + MobileSAM on four original development photos",
              "generated_utc": datetime.now(UTC).isoformat(), "model_sha256": hashes,
              "protected_model_bytes_unchanged": unchanged, "device": "cpu", "precision": "FP32",
              "torch_cpu_threads": 1, "torch": torch.__version__, "ultralytics": ultralytics.__version__,
              "cuda_initialized": torch.cuda.is_initialized(), "review_catalog_configured": False,
              "audit_process_cleared_existing_catalog": catalog_was_configured,
              "configuration_sha256": sha(ROOT / "configs/grading_engine.yaml"),
              "mobilesam_service": service, "counts": dict(totals), "records": records,
              "invariants": {"both_detected_skips_secondary_anatomy": True,
                             "unreviewed_geometry_does_not_reject": True,
                             "one_mobilesam_embedding_per_original_frame": True,
                             "missing_accepted_regions_are_uncertain": True},
              "limitations": ["No independently reviewed physical-absence or fish-ownership labels are supplied.",
                              "These photos have known historical training exposure and do not measure independent anatomy accuracy.",
                              "No real headless/bodyless validation accuracy is claimed.",
                              "Existing shared segmentation runs for pixel diagnostics; the anatomical branch reuses those native candidates.",
                              "Single actual pass per input; timings include first-use effects and are not a repeated speed benchmark."]}
    output = Path(__file__).with_name("secondary_results.json")
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("COUNTS", dict(totals), "REPORT", output, flush=True)


if __name__ == "__main__":
    main()
