"""Explicit opt-in check of the registered local checkpoints on a synthetic frame."""
from __future__ import annotations

import os
import unittest

import numpy as np

from src.inference.model_registry import ModelRegistry
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES
from src.preprocessing.dataset_utils import project_root


@unittest.skipUnless(os.getenv("RUN_CHECKPOINT_SMOKE", "").lower() in {"1", "true", "yes", "on"},
                     "Set RUN_CHECKPOINT_SMOKE=1 and provide registered checkpoints to run real inference.")
class CheckpointSmokeTests(unittest.TestCase):
    def test_registered_models_load_and_infer_on_synthetic_frame(self):
        registry = ModelRegistry(project_root())
        detector = YoloFishDetector(registry.resolve_checkpoint_path(registry.get_default_model1_id()), device="cpu")
        model_id = registry.get_default_model2_id()
        quality = YoloQualityModel(registry.resolve_checkpoint_path(model_id), model_id=model_id, device="cpu")
        self.assertTrue(detector.load(), detector.error)
        self.assertTrue(quality.load(), quality.error)
        self.assertEqual(quality.class_names, dict(SOURCE_CLASSES))
        self.assertEqual(quality.active_model_id, model_id)
        frame = np.zeros((256, 256, 3), dtype=np.uint8)
        self.assertIsInstance(detector.detect(frame), list)
        selected, raw = quality.adapter.predict(image=frame, conf_threshold=quality.confidence_threshold, image_size=quality.image_size)
        self.assertIsInstance(selected, (list, tuple))
        self.assertIsInstance(raw, (list, tuple))


if __name__ == "__main__":
    unittest.main()
