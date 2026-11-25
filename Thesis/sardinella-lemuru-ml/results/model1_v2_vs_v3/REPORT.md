# Model 1 v2 versus v3

Internal development comparison, not an independent thesis test. V3 validation influenced checkpoint selection; v2 training exposure and specimen independence are unknown. Images from one capture date can be correlated. Image-bootstrap intervals describe this set and do not establish population significance. The legacy test set is a regression check and has already been evaluated previously.

## Same-data results

All evaluations use 768 px, batch 1, FP32, confidence floor 0.001, IoU NMS 0.70, max detections 132, and the same software/device. AP uses Ultralytics native validation. Native validation and application prediction use different image padding; fixed-threshold P/R/F1 and count metrics therefore come from a separate pass through the application's single-frame BGR prediction path. Counts use confidence-ordered one-to-one matching at IoU 0.50. Direct predictions at 0.50 and 0.70 are checked against filtered predictions on the first three images per model and dataset.

| Dataset | Confidence | Model | Precision | Recall | F1 | Exact count accuracy | mAP@50 | mAP@50–95 | TP | FP | FN |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development (332 images) | 0.50 | v2 | 93.78% | 69.37% | 79.75% | 20.78% | 88.63% | 68.55% | 1735 | 115 | 766 |
| development (332 images) | 0.50 | v3 | 95.37% | 75.81% | 84.47% | 33.43% | 89.74% | 73.02% | 1896 | 92 | 605 |
| development (332 images) | 0.70 | v2 | 95.70% | 56.94% | 71.40% | 13.55% | 88.63% | 68.55% | 1424 | 64 | 1077 |
| development (332 images) | 0.70 | v3 | 97.29% | 64.49% | 77.57% | 24.70% | 89.74% | 73.02% | 1613 | 45 | 888 |
| legacy (295 images) | 0.50 | v2 | 84.85% | 94.55% | 89.44% | 40.34% | 96.67% | 85.56% | 3400 | 607 | 196 |
| legacy (295 images) | 0.50 | v3 | 82.72% | 91.60% | 86.94% | 32.20% | 92.45% | 74.42% | 3294 | 688 | 302 |
| legacy (295 images) | 0.70 | v2 | 90.07% | 91.85% | 90.95% | 41.69% | 96.67% | 85.56% | 3303 | 364 | 293 |
| legacy (295 images) | 0.70 | v3 | 88.82% | 84.40% | 86.55% | 32.54% | 92.45% | 74.42% | 3035 | 382 | 561 |

Exact count accuracy means the fraction of images with the correct number of detections. It is not ordinary classification accuracy; false positives and missed fish can cancel. No true-negative object population is defined, so classification accuracy is not reported.

## Selection evidence

At least +2 percentage points development mAP50–95, better F1 at both deployed thresholds with descriptive paired intervals above zero, no precision loss above 1pp, and no legacy mAP/F1 loss above 2pp.

Candidate supported by practical gate: **False**. This script does not deploy it.

- PASS: development_map50_95_gain_at_least_2pp
- PASS: development_f1_improves_at_0.50
- PASS: development_precision_loss_at_most_1pp_at_0.50
- PASS: development_paired_f1_interval_above_zero_at_0.50
- PASS: development_f1_improves_at_0.70
- PASS: development_precision_loss_at_most_1pp_at_0.70
- PASS: development_paired_f1_interval_above_zero_at_0.70
- FAIL: legacy_map50_95_loss_at_most_2pp
- FAIL: legacy_f1_loss_at_most_2pp_at_0.50
- FAIL: legacy_f1_loss_at_most_2pp_at_0.70

## Uncertainty

The plotted 95% intervals use 10,000 paired image bootstrap samples and seed 42, keeping both model outputs together for each sampled image. They do not account for unknown specimen correlation, v3 checkpoint selection, or unknown v2 training exposure. With only three validation capture dates (one containing one image), broad statistical significance cannot be established. No population p-value is claimed.

## Reproduction and evidence

`evaluation_manifest.json` records image/label hashes, datasets, software and settings. `evaluations/` contains checkpoint hashes, unrounded prediction boxes/scores and ground truth. `comparison.json` holds aggregates and per-image counts. Every graph is provided as PNG and PDF; `metrics.csv` and `confidence_sweep.csv` contain plotted values.

## Application selection

Model 1 **V2 remains active**. V3 was not promoted because the legacy regression gate failed. V2 was not archived because the system still uses it. The complete V3 checkpoint is preserved at `models/fish_detector/candidates/v3/model1_v3_yolo26s_best.pt`, with its SHA-256 and source recorded alongside it. The registry, runtime thresholds, Model 2, and grading settings were preserved.

Verification: 43 targeted comparison/pipeline/registry/integrity tests passed. The running application at port 8001 was checked to identify its actual selected checkpoint.
