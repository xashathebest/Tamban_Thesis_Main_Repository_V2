# PROMPT 01 - Re-audit the Current System and Establish a Baseline

You are working in my **Tamban dried-fish grading thesis** repository. It has two distinct YOLO-related components: Model 1 detects/counts parent fish; Model 2 emits grade-aware detections of Body, Head, and Tail; a separate weighted decision rule outputs A, B, C, Rejected, or Ungraded. The repository may intentionally omit large `.pt` model weights.

## Scope - inspection first, no feature implementation

1. Identify the **actual** entrypoints for image upload, camera inspection, full-frame/crop Model 2 inference, fish-part ownership association, temporal aggregation, final grading, frontend display, and export.
2. Trace all grading signals and show which ones **change the verdict** versus which are merely logged. Start with `src/inference/grading_engine.py`, `src/inference/grading_policy.py`, `configs/grading_engine.yaml`, `src/api/camera.py`, `src/features/`, and tests, but confirm the current file layout instead of assuming it.
3. Check default weights, required regions, region-count and frame-count thresholds, body/head/tail behavior, and Ungraded vs Rejected semantics. Identify all places where a missing detection might be mistaken for missing anatomy.
4. Run the documented **model-free** unit tests where dependencies allow. If tests need absent checkpoints, identify their dependency and keep checkpoint-backed tests separate; do not claim a broken model.
5. Produce a brief baseline inventory and risk-ranked defects list with precise file/function references. Do not edit runtime behavior in this step.

## Acceptance criteria

- Every row in the inventory is marked `LIVE VERDICT`, `LIVE DIAGNOSTIC`, `OFFLINE RESEARCH`, or `NOT IMPLEMENTED` with file evidence.
- Report actual passing/failing/skipped counts and commands; never invent metrics.
- Highlight any dependency blocking an accurate audit or test.

## Report back

Provide the current inference flow, confirmed file/function map, exact baseline test commands/results, and a prioritized list of next code changes. Stop after this prompt.
