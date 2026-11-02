"""Host-observed stage scopes; telemetry never initializes or synchronizes CUDA."""
from __future__ import annotations

import math
import sys


def milliseconds(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return None
    return round(seconds * 1000, 3) if math.isfinite(seconds) and seconds >= 0 else None


def mask_stage_metrics(context):
    """Separate CPU max-flow and mask preparation within extraction wall time."""
    stages = context.get("segmentation_stage_ms", {})
    complete = not context.get("generation_failures", 0)
    preprocessing = [stages.get(key) for key in (
        "source_resize", "raw_components", "morphology", "final_components", "native_lift",
    )]
    return {
        "segmentation_processing_ms": context.get("segmentation_ms"),
        "foreground_grabcut_ms": stages.get("grabcut") if complete else None,
        "mask_preprocessing_ms": round(sum(preprocessing), 3)
        if complete and all(isinstance(value, (int, float)) for value in preprocessing) else None,
        "mask_cache_lookup_ms": context.get("lookup_ms"),
        "segmentation_backend": ("opencv_cpu" if context.get("segmentation_backend", "opencv_cpu_grabcut") == "opencv_cpu_grabcut"
                                 else context.get("segmentation_backend", "opencv_cpu")),
        "segmentation_stage_ms": stages,
        "segmentation_child_timings_complete": complete and bool(stages),
        "segmentation_timing_note": "Failed extraction wall time is included, but incomplete child timings are unavailable."
        if not complete else "Child timings are nested in extraction wall time.",
    }


def gpu_memory_snapshot():
    """Read this process's existing allocator; never touch the training process."""
    result = {"status": "unavailable", "scope": "this_process_allocator",
              "reason": "CUDA is not initialized in this process; no initialization was requested."}
    torch = sys.modules.get("torch")
    cuda = getattr(torch, "cuda", None)
    initialized = getattr(cuda, "is_initialized", None)
    if not callable(initialized) or not initialized():
        return result
    try:
        device = cuda.current_device()
        return {"status": "available", "scope": "this_process_allocator",
                "device": f"cuda:{device}", "allocated_bytes": int(cuda.memory_allocated(device)),
                "reserved_bytes": int(cuda.memory_reserved(device)),
                "peak_allocated_bytes": int(cuda.max_memory_allocated(device)),
                "peak_scope": "process_lifetime; not reset per inspection",
                "note": "Excludes other processes and is not total GPU utilization."}
    except Exception as error:
        return {**result, "reason": "Existing CUDA allocator statistics are unavailable.",
                "error_type": type(error).__name__}


TIMING_RELATIONSHIPS = {
    "total_processing_ms": "Frame wall time; child stages overlap and must not be added to it.",
    "segmentation_processing_ms": "Extraction wall time, including CPU GrabCut and mask preprocessing.",
    "foreground_grabcut_ms": "CPU OpenCV GrabCut only; included in segmentation_processing_ms.",
    "mask_preprocessing_ms": "Resize, components, morphology and native lift; included in segmentation_processing_ms.",
    "grading_engine_ms": "Includes color, texture and grading/evidence overhead.",
    "geometry_processing_ms": "May include mask lookups/extraction; overlaps segmentation_processing_ms.",
    "structural_damage_ms": "Diagnostic wall time, possibly including shared-mask lookup; overlaps segmentation.",
    "model2_inference_ms": "Host-observed model call; shared once per full-frame inference, never sum across fish.",
}
