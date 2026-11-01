"""In-memory still-image analysis using the existing two local models."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
import warnings

import cv2
import numpy as np
from PIL import Image, JpegImagePlugin, PngImagePlugin

from src.inference.yolo_fish_detector import FishDetection, YoloFishDetector
from src.inference.yolo_quality_model import FishQualityObservation, YoloQualityModel
from src.inference.association import ParentAnchor
from src.inference.body_width import analyze_body_width, boxes_overlap
from src.inference.part_types import PartDetection
from src.inference.part_model import YoloPartModel
from src.inference.preprocessing import (
    CropBounds,
    PreprocessingError,
    canonicalize_image,
    clamp_bbox,
    crop_fish,
    translate_bbox_to_frame,
    validate_image,
)


ALLOWED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
ALLOWED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm"})
DEFAULT_QUALITY_COUNTS = ("Class A", "Class B", "Class C", "Rejected", "Ungraded")


class ImageUploadError(ValueError):
    """A client-safe upload validation error."""


class VideoUploadError(ValueError):
    """A client-safe video upload validation error."""


def _box_iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    """Read the VP8/VP8L/VP8X canvas size without initializing a decoder."""
    if len(data) < 25:
        raise ImageUploadError("The uploaded WEBP header is incomplete.")
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
    if chunk == b"VP8L" and data[20] == 0x2F:
        packed = int.from_bytes(data[21:25], "little")
        return (1 + (packed & 0x3FFF), 1 + ((packed >> 14) & 0x3FFF))
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return (int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF)
    raise ImageUploadError("The uploaded WEBP header is invalid.")


def decode_uploaded_image(
    data: bytes,
    filename: str,
    *,
    max_bytes: int,
    max_dimension: int,
    max_pixels: int,
) -> np.ndarray:
    """Validate and decode a supported image without writing it to disk."""

    suffix = filename.lower().rsplit(".", 1)
    extension = f".{suffix[-1]}" if len(suffix) == 2 else ""
    if extension not in ALLOWED_IMAGE_SUFFIXES:
        supported = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise ImageUploadError(f"Unsupported image format. Use one of: {supported}.")
    if not data:
        raise ImageUploadError("The uploaded image is empty.")
    if len(data) > max_bytes:
        raise ImageUploadError(f"The uploaded image exceeds the {max_bytes} byte limit.")
    # Parse supported image headers before asking OpenCV to allocate decoded
    # pixels. The filename is not evidence of the actual encoded format.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # Use the format-specific header readers directly: Ultralytics
            # monkey-patches Image.open to try installing an unrelated HEIF
            # plugin when identification fails.
            if data.startswith(b"\xff\xd8\xff"):
                header_reader = JpegImagePlugin.JpegImageFile
            elif data.startswith(b"\x89PNG\r\n\x1a\n"):
                header_reader = PngImagePlugin.PngImageFile
            elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
                header_reader = None
            else:
                raise ImageUploadError("The uploaded file is not a supported, decodable image.")
            if header_reader is None:
                width, height = _webp_dimensions(data)
            else:
                with header_reader(BytesIO(data)) as header:
                    width, height = header.size
            if not width or not height or width > max_dimension or height > max_dimension or width * height > max_pixels:
                raise ImageUploadError("The uploaded image dimensions exceed the configured limit.")
    except ImageUploadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageUploadError("The uploaded image dimensions exceed the configured limit.") from exc
    except (OSError, ValueError, SyntaxError, OverflowError, EOFError) as exc:
        raise ImageUploadError("The uploaded file is not a supported, decodable image.") from exc
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ImageUploadError("The uploaded file is not a decodable color image.") from exc
    if image is None:
        raise ImageUploadError("The uploaded file is not a decodable color image.")
    try:
        # IMREAD_COLOR yields BGR and, without IMREAD_IGNORE_ORIENTATION, uses
        # OpenCV's normal EXIF-orientation handling. The rendered image and the
        # inference image are therefore the same canonical pixels.
        image = canonicalize_image(image, source_color_order="bgr", name="Uploaded image")
    except PreprocessingError as exc:
        raise ImageUploadError(str(exc)) from exc
    height, width = image.shape[:2]
    if not width or not height or width > max_dimension or height > max_dimension or width * height > max_pixels:
        raise ImageUploadError("The uploaded image dimensions exceed the configured limit.")
    return image


@dataclass(frozen=True)
class _UploadFish:
    index: int
    bbox: tuple[float, float, float, float]
    confidence: float
    quality_result: FishQualityObservation | None
    crop_bounds: CropBounds | None = None

    @property
    def quality(self) -> str:
        return self.quality_result.quality if self.quality_result and self.quality_result.quality else "Ungraded"


class StillImageAnalyzer:
    """Analyze one uploaded frame without tracker, camera, or session mutations."""

    def __init__(self, detector: YoloFishDetector, quality_model: YoloQualityModel | None, roi_padding: int = 0) -> None:
        self.detector = detector
        self.quality_model = quality_model
        self.roi_padding = roi_padding

    @staticmethod
    def _draw_quality(frame: np.ndarray, fish: _UploadFish) -> None:
        if fish.quality_result is None:
            return
        height, width = frame.shape[:2]
        colors = {"Class A": (76, 175, 80), "Class B": (255, 152, 0), "Class C": (170, 90, 205), "Rejected": (45, 45, 225)}
        bounds = fish.crop_bounds
        if bounds is None:
            return
        for part in fish.quality_result.parts:
            translated = translate_bbox_to_frame(part.bbox, bounds, width, height)
            if translated is not None:
                left, top, right, bottom = translated
                grade = getattr(part, "grade", getattr(part, "quality", ""))
                region = getattr(part, "region", getattr(part, "part", ""))
                color = colors.get(grade, (180, 180, 180))
                cv2.rectangle(frame, (int(left), int(top)), (int(right), int(bottom)), color, 1)
                cv2.putText(frame, region, (max(0, int(left)), max(15, int(top) - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

    def _fish_payload(self, fish: _UploadFish, frame_width: int, frame_height: int) -> dict[str, object]:
        parts: list[dict[str, object]] = []
        if fish.quality_result and fish.crop_bounds is not None:
            for part in fish.quality_result.parts:
                translated = translate_bbox_to_frame(part.bbox, fish.crop_bounds, frame_width, frame_height)
                if translated is None:
                    continue
                payload = part.to_dict() if hasattr(part, "to_dict") else part.compact()
                payload["bbox"] = [round(value, 2) for value in translated]
                parts.append(payload)
        analysis = dict(getattr(fish.quality_result, "analysis", {})) if fish.quality_result else {}
        if not isinstance(analysis.get("body_width"), dict):
            # Model 1 still supplies real dimensions when Model 2 is absent.
            # Do not infer Body geometry from an incompatible legacy adapter.
            analysis["body_width"] = analyze_body_width(
                fish.bbox, (), detection_confidence=fish.confidence,
                frame_shape=(frame_height, frame_width, 3),
            )
            analysis["body_width"]["coordinate_space"] = "original_frame"
        analysis["model1_detection"] = {
            "confidence": fish.confidence,
            "bbox": list(fish.bbox),
            "width_px": fish.bbox[2] - fish.bbox[0],
            "height_px": fish.bbox[3] - fish.bbox[1],
            "source": "Model 1 whole-fish detector",
            "note": "Detection confidence is retained for traceability and does not modify Model 2 grade scores.",
        }
        traceability = analysis.get("traceability") if isinstance(analysis.get("traceability"), dict) else {}
        traceability = dict(traceability)
        traceability.update({
            "model1_checkpoint": self.detector.weights_path.name if getattr(self.detector, "weights_path", None) else None,
            "model1_checkpoint_sha256": getattr(self.detector, "checkpoint_sha256", None),
            "detection_threshold": getattr(self.detector, "confidence_threshold", None),
        })
        if self.quality_model is not None:
            traceability.update({
                "model2_id": getattr(self.quality_model, "active_model_id", None),
                "model2_name": getattr(self.quality_model, "active_model_name", getattr(self.quality_model, "name", None)),
                "model2_checkpoint": self.quality_model.weights_path.name if getattr(self.quality_model, "weights_path", None) else None,
                "model2_checkpoint_sha256": getattr(self.quality_model, "checkpoint_sha256", None),
            })
        analysis["traceability"] = traceability
        analysis["inspection_source"] = {
            "type": "uploaded_photo", "frame_width_px": frame_width, "frame_height_px": frame_height,
        }
        return {
            "id": fish.index,
            "bbox": [round(value, 2) for value in fish.bbox],
            "detector_confidence": round(fish.confidence, 4),
            "quality": fish.quality,
            "quality_confidence": fish.quality_result.quality_confidence if fish.quality_result else None,
            "parts": parts,
            "analysis": analysis,
        }

    def analyze(self, frame: np.ndarray) -> dict[str, object]:
        if self.detector.model is None:
            raise RuntimeError(self.detector.error or "Model 1 Fish detector is unavailable.")
        try:
            frame = validate_image(frame, name="Uploaded image")
        except PreprocessingError as exc:
            raise ImageUploadError(str(exc)) from exc
        detections: list[FishDetection] = self.detector.detect(frame)
        results: list[_UploadFish] = []
        full_frame_results: dict[int, tuple[FishQualityObservation, CropBounds]] = {}
        if (
            isinstance(self.quality_model, YoloQualityModel)
            and self.quality_model.model is not None
            and self.quality_model.quality_inference_mode == "full_frame"
        ):
            parents = []
            for index, detection in enumerate(detections, start=1):
                bounded_parent = clamp_bbox(detection.bbox, frame.shape[1], frame.shape[0])
                if bounded_parent is not None:
                    parents.append(ParentAnchor(index, detection.bbox, detection.confidence))
            if parents:
                full_frame_results = self.quality_model.predict_full_frame(
                    frame,
                    parents,
                    stabilize=False,
                    frame_id="still-full-frame",
                )
        for index, detection in enumerate(detections, start=1):
            bounded = clamp_bbox(detection.bbox, frame.shape[1], frame.shape[0])
            if bounded is None:
                continue
            quality_result = None
            crop_bounds = None
            if isinstance(self.quality_model, YoloQualityModel):
                if self.quality_model.model is None:
                    # Match the live pipeline: an unavailable Model 2 is an
                    # explicit abstention, not a blank upload result.  The
                    # canonical grading policy records UG_MODEL2_UNAVAILABLE
                    # with the same per-fish traceability as a live frame.
                    crop, crop_bounds = crop_fish(frame, bounded, padding=self.roi_padding)
                    quality_result = self.quality_model.unavailable_observation(
                        crop,
                        index,
                        stabilize=False,
                        frame_id=f"still-{index}",
                        detection_confidence=detection.confidence,
                        parent_bbox=bounded,
                        frame_shape=frame.shape,
                    )
                elif self.quality_model.quality_inference_mode == "full_frame":
                    quality_result, crop_bounds = full_frame_results[index]
                else:
                    crop, crop_bounds = crop_fish(frame, bounded, padding=self.roi_padding)
                    quality_result = self.quality_model.predict(
                        crop,
                        index,
                        stabilize=False,
                        frame_id=f"still-{index}",
                        detection_confidence=detection.confidence,
                        parent_bbox=detection.bbox,
                        frame_shape=frame.shape,
                        frame_quality={"width_context": {
                            "crop_bounds": [crop_bounds.x1, crop_bounds.y1, crop_bounds.x2, crop_bounds.y2],
                            "overlapping": any(other is not detection and boxes_overlap(detection.bbox, other.bbox) for other in detections),
                        }},
                    )
            elif self.quality_model is not None and self.quality_model.model is not None:
                # Compatibility for the prior experimental RF-DETR adapter.
                crop, crop_bounds = crop_fish(frame, bounded, padding=self.roi_padding)
                quality_result = self.quality_model.predict(crop, index)
            fish = _UploadFish(index, bounded, detection.confidence, quality_result, crop_bounds)
            results.append(fish)

        annotated = frame.copy()
        counts = {name: 0 for name in DEFAULT_QUALITY_COUNTS}
        for fish in results:
            self._draw_quality(annotated, fish)
            counts[fish.quality] = counts.get(fish.quality, 0) + 1
            left, top, right, bottom = (int(round(value)) for value in fish.bbox)
            color = {"Class A": (76, 175, 80), "Class B": (255, 152, 0), "Class C": (170, 90, 205), "Rejected": (45, 45, 225)}.get(fish.quality, (120, 120, 120))
            cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
            label = f"#{fish.index} {fish.quality} {fish.confidence * 100:.1f}%"
            cv2.putText(annotated, label, (left, max(18, top - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise RuntimeError("Unable to encode the annotated image.")
        analyzed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        payloads = [self._fish_payload(fish, frame.shape[1], frame.shape[0]) for fish in results]
        for payload in payloads:
            payload["timestamp"] = analyzed_at
        return {
            "fish_detected": len(results),
            "quality_counters": counts,
            "model2_available": bool(self.quality_model and self.quality_model.model is not None),
            "model2_id": getattr(self.quality_model, "active_model_id", None),
            "model2_name": getattr(self.quality_model, "active_model_name", getattr(self.quality_model, "name", None)),
            "fish": payloads,
            "analyzed_at": analyzed_at,
            "inspection_source": {"type": "uploaded_photo", "frame_width_px": frame.shape[1], "frame_height_px": frame.shape[0]},
            "annotated_image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
        }


class VideoUploadAnalyzer:
    """Process uploaded video frames with the same still-image inference path."""

    def __init__(self, analyzer: StillImageAnalyzer) -> None:
        self.analyzer = analyzer

    def analyze(self, path: Path, progress: Any) -> dict[str, object]:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise VideoUploadError("The uploaded video could not be opened.")
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        sample_every = max(1, total_frames // 90) if total_frames else 1
        tracks: list[dict[str, Any]] = []
        annotated_frames: list[str] = []
        frame_index = 0
        processed = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % sample_every != 0:
                    frame_index += 1
                    continue
                result = self.analyzer.analyze(frame)
                processed += 1
                for fish in result["fish"]:
                    bbox = list(fish["bbox"])
                    match = max(tracks, key=lambda item: _box_iou(item["bbox"], bbox), default=None)
                    if match is None or _box_iou(match["bbox"], bbox) < 0.3:
                        match = {"bbox": bbox, "fish": dict(fish), "hits": 0}
                        match["fish"]["id"] = len(tracks) + 1
                        tracks.append(match)
                    match["hits"] += 1
                    if (
                        match["fish"].get("quality") == "Ungraded" and fish.get("quality") != "Ungraded"
                    ) or float(fish.get("detector_confidence") or 0) > float(match["fish"].get("detector_confidence") or 0):
                        match["fish"] = dict(fish)
                        match["fish"]["id"] = tracks.index(match) + 1
                    match["bbox"] = bbox
                if len(annotated_frames) < 90 and (processed == 1 or processed % max(1, total_frames // 90) == 0):
                    annotated_frames.append(str(result["annotated_image"]))
                frame_index += 1
                progress(processed, total_frames or processed)
        finally:
            capture.release()
        if processed == 0:
            raise VideoUploadError("The uploaded video contains no readable frames.")
        fish = [track["fish"] for track in tracks]
        counts = {name: 0 for name in DEFAULT_QUALITY_COUNTS}
        for item in fish:
            counts[item.get("quality", "Ungraded")] = counts.get(item.get("quality", "Ungraded"), 0) + 1
        return {
            "fish_detected": len(fish),
            "quality_counters": counts,
            "fish": fish,
            "annotated_frames": annotated_frames,
            "annotated_image": annotated_frames[-1] if annotated_frames else None,
            "frames_processed": processed,
            "total_frames": total_frames or frame_index,
            "video_fps": fps,
            "analysis_mode": "video",
            "inspection_source": {"type": "uploaded_video", "frames_processed": processed, "total_frames": total_frames or frame_index},
            "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


class PartPreviewImageAnalyzer:
    """Upload-only raw part segmentation when the whole-fish model is absent.

    The available checkpoint recognizes individual Head/Body/Tail instances,
    not physical whole-fish instances.  This adapter is deliberately separate
    from ``StillImageAnalyzer`` so a test upload can never alter live tracking,
    counters, or be presented as a production whole-fish grade.
    """

    _COLORS = {
        "Class A": (76, 175, 80),
        "Class B": (255, 152, 0),
        "Class C": (170, 90, 205),
        "Rejected": (45, 45, 225),
    }

    def __init__(self, model: YoloPartModel) -> None:
        self.model = model

    @staticmethod
    def _draw_detection(frame: np.ndarray, detection: PartDetection) -> None:
        color = PartPreviewImageAnalyzer._COLORS.get(detection.grade, (160, 160, 160))
        height, width = frame.shape[:2]
        if detection.mask and len(detection.mask) >= 3:
            points = np.asarray(detection.mask, dtype=np.float32)
            if points.shape == (len(detection.mask), 2) and np.isfinite(points).all():
                points[:, 0] = np.clip(points[:, 0], 0, max(0, width - 1))
                points[:, 1] = np.clip(points[:, 1], 0, max(0, height - 1))
                polygon = np.rint(points).astype(np.int32).reshape((-1, 1, 2))
                overlay = frame.copy()
                cv2.fillPoly(overlay, [polygon], color)
                cv2.addWeighted(overlay, 0.22, frame, 0.78, 0, frame)
                cv2.polylines(frame, [polygon], True, color, 2, cv2.LINE_AA)
        left, top, right, bottom = (int(round(value)) for value in detection.bbox)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        label = f"{detection.source_class_name} {detection.confidence * 100:.1f}%"
        text_y = max(20, top - 7)
        (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        cv2.rectangle(frame, (max(0, left), text_y - text_height - 7), (min(width - 1, left + text_width + 7), text_y + 3), color, -1)
        cv2.putText(frame, label, (max(0, left) + 3, text_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

    def analyze(self, frame: np.ndarray) -> dict[str, object]:
        if self.model.model is None:
            raise RuntimeError(self.model.error or "The upload test model is unavailable.")
        try:
            frame = validate_image(frame, name="Uploaded image")
        except PreprocessingError as exc:
            raise ImageUploadError(str(exc)) from exc
        detections = self.model.predict(frame)
        annotated = frame.copy()
        quality_counters = {name: 0 for name in ("Class A", "Class B", "Class C", "Rejected")}
        for detection in detections:
            self._draw_detection(annotated, detection)
            quality_counters[detection.grade] = quality_counters.get(detection.grade, 0) + 1
        ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise RuntimeError("Unable to encode the annotated image.")
        return {
            "fish_detected": 0,
            "parts_detected": len(detections),
            "quality_counters": quality_counters,
            "model2_available": False,
            "analysis_mode": "part_preview",
            "analysis_label": "Raw part-segmentation test",
            "parts": [detection.to_dict() for detection in detections],
            "annotated_image": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
        }
