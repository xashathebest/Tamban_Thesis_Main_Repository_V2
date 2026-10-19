# Prompt 17: Remove hidden maintenance and uptime risks

**Priority / phase:** P2 - reliability

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Remove hidden maintenance and uptime risks.

### Inspection and implementation tasks

Inspect active modules for duplicate logic, unused imports, hidden global mutation, dead configs, hardcoded paths, unbounded buffers, excessive per-frame logging, stale TODOs, synchronous disk reads in hot loop, swallowed exceptions and worker leaks. Identify any stale frontend API assumptions.
Prefer small refactors with clear behavior preservation. Do NOT remove legacy experiments or research datasets until provenance/usage is established and approved. Pin useful dependencies, document Windows launch commands and data directories.
Review repeated start/stop, hundreds of uploads, large history, hour-long session, stale browser tabs and interrupted writes. Check data files/SQLite transactions and cleanup when killed.

### Required verification

Add leak/regression tests, 30-60-minute soak-test script where available, record memory, CPU, file handles, active threads and request latency over time; clearly mark actual soak test BLOCKED if not run.

### Deliverables for this step

`qa/final/stability_maintenance.md`, small changes, run logs and repeatable soak-test procedure.

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
