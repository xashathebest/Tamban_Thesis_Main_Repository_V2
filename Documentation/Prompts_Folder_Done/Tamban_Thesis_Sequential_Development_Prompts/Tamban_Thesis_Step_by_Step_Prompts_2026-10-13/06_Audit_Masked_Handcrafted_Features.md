# PROMPT 06 - QA Existing Color, Reflectance, Texture and Shape Features

Audit the **feature-extraction implementation** in our Tamban fish-quality thesis before connecting it to grading. The prior ZIP contained `src/features/color.py`, `texture.py`, `morphology.py`, `structure.py`, and `handcrafted.py`. Confirm all paths against the current repo.

## Tasks

1. Inventory every emitted feature: HSV/RGB/LAB color, brightness, yellow/brown/dark coverage, highlights/reflectance proxies, GLCM, LBP, edge/gradient descriptors, mask-based body geometry, and human-annotated structural fields.
2. Trace data lineage from input image and fish mask / part ROI through feature calculation, table/export, training, and any live consumer. Record units, valid ranges, masking assumptions, feature names, and whether each feature is **automatic**, **manual**, **diagnostic**, or **grade-changing**.
3. Check robustness for empty or tiny masks, grayscale/alpha images, crop borders, background contamination, multiple touching fish, overexposure, shadows, and scale/resolution changes.
4. Verify reviewed structural fields are not leaked into predictive inputs unless they are actually available at inference time.
5. Add lightweight tests for determinism, dtype/NaN/inf safety, and trivial known masks/images. Do not enable feature-based grading.
6. Produce `docs/feature_inventory.md` with a precise file/function inventory and `status` for each measurement.

## Acceptance criteria

- No feature is described as a crack/hole detector without confirmed localized damage detection.
- Mask-based results are not falsely presented as equivalent to rectangular full-frame ROI measurements.
- Existing baseline grade outputs are unaffected by this audit.

## Report back

Feature table with formulas or computation notes, tests/results, non-breaking fixes (if any), and remaining measurement limitations.
