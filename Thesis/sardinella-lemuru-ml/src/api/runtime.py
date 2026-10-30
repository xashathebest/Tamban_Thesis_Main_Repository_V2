"""Runtime-mode selection for the operator dashboard."""

from __future__ import annotations

from pathlib import Path


WHOLE_FISH_MODE = "whole_fish"
PART_PREVIEW_MODE = "part_preview"
RUNTIME_MODES = (WHOLE_FISH_MODE, PART_PREVIEW_MODE)
QUALITY_INFERENCE_MODES = ("full_frame", "crop")


def resolve_runtime_mode(value: str | None = None) -> str:
    """Return a validated runtime mode, defaulting to the production path."""

    mode = (value or WHOLE_FISH_MODE).strip().lower()
    if mode not in RUNTIME_MODES:
        supported = ", ".join(RUNTIME_MODES)
        raise ValueError(f"Unsupported LEMURU_MODE {value!r}; expected one of: {supported}.")
    return mode


def resolve_quality_inference_mode(value: str | None, runtime_mode: str) -> str:
    """Resolve a safe Model 2 inference mode for the selected application mode.

    Crop-local part detection cannot establish parent ownership when more than
    one fish is visible.  The whole-fish operator workflow therefore always
    uses full-frame association, even if a stale environment setting requests
    the legacy crop mode.  Crop mode remains available to isolated tooling and
    the part-preview path where fish grading/counting is disabled.
    """

    mode = (value or "full_frame").strip().lower()
    if mode not in QUALITY_INFERENCE_MODES:
        supported = ", ".join(QUALITY_INFERENCE_MODES)
        raise ValueError(
            f"Unsupported FISH_QUALITY_INFERENCE_MODE {value!r}; expected one of: {supported}."
        )
    if runtime_mode == WHOLE_FISH_MODE and mode == "crop":
        return "full_frame"
    return mode


def resolve_part_weights_path(repo_root: Path, explicit_path: str | Path | None = None) -> Path:
    """Resolve part weights independently from the whole-fish model path."""

    path = Path(explicit_path or "models/yolov26/exp-4.pt").expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()
