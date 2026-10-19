# Final QA report — provisional, 2026-10-18

## Decision: NOT READY

The current working tree contains useful software improvements and a passing checkpoint-free regression, but required independent scientific validation, representative target-camera measurements, a supervised soak, and a defense-machine rehearsal remain blocked. Installed runtime dependencies also conflict with the declared requirements. This is a release decision, not a claim that every software path failed. The optional expert library remains disabled and contains no real consultation material.

## Evidence

- Final isolated model-free suite: 588 passed, 6 skipped, 92 subtests, 7 warnings (`21_final_model_free.log`).
- Registered two-model CPU synthetic-frame smoke and reference-image pipeline: 2 passed (`20_checkpoint_tests.log`). These are compatibility checks; the reference image is not independent truth and no accuracy or speed claim follows.
- Local browser and focused histories, export, preview, security and lifecycle checks are indexed in `QA_TEST_MATRIX.md` and `test_summary.md`.
- Phase 11 remains **BLOCKED — EMPIRICAL VALIDATION**; phase 19 independent science and rehearsal are blocked. Raw preview, performance and soak need actual target hardware.

## Risks and gates for READY

1. Acquire independent blind fish-level expert labels and recordings with specimen/session lineage, A/B/C/Rejected support and challenging overlaps; audit independence and report separate detection, counts, grading and agreement.
2. Validate camera start/stop, tracking and paired throughput/accuracy on the actual hardware; measure real browser preview and latency, and run the documented soak.
3. Reconcile installed dependency versions with `requirements.txt`, verify checkpoint identities and actual tracker/device, and complete the target-machine rehearsal and accessibility/manual checks.
4. Re-run the QA suite and release review against the final clean, versioned state after changes; record all blockers and results.

Reference revision: `eb1e252618967b7dbce458be9ced8f3519d7bedd` on `main`, with extensive pre-existing and current uncommitted changes. This revision alone does not identify the tested working tree. No commit, deployment or migration was performed.
