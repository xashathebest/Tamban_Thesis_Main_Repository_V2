"""Static regression checks for the operator Model 2 selector."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_model_selector_is_labeled_and_exposes_live_status() -> None:
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert '<label for="model2-selector">Choose Model 2</label>' in markup
    assert 'id="model2-selector"' in markup
    assert 'aria-describedby="model2-selector-status"' in markup
    assert 'id="model2-selector-status"' in markup

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    for model_id in ("yolo26m_partdet", "effnetv2m_retinanet", "fasterrcnn_r50fpn_v2"):
        assert f'"{model_id}"' in script
    assert "Current active model:" not in script
    assert "model.name || model.display_name" in script


def test_model_selector_uses_registry_and_safe_switch_endpoint() -> None:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for model_id in ("yolo26m_partdet", "fasterrcnn_r50fpn_v2", "effnetv2m_retinanet"):
        assert f'"{model_id}"' in script
    assert 'fetch("/api/models", { cache: "no-store" })' in script
    assert 'fetch("/api/models/select", {' in script
    assert "option.disabled = !modelCanGrade(model);" in script
    assert "Stop inspection before changing Model 2." in script
