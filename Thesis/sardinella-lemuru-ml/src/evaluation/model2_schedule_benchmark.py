"""Replay fixed-resolution videos through the real pipeline for Model 2 comparisons.

This collects observations for expert review; it does not infer ownership truth.
See docs/model2_schedule_benchmark.md for the manifest and limitations.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import platform
from pathlib import Path
from time import perf_counter

import cv2

from src.api.camera import CameraInspectionService
from src.api.domain import InspectionState
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> tuple[list[dict], tuple[int, int]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resolution = manifest.get("resolution")
    clips = manifest.get("clips")
    if (not isinstance(resolution, list) or len(resolution) != 2 or
            any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in resolution)):
        raise ValueError("resolution must be [width, height] in positive pixels")
    if not isinstance(clips, list) or not clips:
        raise ValueError("clips must contain at least one video")
    ids = set()
    result = []
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or not clip["id"].strip():
            raise ValueError("each clip needs a nonempty id")
        if clip["id"] in ids:
            raise ValueError("clip ids must be unique")
        ids.add(clip["id"])
        if not isinstance(clip.get("path"), str):
            raise ValueError("each clip needs a video path")
        video = Path(clip["path"]).expanduser()
        video = (video if video.is_absolute() else path.parent / video).resolve()
        if not video.is_file():
            raise ValueError(f"video does not exist: {video}")
        crossings = clip.get("expert_crossings")
        if crossings is not None and (isinstance(crossings, bool) or not isinstance(crossings, int) or crossings < 0):
            raise ValueError("expert_crossings must be a nonnegative integer or null")
        if crossings is not None and (not clip.get("expert_reviewer") or not clip.get("truth_reference") or
                                      clip.get("system_prediction_visible") is not False):
            raise ValueError("expert crossings require reviewer, truth reference and system_prediction_visible=false")
        result.append({**clip, "path": str(video), "sha256": sha256(video)})
    return result, tuple(resolution)


def replay(video: Path, resolution: tuple[int, int], detector: YoloFishDetector,
           quality: YoloQualityModel, mode: str, interval: int, trace, max_frames: int | None = None) -> dict:
    detector.reset_tracker()
    quality.reset_tracks()
    quality.quality_inference_mode = mode
    state = InspectionState()
    service = CameraInspectionService(state, detector, quality_model=quality,
                                      quality_inference_mode=mode, quality_interval=interval)
    service._runtime_metrics.enabled = True
    latencies: dict[str, float] = {}
    original_latency = service._runtime_metrics.record_latency
    def record_latency(name, seconds):
        original_latency(name, seconds)
        if seconds is not None and math.isfinite(seconds) and seconds >= 0:
            latencies[name] = latencies.get(name, 0.0) + seconds * 1000
    service._runtime_metrics.record_latency = record_latency
    original_predict = detector.predict
    frame_detections = []
    def capture_detections(frame):
        nonlocal frame_detections
        found = original_predict(frame)
        frame_detections = [{"track_id": item.track_id, "bbox": list(item.bbox), "confidence": item.confidence} for item in found]
        return found
    detector.predict = capture_detections
    original_record = service._record_quality_observation
    observations = []
    def capture_observation(detection, result, bounds, *args, **kwargs):
        observations.append({"track_id": int(detection.track_id), "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                             "quality": result.quality, "parts_crop_coordinates": [part.to_dict() for part in result.parts],
                             "association": result.analysis.get("quality_inference", {}).get("association")})
        return original_record(detection, result, bounds, *args, **kwargs)
    service._record_quality_observation = capture_observation
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        detector.predict = original_predict
        raise ValueError(f"cannot open video: {video}")
    frames = 0
    started = perf_counter()
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if (frame.shape[1], frame.shape[0]) != resolution:
                raise ValueError(f"{video}: frame {frames} has unexpected resolution {frame.shape[1]}x{frame.shape[0]}")
            observations = []
            service.process_frame(frame, cv2)
            if state.segmenter_status == "error":
                raise RuntimeError(f"Model 2 processing failed: {state.segmenter_message}")
            trace.write(json.dumps({"frame": frames, "detections": frame_detections, "observations": observations}, allow_nan=False) + "\n")
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break
    finally:
        capture.release()
        detector.predict = original_predict
    if not frames:
        raise ValueError(f"no readable frames in {video}")
    events = state.tracking.archive_history()
    snapshot = state.snapshot()
    count = snapshot["counters"]["total"]
    quality_counts = snapshot["quality_counters"]
    graded = sum(value for name, value in quality_counts.items() if name != "Ungraded")
    counters = service.runtime_diagnostics()["performance"]["counters"]
    return {"frames": frames, "wall_seconds_including_trace_io": perf_counter() - started,
            "model2_invocations": counters.get("model2", 0), "model2_total_ms": latencies.get("model2_inference"),
            "association_total_ms": latencies.get("association"),
            "part_assignment_total_ms": latencies.get("part_assignment"),
            "recorded_crossings": count, "quality_counts": quality_counts,
            "graded_fraction_of_recorded_crossings": graded / count if count else None,
            "archived_event_count": len(events), "final_events": events}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model1", type=Path, required=True)
    parser.add_argument("--model2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing files are never overwritten")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model1-size", type=int, default=640)
    parser.add_argument("--model2-size", type=int, default=640)
    parser.add_argument("--modes", nargs="+", choices=("full_frame", "crop"), default=["full_frame", "crop"])
    parser.add_argument("--intervals", nargs="+", type=int, default=[1, 2, 3, 4])
    parser.add_argument("--max-frames", type=int, help="Limit each clip for smoke testing; not a complete study")
    args = parser.parse_args(argv)
    if any(value <= 0 for value in args.intervals):
        parser.error("intervals must be positive")
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("max-frames must be positive")
    clips, resolution = read_manifest(args.manifest)
    if not args.model1.is_file() or not args.model2.is_file():
        parser.error("both checkpoint files must exist")
    args.output.mkdir(parents=True, exist_ok=False)
    detector = YoloFishDetector(args.model1.resolve(), device=args.device, image_size=args.model1_size)
    quality = YoloQualityModel(args.model2.resolve(), device=args.device, image_size=args.model2_size)
    if not detector.load() or not quality.load():
        raise RuntimeError(f"model loading failed: {detector.error or quality.error}")
    config = {"manifest_sha256": sha256(args.manifest), "model1_sha256": sha256(args.model1), "model2_sha256": sha256(args.model2),
              "resolution": resolution, "device_requested": args.device, "model1_device": detector.device, "model2_device": quality.device,
              "model1_image_size": args.model1_size, "model2_image_size": args.model2_size, "platform": platform.platform(),
              "opencv": cv2.__version__, "model1_confidence": detector.confidence_threshold,
              "model2_confidence": quality.confidence_threshold,
              "max_frames": args.max_frames,
              "grading_configuration": asdict(quality._grading_engine.config),
              "tracking_configuration": InspectionState().tracking.config.to_dict(),
              "warning": "Exploratory replay; accuracy and ownership require independent expert review. Wall time includes trace I/O."}
    results = []
    for clip_number, clip in enumerate(clips):
        for mode in args.modes:
            for interval in args.intervals:
                name = f"clip_{clip_number:03d}_{mode}_{interval}.jsonl"
                with (args.output / name).open("x", encoding="utf-8") as trace:
                    result = replay(Path(clip["path"]), resolution, detector, quality, mode, interval, trace, args.max_frames)
                truth = clip.get("expert_crossings")
                if args.max_frames is not None:
                    truth = None  # The expert count applies to the complete clip.
                result.update({"clip_id": clip["id"], "clip_sha256": clip["sha256"], "mode": mode, "interval": interval,
                               "expert_crossings": truth, "count_error": None if truth is None else result["recorded_crossings"] - truth,
                               "trace": name})
                results.append(result)
    (args.output / "report.json").write_text(json.dumps({"configuration": config, "clips": clips, "results": results}, indent=2, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
