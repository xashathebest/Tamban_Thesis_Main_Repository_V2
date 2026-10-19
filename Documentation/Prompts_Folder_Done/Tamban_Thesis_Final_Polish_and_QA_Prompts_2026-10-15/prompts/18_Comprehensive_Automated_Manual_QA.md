# Prompt 18: Build a traceable PASS/FAIL/BLOCKED quality matrix

**Priority / phase:** P0 - final QA gate

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Build a traceable PASS/FAIL/BLOCKED quality matrix.

### Inspection and implementation tasks

Create a single QA matrix covering camera start/stop/restart, video FPS/latency, counts, overlap, part assignment, A/B/C/Ungraded/Rejected, missing/obscured parts, confidence ties, multi-frame aggregation, empty detections, upload success/failure/limits, model switching, DB session ownership, persistence, history, review queue, exports, settings, accessibility, safety and app shutdown.
Run unit tests, API tests, frontend smoke tests and integration tests. Clearly separate mocked inference from real checkpoint validation and manual testing from automated testing. Tests that require unavailable model files or hardware must be BLOCKED with reason, not passed.
Record exact commands, environment and evidence links; associate every fixed defect with at least one regression test. Do not treat previously green tests as proof of new paths unless they cover them.

### Required verification

Produce machine-readable summary if possible. No unresolved silent result corruption, all executable core tests pass; critical failures block release. Preserve repeatable screenshots, test data and logs with sensitive data excluded.

### Deliverables for this step

`qa/final/qa_test_matrix.md`, `qa/final/test_summary.md`, reproduction links and blocked-test plan.

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
