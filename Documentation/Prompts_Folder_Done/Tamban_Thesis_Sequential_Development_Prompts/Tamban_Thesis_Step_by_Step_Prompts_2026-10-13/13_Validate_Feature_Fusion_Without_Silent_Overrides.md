# PROMPT 13 - Experiment With Feature Fusion Against the Weighted Baseline

Develop an **opt-in, validation-first** way to compare our current Model 2 weighted grading against supplemental brightness/reflectance, texture and (if available) belly-defect evidence. Maintain Model 1 parent detection and Model 2 part grading as the default active architecture.

## Starting baseline

Body=0.50, Head=0.30, Tail=0.20. Missing-region weights contribute zero (they are **not** renormalized). Confidence-weighted support is not a calibrated grade probability. A possible two-part eligibility policy is separately controlled, not assumed finalized.

## Tasks

1. Read current `src/inference/grading_policy.py`, `src/inference/grading_engine.py`, feature modules and config before editing.
2. Specify experiment variants: E0 weighted model only; E1 + validated color/reflectance; E2 + texture; E3 + independently verified structural evidence; E4 combined. Do not merge datasets that do not align at the **same fish** level.
3. Implement a **pure, testable** fusion function used offline or behind a disabled feature flag. Make source feature values, thresholds, contribution/override, confidence, and rejection reason explainable.
4. Fit any thresholds, weights or meta-model using train/validation only and compare against E0. If an added feature reduces macro-F1 or increases false Rejected, keep baseline.
5. Avoid an automatic head-absence or belly-hole Rejected override until the expert rule and defect-detection reliability are independently verified.
6. Add tests proving the disabled fusion produces identical outputs to existing grading and proving invalid/missing feature evidence cannot force a class.

## Acceptance criteria

- Default production verdicts stay unchanged unless an explicitly approved flag is enabled.
- Any improvements are actually evaluated on held-out fish, with sample counts and uncertainty.
- Feature contributions are logged by version and source.

## Report back

Diff, flags, pure API, experimental metrics if available, model-free test results, and go/no-go recommendation.
