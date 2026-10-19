# Prompt 03: Make camera lifecycle and durable sessions race-safe

**Priority / phase:** P0 - data integrity

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make camera lifecycle and durable sessions race-safe.

### Inspection and implementation tasks

Inspect `src/api/app.py` start/stop routes, `src/api/camera.py` worker lifecycle and `src/api/database.py` session persistence. Recheck that the durable session is created and confirmed BEFORE any event can be emitted by the new worker.
Make stop wait for actual worker termination or return truthful STOPPING/timeout status; never report stopped if a worker is alive. Guard concurrent start, double-stop, immediate restart, camera acquisition failure, and application shutdown. Ensure old track/evidence buffers cannot contaminate a new session.
Treat file handles, camera handles, timers and subscriptions carefully. Prefer explicit state transitions: IDLE, STARTING, RUNNING, STOPPING, STOPPED, ERROR. Do not change fish-grade rules.

### Required verification

Simulate worker emitting immediately on launch, worker stalling on stop, repeated start/stop, crash while running, rapid restart, and two clients issuing start. Assert event belongs to correct session and resources are released.

### Deliverables for this step

Lifecycle state diagram, changed files and race regression tests with exact results.

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
