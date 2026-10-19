# Prompt 05: Protect per-fish identity and body-part ownership

**Priority / phase:** P0 - grading validity

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Protect per-fish identity and body-part ownership.

### Inspection and implementation tasks

Inspect `src/inference/yolo_fish_detector.py`, `src/inference/part_fusion.py`, `src/api/camera.py` and tracking configuration. Confirm which tracker is ACTUALLY running (ByteTrack or IoU fallback); do not silently mislabel the backend. Ensure dependencies needed for intended tracker are declared, or show a visible documented fallback.
For full-frame Model 2, association must consider all relevant detected parent fish, not just those scheduled to be graded. Ambiguous ownership must abstain rather than arbitrarily assign a part. Preserve independent IDs and grade histories when two fish overlap or cross paths.
Investigate camera crop mode versus full-frame; avoid speculative rewrite. Any association threshold changes require adversarial tests.

### Required verification

Create synthetic two-fish bounding-box geometry cases: close fish, crossing fish, parent excluded by scheduling, partial occlusion, same-distance ambiguous part, one parent absent, reentry, and duplicate detections. Verify there is no cross-fish grade leakage. If a real-model sample is available, record a visual case.

### Deliverables for this step

Association invariant documentation, adversarial tests, backend visibility, and changes with evidence.

## Execution rules (apply to this prompt)

- Operate on the **latest repository state**; earlier audit findings are leads to verify, not proof that a bug is still present. If already fixed, document evidence and make no unnecessary changes.
- Inspect relevant code and reproduce the issue **before** editing. Make incremental, reviewable changes; preserve working features and the two-model architecture.
- Missing large YOLO checkpoints in a shared ZIP are expected. Clearly distinguish simulated/model-free tests from actual model inference; label unavailable evaluations **BLOCKED**.
- Do not change scientific grade weights, required parts, rejection criteria, confidence interpretation, or feature-to-grade rules without explicit research approval and validation. No detected head is NOT proof the fish physically lacks a head; **Ungraded** is not **Rejected**.
- Include regression tests, full test commands/results, files changed, any API/config behavior change, and a rollback or feature flag when the behavior is significant. No fabricated measurements or claims of 100% accuracy.
- Stop and request approval before destructive dataset migrations, incompatible database/schema changes, irreversible historical result changes, or scientifically material policy decisions.

### Completion response format

1. **Finding/status:** confirmed bug, already fixed, improvement, or blocked, with source paths and short evidence.
2. **Changes made:** precise files/functions, concise before vs after.
3. **Tests:** commands, pass/fail/skip/blocked counts and relevant output.
4. **Risks and open questions:** anything requiring expert approval, camera, GPU or checkpoint.
5. **Next action:** handoff to the next numbered prompt without starting it.
