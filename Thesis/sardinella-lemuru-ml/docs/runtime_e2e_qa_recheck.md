# Final QA recheck

Fresh recheck completed November 3, 2026 against the current working code. **All executed acceptance checks passed. No additional production-code fixes were needed.**

| Check | Fresh result |
|---|---|
| Full regression suite | 1,715 passed, 12 skipped, 7 warnings, 127 subtests passed; zero failures in 43.50 seconds |
| Source-bound replay of the 24 actual-image cases | Zero invariant/arithmetic failures; identical native accepted parts, grades, supports and weights |
| Actual CPU HTTP analysis and Chrome | 46 checks plus four lifecycle checks and mobile layout passed |
| Final frontend with the actual saved image/masks/results | 16 checks passed; zero fetches or model reruns |
| Complete CSV/XLSX round trip | All 347 fields for nine fish matched or reconstructed exactly; zero lost evidence |
| View-switch instrumentation | One Model 1 call, one Model 2 call, one shared SAM embedding; zero GrabCut calls throughout the actual inspection/view/export checks |
| Native output alignment | Maximum serialized box-rounding difference 0.004897 pixels; raw native traces retained |
| Checkpoint and inference integrity | Full hashes unchanged; protected predictor ASTs unchanged; CUDA stayed uninitialized |
| JavaScript syntax and diff whitespace | Passed |

The real browser checks cover Bounding Boxes / Fish Masks, visible shaded masks, opacity, highlighting, zoom, Model 1/Model 2 visibility, anatomical debugging, card selection, review indicators, loading with elapsed time, errors, reset, and export consistency. All 45 oversized evidence values are preserved using the documented Excel chunk references.

The fresh actual HTTP case retains nine parents, 17 raw anatomical candidates, nine masks and eight masks requiring review. Its final results remain one Class C and eight Ungraded. The 24-case replay also preserves the previously reported Ungraded counts. This is expected conservative behavior where required ownership is unavailable, not a failing software check. Models, thresholds, grading weights and calibration gates were not changed to increase grading coverage.

The separate read-only audit found no additional defect in required-pair checks, deterministic crop selection, native/crop rendering, source checks, or mask success/error reporting. It also checked tie ordering and coordinate-translation invariance.

Evidence is under `results/qa/runtime_e2e/recheck/`:

- `full_tests.log`, `replay.log`, `comparison.log`, and `replay_acceptance.json`.
- `api_browser.log`, `recorded_browser.log`, and `summary.json`.
- Refreshed actual result and export reports, CSV/XLSX files, and browser artifacts.

The current code was exercised on an isolated fresh CPU server; the existing live service and training processes were preserved. Physical-camera behavior, deployment-GPU performance, and biological grading accuracy were not certified by this recheck. Accuracy still requires independent per-fish expert labels.

See [the end-to-end validation report](runtime_e2e_validation.md) for root causes, the unchanged before/after grading coverage, remaining ownership/detection bottlenecks, exact production files, and reproducible commands.
