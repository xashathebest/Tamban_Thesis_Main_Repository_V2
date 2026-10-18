# PROMPT 02 - Fix Temporal Grading Acceptance and Recovery

Work only on temporal quality-evidence correctness in the **current Tamban thesis repository**. Do not change the fish-grade weights or introduce new visual features. Model 1 detects parents; Model 2 supplies grade-aware body-part predictions. Check current code before editing, especially `src/inference/grading_engine.py`, config, and tests.

## Problem to reproduce

Previous QA found that a frame with Body+Head evidence followed by an **empty part-detection frame** could satisfy a two-frame gate and still produce Class A. Temporary ambiguity/parent uncertainty flags also remained sticky forever for a track, even after clear observations.

## Changes requested

1. Write failing model-free regression tests for both cases **before** making the fix. Include data for body-only, body+head, body+tail, and no body.
2. Define and implement **evidence-bearing frame** acceptance: a frame only counts toward the required temporal grading evidence if it contains the policy-required reliable parts/observations. Make the minimum configurable and report how it is counted.
3. Separate historical ambiguity warnings from the active readiness gate. Specify a recent-observation/recovery policy that permits grading after sufficient good frames without erasing audit history; ensure track identity changes never inherit the previous fish's evidence.
4. Verify graceful handling of short occlusions, empty frames, false parts, expired tracks, and repeated frames from the same source.
5. Do not falsely upgrade uncertain observations into positive evidence or force a grade when required evidence is missing.

## Acceptance criteria

- One good frame + one empty frame **cannot** pass a two-evidence-bearing-frame requirement.
- Enough later unambiguous evidence can recover from a transient failure under the documented policy.
- Model-free tests pass without requiring actual `.pt` checkpoints.

## Report back

List changed functions/files, the new temporal definition, exact tests/results, and any still-unresolved tradeoffs in Ungraded coverage.
