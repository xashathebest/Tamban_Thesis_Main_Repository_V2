# Tamban System - Next Steps Checklist

## P0 - Model 2 diagnosis
- [ ] Confirm exact Model 2 checkpoint path and SHA-256.
- [ ] Confirm all 12 Model 2 class names at startup.
- [ ] Run exact training image directly through Model 2 at conf 0.01, 0.05, 0.10, 0.15, 0.25.
- [ ] Save raw part predictions before grading.
- [ ] Compare direct full-frame Model 2 versus Model 1 crop -> Model 2.
- [ ] Test scale-aware crop padding.
- [ ] Test Model 2 on the original full frame with parent-part association.
- [ ] Set quality interval to 1 during diagnosis.
- [ ] Identify whether the main bottleneck is model/checkpoint, crop handoff, threshold, or temporal logic.

## P0 - Grading engine
- [ ] Remove decision-weight renormalization for missing parts.
- [ ] Compute original evidence coverage.
- [ ] Enforce minimum regions observed.
- [ ] Enforce minimum original-weight coverage.
- [ ] Load and enforce final verdict threshold from YAML.
- [ ] Add top-vs-second grade margin.
- [ ] Keep Body-only fish Ungraded initially.
- [ ] Keep nondetection/occlusion separate from Rejected.
- [ ] Update tests and README to match final behavior.

## P1 - Model 1 false positives
- [ ] Capture people/hands/candle/shadows/tools/empty-tray hard negatives.
- [ ] Build 100-300 carefully selected no-Fish negative training images.
- [ ] Create a separate non-fish validation benchmark.
- [ ] Fine-tune from the current Model 1 baseline.
- [ ] Sweep confidence threshold after fine-tuning.
- [ ] Compare real-fish recall and false positives before/after.

## P1 - UI and counts
- [ ] Draw Ungraded on live Fish boxes.
- [ ] Draw Fish ID + final grade on every parent Fish box.
- [ ] Display D (Model 1) and Q (Model 2/fusion) confidence separately.
- [ ] Add a dedicated part-label overlay.
- [ ] Show compact Ungraded reason codes.
- [ ] Add visible-fish A/B/C/Rejected/Ungraded counts.
- [ ] Keep session crossing counts in a separate section.
- [ ] Enforce A+B+C+Rejected+Ungraded = total.
- [ ] Add unit tests for counting invariants.

## P1/P2 - Model 2 data and retraining
- [ ] Populate specimen IDs and capture-session metadata.
- [ ] Collect more A and B examples, especially tails.
- [ ] Collect mixed B+C scenes in the same conditions.
- [ ] Collect overlap/occlusion examples.
- [ ] Keep each physical fish within one split.
- [ ] Match training inputs to selected runtime mode.
- [ ] Retrain/fine-tune only after P0 diagnosis.
- [ ] Report per-class and per-region metrics.

## P2 - Association and temporal stability
- [ ] Enable full-frame Model 2 experimental path.
- [ ] Assign Head/Body/Tail to parent Fish IDs with global matching.
- [ ] Allow UNASSIGNED when ambiguous.
- [ ] Add visibility states separate from grade.
- [ ] Add short-window persistence after raw Model 2 is stable.
- [ ] Expire stale evidence.
- [ ] Evaluate crowded/overlapping scenes separately.

## P2 - Repository cleanup
- [ ] Archive/remove one of the duplicate 915-file v7 COCO exports.
- [ ] Reduce redundant image copies and keep one canonical representation.
- [ ] Move fish_quality_system/ to legacy/ if not used by the active runtime.
- [ ] Remove/replace zero-byte Yolov26_First.py and Yolov26_Second.py.
- [ ] Finish or archive NotImplementedError entry points.
- [ ] Move logs/generated outputs under results/.
- [ ] Add model registry with hashes/provenance.

## P3 - Validation and thesis
- [ ] Fix all automated test failures.
- [ ] Create specimen/session-safe validation and untouched test sets.
- [ ] Tune thresholds only on validation.
- [ ] Lock model hashes, association and grading policy.
- [ ] Report Model 1 precision/recall/mAP/count error/false-positive benchmark.
- [ ] Report Model 2 per-class/region metrics.
- [ ] Report association accuracy and UNASSIGNED rate.
- [ ] Report final A/B/C/Rejected metrics and Ungraded rate.
- [ ] Include success/failure examples and honest limitations in the thesis.
