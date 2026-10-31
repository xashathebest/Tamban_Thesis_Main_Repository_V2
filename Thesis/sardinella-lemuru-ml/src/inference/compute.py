"""Shared CUDA selection, mixed-precision, and timing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class ComputeReport:
    requested_device: str
    device: str
    backend: str
    cuda_available: bool
    cuda_version: str | None
    device_name: str | None
    fp16_requested: str
    fp16_enabled: bool
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_device": self.requested_device,
            "device": self.device,
            "backend": self.backend,
            "cuda_available": self.cuda_available,
            "cuda_version": self.cuda_version,
            "device_name": self.device_name,
            "fp16_requested": self.fp16_requested,
            "fp16_enabled": self.fp16_enabled,
            "fallback_reason": self.fallback_reason,
        }


def _torch() -> Any:
    import torch

    return torch


def resolve_compute(requested: str | None = None, fp16: str | None = None) -> ComputeReport:
    """Resolve CUDA automatically and fall back to CPU without changing models."""

    requested_value = (requested or "auto").strip().lower()
    fp16_value = (fp16 or "auto").strip().lower()
    if fp16_value not in {"auto", "on", "off"}:
        raise ValueError("FISH_INFERENCE_FP16 must be 'auto', 'on', or 'off'.")
    try:
        torch = _torch()
        cuda_available = bool(torch.cuda.is_available())
        cuda_version = str(torch.version.cuda) if torch.version.cuda else None
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        requested_cuda = requested_value.startswith("cuda") or requested_value.isdigit()
        if requested_value in {"", "auto"}:
            device = "cuda:0" if cuda_available and device_count else "cpu"
        elif requested_value == "cpu":
            device = "cpu"
        elif requested_cuda and cuda_available and device_count:
            device = f"cuda:{requested_value.split(':', 1)[1] if ':' in requested_value else requested_value}" if requested_value != "cuda" else "cuda:0"
        else:
            device = "cpu"
        fallback_reason = None
        if device == "cpu" and requested_cuda and not cuda_available:
            fallback_reason = "CUDA was requested but PyTorch reports no CUDA device; using CPU."
        device_name = torch.cuda.get_device_name(device) if device.startswith("cuda") else None
        fp16_enabled = device.startswith("cuda") and fp16_value != "off"
        return ComputeReport(
            requested_device=requested or "auto",
            device=device,
            backend="cuda" if device.startswith("cuda") else "cpu",
            cuda_available=cuda_available,
            cuda_version=cuda_version,
            device_name=str(device_name) if device_name else None,
            fp16_requested=fp16_value,
            fp16_enabled=fp16_enabled,
            fallback_reason=fallback_reason,
        )
    except Exception as exc:
        return ComputeReport(
            requested_device=requested or "auto",
            device="cpu",
            backend="cpu",
            cuda_available=False,
            cuda_version=None,
            device_name=None,
            fp16_requested=fp16_value,
            fp16_enabled=False,
            fallback_reason=f"CUDA probe failed; using CPU: {exc}",
        )


def synchronize(device: str) -> None:
    """Make host timings include queued CUDA work."""

    if device.startswith("cuda"):
        try:
            _torch().cuda.synchronize(device)
        except Exception:
            return


def timed_start(device: str) -> float:
    synchronize(device)
    return perf_counter()


def timed_elapsed(started: float, device: str) -> float:
    synchronize(device)
    return perf_counter() - started
