# Prompt 20: Close the loop with a defensible readiness decision

**Priority / phase:** P0 - last

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Close the loop with a defensible readiness decision.

### Inspection and implementation tasks

Read outputs of prior prompts and inspect latest code revision. Re-run model-free automated tests and every available test requiring actual models, complete UI regression, load/resilience tests, export checks and same-hardware performance benchmark. Inspect documentation for mismatch with real config, grade-policy claims and feature status.
Prepare final artifacts: `FINAL_QA_REPORT.md`, `CHANGES_IMPLEMENTED.md`, `PERFORMANCE_REPORT.md`, `QA_TEST_MATRIX.md`, `UI_UX_REFINEMENT_REPORT.md`, `PRE_DEFENSE_CHECKLIST.md`, with precise file paths, reproduction steps and measurements. Include a changelog, known limitations, deployment instructions, model checkpoint requirements, safe rollback and version snapshot.
Assign exactly one decision: READY (all required evidence complete), CONDITIONALLY READY (controlled demonstration possible with stated blocks), or NOT READY (critical unresolved defects). Define what blocks moving to READY. Never declare release green simply because unit tests pass or user has no checkpoints in shared ZIP.

### Required verification

Check that all claims are evidenced, critical defects fixed or explicitly unresolved, skip/block counts are correct, FPS is labeled accurately, and expert vs experimentally validated rules are distinguished. Verify artifacts exist and links resolve.

### Deliverables for this step

Final QA report bundle, exact readiness call, top remaining risks and recommended demo settings.

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
