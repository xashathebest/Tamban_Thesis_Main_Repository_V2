import cv2
import numpy as np

from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.part_types import PartDetection
from src.inference.preprocessing import generate_runtime_fish_mask


def _fish_crop():
    image = np.full((120, 180, 3), 35, dtype=np.uint8)
    cv2.ellipse(image, (90, 60), (65, 30), 0, 0, 360, (170, 130, 90), -1)
    return image


def test_runtime_mask_is_nonempty_and_validated_for_features():
    mask, metadata = generate_runtime_fish_mask(_fish_crop())

    assert mask is not None
    assert mask.shape == (120, 180)
    assert metadata["status"] == "validated_for_features"
    assert metadata["mask_validated_for_cracks"] is False


def test_grading_payload_uses_runtime_mask_without_enabling_adjustments():
    engine = WeightedGradingEngine(GradingConfig(image_diagnostics_enabled=True))
    image = _fish_crop()
    mask, _ = generate_runtime_fish_mask(image)
    parts = [PartDetection.from_source_class(0, 0.9, (20, 40, 160, 80))]

    verdict = engine.evaluate(1, image, parts, stabilize=False, fish_mask=mask)
    supporting = verdict.to_dict()["supporting_image_measurements"]

    assert supporting["texture"]["status"] == "measured"
    assert supporting["texture"]["mask_validated_for_cracks"] is False
    assert supporting["used_for_final_grade"] is False
    assert verdict.adjustments == ()
