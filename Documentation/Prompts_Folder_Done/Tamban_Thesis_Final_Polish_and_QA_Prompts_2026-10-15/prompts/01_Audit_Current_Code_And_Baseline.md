# Prompt 01: Fresh repository audit and evidence baseline

**Priority / phase:** P0 - start here

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Fresh repository audit and evidence baseline.

### Inspection and implementation tasks

Inspect `README.md`, `src/api/`, `src/inference/`, `src/features/`, `frontend/`, `configs/`, model registry, dataset/report manifests, and `tests/`. Trace the active flow from camera or upload to tracking, parent-part association, grading, persistence, and UI.
Cross-check earlier audit findings against CURRENT code: model-switching, session-start race, stop timeout, partial settings updates, stale exports, tracker fallback, association, temporal gating, performance, and feature claims. Mark each CONFIRMED / FIXED / PARTIAL / NOT REPRODUCIBLE / BLOCKED.
Run syntax checks, model-free tests, and available static checks. Report checkpoint-dependent failures separately; do not assume missing large `.pt` files are corrupt.
Capture git revision/working tree, Python/library versions, OS and hardware if discoverable, configuration, selected models and tracker backend. Save current outputs before modifying any code.

### Required verification

Re-run exact baseline commands, record pass/fail/skip counts, collect stack traces, reference line numbers and reproduction steps. Differentiate observed behavior from conjecture; mark real-camera and real-model checks BLOCKED if unavailable.

### Deliverables for this step

`qa/final/baseline_inventory.md`, `qa/final/baseline_tests.md`, prioritized risk register, reproducible commands, and an explicit list of no-change findings.

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
