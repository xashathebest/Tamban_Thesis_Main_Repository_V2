"""Hardware capability is not numerical validation of checkpoint precision."""
from types import SimpleNamespace
import pytest
from src.inference import compute


def fake_torch(available=True):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available,
        device_count=lambda: 1 if available else 0, get_device_name=lambda _: "Synthetic GPU"),
        version=SimpleNamespace(cuda="synthetic-test-only"))


@pytest.mark.parametrize("fp16_mode", ["auto", "on", "off"])
def test_cuda_uses_full_precision_until_model_specific_validation(monkeypatch, fp16_mode):
    monkeypatch.setattr(compute, "_torch", lambda: fake_torch())
    report = compute.resolve_compute("auto", fp16_mode)
    assert report.device == "cuda:0"
    assert report.fp16_enabled is False
    assert "FP32" in report.precision_status


def test_cpu_fallback_reports_unavailable_cuda(monkeypatch):
    monkeypatch.setattr(compute, "_torch", lambda: fake_torch(False))
    report = compute.resolve_compute("cuda:0", "auto")
    assert report.device == "cpu" and report.cuda_available is False
    assert report.fallback_reason and report.fp16_enabled is False


def test_invalid_cuda_ordinal_does_not_misreport_available_hardware(monkeypatch):
    monkeypatch.setattr(compute, "_torch", lambda: fake_torch())
    report = compute.resolve_compute("cuda:9", "off")
    assert report.device == "cpu" and report.cuda_available is True
    assert report.fallback_reason


def test_failed_cuda_probe_preserves_usable_cpu_path(monkeypatch):
    def fail(): raise RuntimeError("Synthetic driver failure")
    monkeypatch.setattr(compute, "_torch", fail)
    report = compute.resolve_compute("auto", "auto")
    assert report.device == "cpu" and report.fp16_enabled is False
    assert "probe failed" in report.fallback_reason


def test_runtime_status_reuses_the_loaded_models_compute_reports(monkeypatch):
    import importlib
    app = importlib.import_module("src.api.app")
    report = compute.ComputeReport("cpu", "cpu", "cpu", False, None, None, "off", False)
    monkeypatch.setattr(app, "model", SimpleNamespace(compute=report, device="cpu"))
    monkeypatch.setattr(app, "quality_model", SimpleNamespace(compute=report, device="cpu"))
    def unexpected_probe(*args): raise AssertionError("Loaded model compute should be reused")
    monkeypatch.setattr(app, "resolve_compute", unexpected_probe)
    result = app._device_report()
    assert result["model1_compute"] == result["model2_compute"] == report.to_dict()
