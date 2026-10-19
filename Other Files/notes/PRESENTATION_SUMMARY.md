# Consultation evidence summary

Archive: `Thesis-main (2).zip`
SHA-256: `1f49fc87b5ab4411e2dcf39d511368195522af9ea01eb7515e170fcf7fef7718`

## What was actually checked
- 1353 files inventoried; 125 source/test Python files parsed; 0 syntax errors.
- 1/6 registered checkpoint paths have bytes in this archive.
- 3 COCO split records audited; 0 cross-split hash/name flags.
- Appearance exploration: MEASURED_EXPLORATORY; 158 training Body ROIs.
- Pure-policy probe status: EXECUTED_SYNTHETIC.

## Important interpretation
Dataset label counts describe parts, not independently graded whole fish. Filename groups cannot establish physical specimen independence.
A box-like segmentation polygon is still a region of interest; do not call it a verified fish-only mask.
Appearance charts use training annotations, not model predictions; they do not prove a grading improvement.
Policy examples are synthetic inputs to the actual pure grading function; they do not prove model accuracy or temporal stability.
Old reports in saved_artifacts_index.csv were not rerun. No live FPS, new accuracy, full test-suite result, or expert approval is invented.

## Present these first
`dataset_split_summary.csv`, `grade_support_by_split.csv`, the class-support charts, and `policy_synthetic_scenarios.csv` (when enabled).
Use `training_body_roi_features.csv` and its charts only as exploratory feature evidence.
Supply `local_runtime.jsonl` for actual-computer speed evidence; supply completed truth/prediction templates for fish-level metrics.

## Questions that these outputs support
How should incomplete parts be handled? Is the proposed two-part policy acceptable? Which classes need more independent examples?
Are the current rectangular annotations sufficient, or are fish-only masks and explicit belly-defect labels needed?
What FPS/decision latency and counting/grade error rates are acceptable on the intended hardware?
