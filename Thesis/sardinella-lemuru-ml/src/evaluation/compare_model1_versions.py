"""Compare whole-fish checkpoints on identical data, with graphs and paired uncertainty.

Run with --help for explicit checkpoint and dataset inputs. This command never
changes the application registry or promotes a checkpoint. Cached evaluations
are bound to checkpoint, image/label content, software, and inference settings.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


LIMITATION = (
    "Internal development comparison, not an independent thesis test. V3 validation "
    "influenced checkpoint selection; v2 training exposure and specimen independence "
    "are unknown. Images from one capture date can be correlated. Image-bootstrap "
    "intervals describe this set and do not establish population significance. The "
    "legacy test set is a regression check and has already been evaluated previously."
)
METRIC_NAMES = {
    "precision": "Precision", "recall": "Recall", "f1": "F1",
    "exact_count_accuracy": "Exact count accuracy", "map50": "mAP@50",
    "map50_95": "mAP@50–95",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dataset_signature(data: Path, split: str) -> dict:
    import yaml
    config = yaml.safe_load(data.read_text(encoding="utf-8"))
    if config.get("names") not in ({0: "Fish"}, {"0": "Fish"}, ["Fish"]):
        raise ValueError("Comparison requires the single Fish class, without relabelling.")
    root = Path(config.get("path", data.parent))
    if not root.is_absolute():
        root = (data.parent / root).resolve()
    folder = root / config[split]
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
    if not images:
        raise ValueError(f"No evaluation images: {folder}")
    records = []
    for image in images:
        label = root / "labels" / Path(config[split]).name / f"{image.stem}.txt"
        if not label.is_file():
            raise ValueError(f"Missing ground truth: {label}")
        records.append({"file": image.name, "image_sha256": sha256(image), "label_sha256": sha256(label)})
    fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    return {"yaml": str(data.resolve()), "split": split, "images": len(images),
            "fingerprint": fingerprint, "files": records}


def match_counts(boxes, scores, targets, threshold: float, iou: float = .5) -> tuple[int, int, int]:
    """Match predictions by descending confidence to one unused target at a time."""
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
    targets = np.asarray(targets, dtype=float).reshape(-1, 4)
    scores = np.asarray(scores, dtype=float)
    selected = np.flatnonzero(scores >= threshold)
    selected = selected[np.argsort(-scores[selected], kind="stable")]
    used: set[int] = set()
    for index in selected:
        if len(used) == len(targets):
            break
        box = boxes[index]
        intersection = np.maximum(0, np.minimum(box[2:], targets[:, 2:]) - np.maximum(box[:2], targets[:, :2])).prod(axis=1)
        union = np.maximum(0, box[2:] - box[:2]).prod() + np.maximum(0, targets[:, 2:] - targets[:, :2]).prod(axis=1) - intersection
        overlap = np.divide(intersection, union, out=np.zeros_like(union), where=union > 0)
        if used:
            overlap[list(used)] = -1
        target = int(np.argmax(overlap))
        if overlap[target] >= iou:
            used.add(target)
    return len(used), len(selected) - len(used), len(targets) - len(used)


def count_metrics(counts: np.ndarray) -> dict:
    counts = np.asarray(counts)
    tp, fp, fn = counts.sum(axis=0).tolist()
    precision = tp / (tp + fp) if tp + fp else 0.
    recall = tp / (tp + fn) if tp + fn else 0.
    return {"tp": int(tp), "fp": int(fp), "fn": int(fn), "precision": precision,
            "recall": recall, "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
            "exact_count_accuracy": float(np.mean(counts[:, 1] == counts[:, 2])),
            "count_mae": float(np.mean(np.abs(counts[:, 1] - counts[:, 2]))),
            "perfect_detection_image_rate": float(np.mean((counts[:, 1] == 0) & (counts[:, 2] == 0)))}


def capture_date(filename: str) -> str:
    match = re.search(r"(?:WIN_)?(20\d{6})", filename)
    return match.group(1) if match else "unknown"


def evaluate(checkpoint: Path, signature: dict, output: Path, device: str) -> dict:
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect.val import DetectionValidator
    from ultralytics.utils import ops

    settings = {"imgsz": 768, "batch": 1, "conf": .001, "iou": .70,
                "max_det": 132, "half": False, "rect": True, "device": device}
    provenance = {"checkpoint_sha256": sha256(checkpoint), "dataset_fingerprint": signature["fingerprint"],
                  "settings": settings, "ultralytics": ultralytics.__version__, "torch": torch.__version__}
    cached = None
    if output.is_file():
        cached = json.loads(output.read_text(encoding="utf-8"))
        if cached.get("provenance") == provenance:
            if "runtime_settings" in cached:
                print(f"Using verified cache: {output}", flush=True)
                return cached
        else:
            raise ValueError(f"Evaluation cache differs from these inputs; use a new output directory: {output}")
    records = []

    class RecordingValidator(DetectionValidator):
        def update_metrics(self, preds, batch):
            super().update_metrics(preds, batch)
            for index, pred in enumerate(preds):
                prepared = self._prepare_batch(index, batch)
                scaled = self.scale_preds(pred, prepared)
                targets = ops.scale_boxes(prepared["imgsz"], prepared["bboxes"].clone(),
                                          prepared["ori_shape"], prepared["ratio_pad"])
                records.append({"file": Path(prepared["im_file"]).name,
                                "boxes": scaled["bboxes"].cpu().tolist(),
                                "scores": scaled["conf"].cpu().tolist(),
                                "targets": targets.cpu().tolist()})

    if cached is None:
        print(f"Evaluating native AP for {checkpoint.name}: {signature['images']} {signature['split']} images", flush=True)
        model = YOLO(str(checkpoint))
        if model.task != "detect" or model.names != {0: "Fish"}:
            raise ValueError("Checkpoint must be a single-class whole-fish detection model.")
        metrics = model.val(validator=RecordingValidator, data=signature["yaml"], split=signature["split"],
                            workers=0, plots=False, verbose=False, project=str(output.parent),
                            name=output.stem + "_native", exist_ok=True, **settings)
        if len(records) != signature["images"] or {r["file"] for r in records} != {r["file"] for r in signature["files"]}:
            raise ValueError("Native validation did not evaluate the exact requested images.")
        payload = {"checkpoint": str(checkpoint.resolve()), "provenance": provenance,
                   "map50": float(metrics.box.map50), "map50_95": float(metrics.box.map),
                   "native_best_f1_precision": float(metrics.box.mp), "native_best_f1_recall": float(metrics.box.mr),
                   "speed_ms": {k: float(v) for k, v in metrics.speed.items()},
                   "native_records": sorted(records, key=lambda r: r["file"])}
        del model
    else:
        payload = cached
        payload["native_records"] = payload.pop("records")
    # Native validation pads images differently from single-frame prediction.
    # Evaluate the actual application predict path for deployed-threshold metrics.
    import cv2
    import yaml
    data = yaml.safe_load(Path(signature["yaml"]).read_text(encoding="utf-8"))
    root = Path(data.get("path", Path(signature["yaml"]).parent))
    if not root.is_absolute():
        root = Path(signature["yaml"]).parent / root
    image_folder = root / data[signature["split"]]
    model = YOLO(str(checkpoint))
    runtime_settings = {"imgsz": 768, "conf": .001, "iou": .70, "max_det": 132,
                        "device": device, "half": False, "verbose": False}
    predict_options = {key: value for key, value in runtime_settings.items() if key != "half"}
    runtime_records, inference_times = [], []
    print(f"Evaluating application prediction path for {checkpoint.name}", flush=True)
    for number, record in enumerate(payload["native_records"]):
        image = cv2.imread(str(image_folder / record["file"]))
        if image is None:
            raise ValueError(f"Cannot decode {record['file']}")
        if number == 0:
            model.predict(source=image, **runtime_settings)
        prediction = model.predict(source=image, **predict_options)[0]
        runtime_records.append({"file": record["file"], "boxes": prediction.boxes.xyxy.cpu().tolist(),
                                "scores": prediction.boxes.conf.cpu().tolist(), "targets": record["targets"]})
        inference_times.append(float(prediction.speed["inference"]))
        # Check that filtering the confidence sweep reproduces direct runtime
        # calls at both configured thresholds, including the max-detection cap.
        if number < 3:
            for threshold in (.5, .7):
                direct = model.predict(source=image, **{**predict_options, "conf": threshold})[0]
                mask = prediction.boxes.conf >= threshold
                if not (int(mask.sum()) == len(direct.boxes)
                        and np.allclose(prediction.boxes.xyxy[mask].cpu(), direct.boxes.xyxy.cpu(), atol=.01)
                        and np.allclose(prediction.boxes.conf[mask].cpu(), direct.boxes.conf.cpu(), atol=1e-5)):
                    raise ValueError("Low-confidence prediction filtering differs from the deployed threshold.")
        if (number + 1) % 100 == 0:
            print(f"Runtime {checkpoint.name}: {number+1}/{len(payload['native_records'])}", flush=True)
    payload["runtime_settings"] = runtime_settings
    payload["runtime_inference_ms_mean"] = float(np.mean(inference_times))
    payload["records"] = runtime_records
    save_json(output, payload)
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return payload


def paired_bootstrap(first: np.ndarray, second: np.ndarray, repeats: int = 10000) -> dict:
    """Descriptive paired image resampling; deliberately no population p-value."""
    if len(first) != len(second) or not len(first):
        raise ValueError("Paired arrays must contain the same nonzero number of images.")
    rng = np.random.default_rng(42)
    deltas = {key: [] for key in ("precision", "recall", "f1", "exact_count_accuracy")}
    for _ in range(repeats):
        indices = rng.integers(0, len(first), size=len(first))
        old, new = count_metrics(first[indices]), count_metrics(second[indices])
        for key in deltas:
            deltas[key].append(new[key] - old[key])
    return {key: {"lower": float(np.quantile(values, .025)), "upper": float(np.quantile(values, .975))}
            for key, values in deltas.items()}


def summarize(evaluations: dict) -> dict:
    summaries = {}
    for name, pair in evaluations.items():
        if [r["file"] for r in pair["v2"]["records"]] != [r["file"] for r in pair["v3"]["records"]]:
            raise ValueError("Versions were evaluated on different images.")
        for old, new in zip(pair["v2"]["records"], pair["v3"]["records"]):
            if old["targets"] != new["targets"]:
                raise ValueError("Ground truth differs between model evaluations.")
        summary = {"images": len(pair["v2"]["records"]), "models": {}, "paired_intervals": {}}
        counts = {}
        for tag, evaluation in pair.items():
            counts[tag] = {}
            model = {"map50": evaluation["map50"], "map50_95": evaluation["map50_95"],
                     "checkpoint_sha256": evaluation["provenance"]["checkpoint_sha256"], "thresholds": {}}
            for threshold in (.5, .7):
                key = f"{threshold:.2f}"
                array = np.asarray([match_counts(r["boxes"], r["scores"], r["targets"], threshold) for r in evaluation["records"]])
                counts[tag][key] = array
                result = count_metrics(array)
                result["per_image"] = [{"file": r["file"], "tp": int(c[0]), "fp": int(c[1]), "fn": int(c[2])}
                                       for r, c in zip(evaluation["records"], array)]
                dates = [capture_date(r["file"]) for r in evaluation["records"]]
                result["by_capture_date"] = {date: {"images": dates.count(date), **count_metrics(array[np.asarray(dates) == date])}
                                             for date in sorted(set(dates))}
                model["thresholds"][key] = result
            summary["models"][tag] = model
        for threshold in ("0.50", "0.70"):
            summary["paired_intervals"][threshold] = paired_bootstrap(counts["v2"][threshold], counts["v3"][threshold])
        summaries[name] = summary
    return summaries


def promotion_gate(summary: dict) -> dict:
    """Conservative practical decision, not a claim of independent significance."""
    current = summary["development"]["models"]
    checks = {"development_map50_95_gain_at_least_2pp": current["v3"]["map50_95"] - current["v2"]["map50_95"] >= .02}
    for threshold in ("0.50", "0.70"):
        old, new = (current[tag]["thresholds"][threshold] for tag in ("v2", "v3"))
        checks[f"development_f1_improves_at_{threshold}"] = new["f1"] > old["f1"]
        checks[f"development_precision_loss_at_most_1pp_at_{threshold}"] = new["precision"] >= old["precision"] - .01
        checks[f"development_paired_f1_interval_above_zero_at_{threshold}"] = summary["development"]["paired_intervals"][threshold]["f1"]["lower"] > 0
    if "legacy" in summary:
        legacy = summary["legacy"]["models"]
        checks["legacy_map50_95_loss_at_most_2pp"] = legacy["v3"]["map50_95"] >= legacy["v2"]["map50_95"] - .02
        for threshold in ("0.50", "0.70"):
            checks[f"legacy_f1_loss_at_most_2pp_at_{threshold}"] = legacy["v3"]["thresholds"][threshold]["f1"] >= legacy["v2"]["thresholds"][threshold]["f1"] - .02
    else:
        checks["legacy_regression_check_available"] = False
    return {"candidate_supported": all(checks.values()), "checks": checks,
            "interpretation": "Practical internal validation gate; independent population significance is not established.",
            "policy": "At least +2 percentage points development mAP50–95, better F1 at both deployed thresholds with descriptive paired intervals above zero, no precision loss above 1pp, and no legacy mAP/F1 loss above 2pp."}


def make_graphs(summary: dict, evaluations: dict, output: Path, training_csv: Path | None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 120, "savefig.dpi": 200})
    colors = {"v2": "#64748b", "v3": "#0284c7"}

    def save(fig, name):
        fig.savefig(output / f"{name}.png", bbox_inches="tight")
        fig.savefig(output / f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)

    development = summary["development"]["models"]
    fig, axes = plt.subplots(len(summary), 2, figsize=(14, 5.2 * len(summary)), squeeze=False)
    for row, (dataset_name, subset) in enumerate(summary.items()):
        for ax, threshold in zip(axes[row], ("0.50", "0.70")):
            keys = ["precision", "recall", "f1", "map50", "map50_95"]
            for offset, tag in zip((-.19, .19), ("v2", "v3")):
                model = subset["models"][tag]
                values = [100 * (model[key] if key.startswith("map") else model["thresholds"][threshold][key]) for key in keys]
                bars = ax.bar(np.arange(len(keys)) + offset, values, width=.36, color=colors[tag], label=tag.upper())
                ax.bar_label(bars, labels=[f"{v:.1f}" for v in values], fontsize=9, padding=3)
            ax.set_xticks(np.arange(len(keys)), [METRIC_NAMES[k] for k in keys], rotation=18)
            ax.set_ylim(0, 108)
            ax.set_ylabel("Percent (higher is better)")
            ax.set_title(f"{dataset_name.title()} · {subset['images']} images · confidence {threshold}")
            ax.legend(frameon=False)
    fig.suptitle("Model 1 v2 vs v3 · gains and regressions on identical data", fontsize=15)
    fig.text(.5, -.02, "mAP sweeps confidence (minimum 0.001). P/R/F1 use the stated fixed threshold. Internal validation; no independent test claim.", ha="center", fontsize=9)
    fig.tight_layout()
    save(fig, "01_detection_metrics")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for ax, threshold in zip(axes, ("0.50", "0.70")):
        for offset, tag in zip((-.19, .19), ("v2", "v3")):
            values = [development[tag]["thresholds"][threshold][key] for key in ("tp", "fp", "fn")]
            bars = ax.bar(np.arange(3) + offset, values, width=.36, color=colors[tag], label=tag.upper())
            ax.bar_label(bars, padding=3)
        ax.set_xticks(np.arange(3), ["Correct detections ↑", "False positives ↓", "Missed fish ↓"])
        ax.set_ylim(0, max(development[t]["thresholds"][threshold]["tp"] for t in ("v2", "v3")) * 1.2)
        fish_count = development["v2"]["thresholds"][threshold]["tp"] + development["v2"]["thresholds"][threshold]["fn"]
        ax.set_title(f"Confidence {threshold} · {fish_count:,} development ground-truth fish")
        ax.legend(frameon=False)
    fig.suptitle("Correct detections and errors on the same images", fontsize=15)
    fig.tight_layout()
    save(fig, "02_detection_errors")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    thresholds = np.linspace(.05, .95, 91)
    curve_rows = []
    for tag, evaluation in evaluations["development"].items():
        curves = []
        for threshold in thresholds:
            values = count_metrics(np.asarray([match_counts(r["boxes"], r["scores"], r["targets"], float(threshold)) for r in evaluation["records"]]))
            curve_rows.append({"model": tag, "confidence": float(threshold), **values})
            curves.append(values)
        axes[0].plot([100*c["recall"] for c in curves], [100*c["precision"] for c in curves], color=colors[tag], label=tag.upper(), linewidth=2)
        axes[1].plot(thresholds, [100*c["f1"] for c in curves], color=colors[tag], label=tag.upper(), linewidth=2)
    axes[0].set(xlabel="Recall (%)", ylabel="Precision (%)", xlim=(0, 100), ylim=(0, 101), title="Precision–recall operating points · IoU 0.50")
    axes[1].set(xlabel="Confidence threshold", ylabel="F1 (%)", ylim=(0, 100), title="F1 across confidence thresholds")
    for threshold in (.5, .7):
        axes[1].axvline(threshold, color="#a3a3a3", linestyle="--", linewidth=1)
    for ax in axes:
        ax.legend(frameon=False)
        ax.grid(alpha=.18)
    fig.suptitle("Confidence sweep · internal development validation", fontsize=15)
    fig.tight_layout()
    save(fig, "03_precision_recall_and_f1")
    with (output / "confidence_sweep.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(curve_rows[0]))
        writer.writeheader()
        writer.writerows(curve_rows)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, threshold in zip(axes, ("0.50", "0.70")):
        keys = ["precision", "recall", "f1", "exact_count_accuracy"]
        values = np.array([100 * (development["v3"]["thresholds"][threshold][k] - development["v2"]["thresholds"][threshold][k]) for k in keys])
        intervals = summary["development"]["paired_intervals"][threshold]
        lower = np.array([100*intervals[k]["lower"] for k in keys])
        upper = np.array([100*intervals[k]["upper"] for k in keys])
        ax.errorbar(values, np.arange(4), xerr=[np.maximum(0, values-lower), np.maximum(0, upper-values)], fmt="o", capsize=5, color=colors["v3"])
        ax.set_yticks(np.arange(4), [METRIC_NAMES[k] for k in keys])
        ax.axvline(0, color="#9ca3af", linestyle="--")
        ax.set(xlabel="V3 minus V2 (percentage points)", title=f"Confidence {threshold} · paired 95% intervals")
        ax.grid(axis="x", alpha=.18)
    fig.suptitle("Descriptive uncertainty · 10,000 paired image bootstrap samples", fontsize=14)
    fig.text(.5, -.02, "Correlated capture sessions and checkpoint selection limit inference. These intervals do not prove independent statistical significance.", ha="center", fontsize=9)
    fig.tight_layout()
    save(fig, "04_paired_uncertainty")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, (name, subset) in zip(axes, summary.items()):
        for offset, tag in zip((-.19, .19), ("v2", "v3")):
            model = subset["models"][tag]
            values = [100*model["thresholds"]["0.50"]["exact_count_accuracy"], 100*model["thresholds"]["0.70"]["exact_count_accuracy"], 100*model["map50_95"]]
            bars = ax.bar(np.arange(3) + offset, values, width=.36, color=colors[tag], label=tag.upper())
            ax.bar_label(bars, labels=[f"{v:.1f}" for v in values], padding=3)
        ax.set_xticks(np.arange(3), ["Exact count @0.50", "Exact count @0.70", "mAP@50–95"], rotation=10)
        ax.set(title=f"{name.title()} · {subset['images']} images", ylabel="Percent", ylim=(0, 108))
        ax.legend(frameon=False)
    fig.suptitle("Count accuracy and legacy regression check", fontsize=15)
    fig.text(.5, -.02, "Exact count accuracy = images with predicted count equal to true count; cancelling FP/FN can still give an exact count. This is not classification accuracy.", ha="center", fontsize=9)
    fig.tight_layout()
    save(fig, "05_count_accuracy_and_regression")

    dates = sorted(development["v2"]["thresholds"]["0.70"]["by_capture_date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    for offset, tag in zip((-.19, .19), ("v2", "v3")):
        values = [100*development[tag]["thresholds"]["0.70"]["by_capture_date"][date]["f1"] for date in dates]
        bars = ax.bar(np.arange(len(dates)) + offset, values, width=.36, color=colors[tag], label=tag.upper())
        ax.bar_label(bars, labels=[f"{v:.1f}" for v in values], padding=3)
    ax.set_xticks(np.arange(len(dates)), [f"{date}\nn={development['v2']['thresholds']['0.70']['by_capture_date'][date]['images']}" for date in dates])
    ax.set(title="F1 by validation capture date · confidence 0.70", ylabel="F1 (%)", ylim=(0, 108))
    ax.legend(frameon=False)
    fig.text(.5, -.02, "Only three capture dates; one has a single image. Physical specimen independence is unknown.", ha="center", fontsize=9)
    fig.tight_layout()
    save(fig, "06_capture_date_results")

    if training_csv:
        with training_csv.open(encoding="utf-8-sig") as handle:
            rows = [{k.strip(): float(v) for k,v in row.items()} for row in csv.DictReader(handle)]
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))
        for key in ("metrics/mAP50(B)", "metrics/mAP50-95(B)"):
            axes[0].plot([r["epoch"] for r in rows], [100*r[key] for r in rows], label=key.replace("metrics/", ""))
        for key in ("train/box_loss", "val/box_loss"):
            axes[1].plot([r["epoch"] for r in rows], [r[key] for r in rows], label=key)
        axes[0].set(xlabel="Epoch", ylabel="Percent", title="V3 training validation metrics (epoch log)")
        axes[1].set(xlabel="Epoch", ylabel="Box loss", title="V3 training and validation box loss")
        for ax in axes:
            ax.legend(frameon=False)
            ax.grid(alpha=.18)
        fig.text(.5, -.02, "Training diagnostics use the trainer's evaluation mode and are separate from the identical-settings checkpoint comparison.", ha="center", fontsize=9)
        fig.tight_layout()
        save(fig, "07_v3_training_history")


def write_report(summary: dict, gate: dict, output: Path) -> None:
    lines = ["# Model 1 v2 versus v3", "", LIMITATION, "", "## Same-data results", "",
             "All evaluations use 768 px, batch 1, FP32, confidence floor 0.001, IoU NMS 0.70, max detections 132, and the same software/device. AP uses Ultralytics native validation. Native validation and application prediction use different image padding; fixed-threshold P/R/F1 and count metrics therefore come from a separate pass through the application's single-frame BGR prediction path. Counts use confidence-ordered one-to-one matching at IoU 0.50. Direct predictions at 0.50 and 0.70 are checked against filtered predictions on the first three images per model and dataset.", "",
             "| Dataset | Confidence | Model | Precision | Recall | F1 | Exact count accuracy | mAP@50 | mAP@50–95 | TP | FP | FN |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    rows = []
    for name, subset in summary.items():
        for threshold in ("0.50", "0.70"):
            for tag, model in subset["models"].items():
                m = model["thresholds"][threshold]
                values = [m[k] for k in ("precision", "recall", "f1", "exact_count_accuracy")] + [model["map50"], model["map50_95"]]
                lines.append(f"| {name} ({subset['images']} images) | {threshold} | {tag} | " + " | ".join(f"{v*100:.2f}%" for v in values) + f" | {m['tp']} | {m['fp']} | {m['fn']} |")
                rows.append({"dataset": name, "confidence": threshold, "model": tag,
                             **{k:v for k,v in m.items() if k not in {"per_image", "by_capture_date"}},
                             "map50": model["map50"], "map50_95": model["map50_95"]})
    lines += ["", "Exact count accuracy means the fraction of images with the correct number of detections. It is not ordinary classification accuracy; false positives and missed fish can cancel. No true-negative object population is defined, so classification accuracy is not reported.", "", "## Selection evidence", "", gate["policy"], "",
              f"Candidate supported by practical gate: **{gate['candidate_supported']}**. This script does not deploy it.", ""]
    lines.extend(f"- {'PASS' if passed else 'FAIL'}: {check}" for check, passed in gate["checks"].items())
    lines += ["", "## Uncertainty", "", "The plotted 95% intervals use 10,000 paired image bootstrap samples and seed 42, keeping both model outputs together for each sampled image. They do not account for unknown specimen correlation, v3 checkpoint selection, or unknown v2 training exposure. With only three validation capture dates (one containing one image), broad statistical significance cannot be established. No population p-value is claimed.", "", "## Reproduction and evidence", "", "`evaluation_manifest.json` records image/label hashes, datasets, software and settings. `evaluations/` contains checkpoint hashes, unrounded prediction boxes/scores and ground truth. `comparison.json` holds aggregates and per-image counts. Every graph is provided as PNG and PDF; `metrics.csv` and `confidence_sweep.csv` contain plotted values.", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--legacy-data", type=Path)
    parser.add_argument("--training-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    datasets = {"development": dataset_signature(args.data, "val")}
    if args.legacy_data:
        datasets["legacy"] = dataset_signature(args.legacy_data, "test")
    evaluations = {}
    for name, signature in datasets.items():
        print(f"Dataset fingerprint {name}: {signature['fingerprint']}", flush=True)
        evaluations[name] = {tag: evaluate(checkpoint, signature, args.output / "evaluations" / name / f"{tag}.json", args.device)
                             for tag, checkpoint in (("v2", args.baseline), ("v3", args.candidate))}
    print("Computing paired intervals and graphs", flush=True)
    summary = summarize(evaluations)
    gate = promotion_gate(summary)
    save_json(args.output / "evaluation_manifest.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "datasets": datasets,
              "training_csv": str(args.training_csv) if args.training_csv else None,
              "training_csv_sha256": sha256(args.training_csv) if args.training_csv else None, "limitation": LIMITATION})
    save_json(args.output / "comparison.json", {"datasets": summary, "selection": gate, "limitation": LIMITATION})
    make_graphs(summary, evaluations, args.output, args.training_csv)
    write_report(summary, gate, args.output)
    print(json.dumps(gate, indent=2), flush=True)
    for name, subset in summary.items():
        for tag, model in subset["models"].items():
            print(name, tag, "map50_95", model["map50_95"], {t:{k:v for k,v in m.items() if k in {"precision","recall","f1","tp","fp","fn","exact_count_accuracy"}} for t,m in model["thresholds"].items()}, flush=True)


if __name__ == "__main__":
    main()
