# PROMPT 14 - End-to-End Fish-Level Validation, Ablation and Evidence Report

Prepare a thesis-defensible **evaluation framework** for Tamban fish counting + quality grading after major grading/feature changes. If actual model checkpoints or truly independent expert-graded test fish are not available, **do not fabricate performance**: produce reproducible scripts and explicitly mark the validation BLOCKED.

## Tasks

1. Build a fish-level manifest including `specimen_id`, `capture_group_id`, expert final grade (A/B/C/Rejected), true missing head/tail, belly-defect labels, image/frame provenance, and any occlusion/lighting notes. Validate specimen independence across splits.
2. Separate metrics for **Model 1 detection/counting** and **end-to-end fish-level grading**. Include counting MAE, precision/recall where appropriate, per-class precision/recall/F1, macro-F1, confusion matrix, graded coverage, Ungraded frequency, false Rejected rate, and latency.
3. Evaluate E0 (confidence/50-30-20) and any validated E1-E4 feature additions on **exactly the same independent fish-level examples**. Test subgroups: A/B/C/Rejected, B vs C, overlapping fish, partially hidden parts, true missing head/tail, and different lighting.
4. Lock model checkpoints, weighting policy, thresholds and fusion flags **before** the final untouched test. Tune only on training/validation.
5. Produce scripts, machine-readable summary JSON/CSV, plots, and a concise Markdown thesis-results report. Record run seeds, software versions, model hashes, config hash, sample denominators and failure cases.
6. Verify no test-data leakage through augmented views, duplicate fish, or camera-session overlap.

## Acceptance criteria

- Metrics accurately distinguish `not run`, `blocked`, `measured`, and `simulated`.
- No claim of validated four-grade performance from a test split that lacks Class A examples.
- Passing unit tests are not presented as proof of real-world grade accuracy.

## Report back

Provide exact commands, outputs/results or blockers, a conclusion on whether feature fusion helps, and remaining scientific limitations.
