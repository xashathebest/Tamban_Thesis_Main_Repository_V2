# Grading evidence and image feature claims

This describes the supplied implementation, not independent validation of the models or grading policy. The default original weights are Body 50%, Head 30% and Tail 20%; when Tail is unavailable, the configured adaptive policy uses Body 62.5% and Head 37.5%. See the README for the policy and its limitations.

Runtime update, 2026-11-23: [calibrated decision fusion](intelligent_decision_fusion.md)
is implemented for size, cracks, color/brightness and texture. No reference
calibration is installed, so these supporting features currently have zero
effective scoring weight. Native-mask integration tests establish software
contribution behavior only; they do not establish improved fish-grading accuracy.

Grading QA, 2026-11-23: configuration 4.1 requires a unique winning score,
including when the configured minimum margin is zero. Exact anatomical or fused
ties and differences within floating-point roundoff require review. Optional
geometry/structural score transfers that would create a tie are withheld; tied
remaining grades after a structural eligibility restriction require review.
Unavailable inference and rejected
frame-quality evidence remain holds even with retained scores; offline replay
preserves unavailable flags from saved nested fields. A configured Rejected
override reports weighted Rejected support separately from the provisional
winner and the part's confidence. Previous calibrated artifacts require refitting
under `whole_fish_feature_validation_v4`. The existing weights and numerical
acceptance thresholds are retained.

| Category | Fields and present use | Limits |
| --- | --- | --- |
| ACTIVE grading evidence | Model 2 region/class evidence and its weighted support, coverage and configured acceptance gates (`src/inference/grading_engine.py`, `src/inference/grading_policy.py`). Model 1 detection confidence selects detections and tracks; it is not a grade score. | Support scores are not measured accuracy or calibrated probabilities. Model 2's Rejected region classes are model evidence, not a named crack or belly-hole detector. |
| DIAGNOSTIC ONLY | Per-region and whole-fish hue, saturation, HSV value, yellow, dark-patch and highlight proxies (`src/inference/grading_engine.py` and `src/features/color.py`); camera grayscale brightness and contrast (`CameraService._update_image_statistics`). | Grading uses no HSV or defect adjustment, even if those configuration switches are set. Runtime colour measurements use rectangular regions that can include background; highlight is not validated shininess, and yellow is not a diagnosed defect. Camera brightness is a grayscale mean in the 0–255 image range, distinct from HSV value. |
| DIAGNOSTIC ONLY / optionally configured gate | Sharpness and representative-frame scores help review; explicitly configured frame-quality filtering can exclude evidence before grading (`GradingConfig`). | Default sharpness filtering is disabled. Representative-frame selection itself does not change the grade. |
| OFFLINE RESEARCH | Mask-based colour, texture, morphology and structural feature extraction (`src/features/handcrafted.py`, `texture.py`, `morphology.py`, `structure.py`). | These offline features do not supply a live grade. A generic edge-density proxy does not establish a crack, belly hole, or any validated anatomical defect. |
| CALIBRATION-GATED | The implemented 70/15/5/5/5 Model 2/size/cracks/color/texture fusion, with per-feature reliability, numeric score contributions and review safeguards. | Requires verified source-bound measurements and specimen-separated calibration/validation. The installed default contributes no supporting feature weight. Candidate dark-line extraction is not validated structural defect detection. |
| PLANNED / UNVALIDATED | Independently validated belly-defect and crack detection. | Current detectors do not provide trained named belly-defect or crack classes. No grading-accuracy claim follows from candidate image processing or research scripts. |

`configs/grading_engine.yaml` leaves HSV and defect adjustments disabled. The current engine contains no validated adjustment rule even if a switch is enabled. Changing that behavior requires a separately authorized, independently evaluated policy; this document is not approval to change it. Historical exports retain their recorded data, and diagnostic headers describe the present implementation rather than proving an unknown historical model's behavior.
