# PROMPT 03 - Fix Fish-to-Body-Part Ownership Under Overlap

Please correct only the **parent-fish-to-body-part association** logic in the current Tamban grading system. The camera can see multiple overlapping fish; Model 1 supplies parent tracks and Model 2 predicts Body/Head/Tail boxes. Confirm the actual branch for full-frame inference in `src/api/camera.py`, `src/inference/yolo_quality_model.py`, and `src/inference/association.py`.

## Known risk

Previous QA found that the live camera passed only parents currently *scheduled for grading* to the full-frame part-association step. If a visible overlapping fish had already been finalized or was not scheduled, its absence from the candidate parents could make an ambiguous part look uniquely owned by the wrong fish.

## Requested implementation

1. Reproduce the issue with a synthetic two-parent overlapping geometry and staggered grading schedules.
2. Associate part detections against **all visible eligible-to-own parts parent fish** in the frame, regardless of which parents are currently scheduled to receive new grading evidence.
3. Only **after ownership is resolved**, forward accepted parts to currently eligible grading tracks. Preserve explicit `UNASSIGNED` or `AMBIGUOUS` results when ownership cannot be determined.
4. Check coordinate transformations (full-frame vs crop), fish IDs, original image coordinates, and no cross-fish evidence reuse.
5. Add tests for two overlapping fish, one filtered from grading, ties, a part partly outside parent boxes, and single-fish stability.

## Acceptance criteria

- Removing one fish from grading eligibility does **not** change part ownership computed from the same scene geometry.
- Ambiguous parts are not forcibly assigned to whichever parent remains scheduled.
- Existing single-fish and non-overlap inference paths still pass model-free tests.

## Report back

Provide changed files, before/after association outcomes on the reproducer, tests/results, and whether real-checkpoint camera testing is still required.
