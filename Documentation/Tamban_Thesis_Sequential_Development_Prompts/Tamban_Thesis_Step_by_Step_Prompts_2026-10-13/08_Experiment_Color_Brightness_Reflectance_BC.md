# PROMPT 08 - Research Experiment: Brightness, Color and Reflectance for B vs C

Build a **reproducible offline experiment**, not a production grade override, to test whether brightness/color/shininess features improve differentiation of Tamban Class B versus Class C. The current code has color and reflectance proxies (see `src/features/color.py`, `src/features/handcrafted.py`). Reuse rather than reinvent them.

## Tasks

1. Identify genuinely expert-labeled fish-level B/C samples, specimen/capture-group IDs, camera/lighting conditions, and fish masks. Report actual class counts. If independent or adequate labels do not exist, provide a runnable experiment scaffold and **stop short of performance claims**.
2. Compute candidate features: HSV Value and Saturation, LAB lightness/color channels, bright-highlight coverage, specular-region fraction, yellow/brown/dark coverage, and reasonable controls for exposure/white balance.
3. Compare a **Model 2-only** baseline (where Model 2 outputs can be aligned fish-by-fish) against candidate features alone and an optional offline combined baseline. Label any missing baseline honestly.
4. Split/group by specimen or capture session before training/tuning to prevent leakage; never split augmented views of the same fish across train/validation/test.
5. Report per-class precision/recall, macro-F1, B-vs-C confusion, false predictions, sample sizes, and lighting sensitivity. Plot distributions showing overlap, not just averages. Avoid training on the final untouched test set.
6. Generate one Markdown report and reproducible scripts/configs with saved seeds and feature metadata.

## Acceptance criteria

- Dataset availability and grouping are explicit.
- All thresholds and choices are fitted only using training/validation data.
- No production grading weights or thresholds are changed by this experiment.

## Report back

Exact datasets, scripts, commands, plots/reports generated, quantitative results if genuinely measured, and whether the evidence supports integration.
