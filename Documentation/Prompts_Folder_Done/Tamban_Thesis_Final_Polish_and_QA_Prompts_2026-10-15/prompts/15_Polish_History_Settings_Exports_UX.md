# Prompt 15: Make secondary workflows predictable and self-explanatory

**Priority / phase:** P2 - UI polish

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make secondary workflows predictable and self-explanatory.

### Inspection and implementation tasks

Inspect History, Review Queue, Analytics, Export and Settings in frontend. Unify layouts and naming. Present one clear route to a task, while retaining deep links/legacy routes if used. Consolidate display toggles with one source of truth; distinguish visual-only toggles from scientific grading thresholds.
Provide searchable and paginated history, clear session metadata, deterministic review actions with confirmation/undo where possible, disabled export until valid selection, progress/completion/error feedback, and precise selected-column behavior. Show whether a grade is AI predicted, human reviewed, or uncertain.
Ensure model selectors cannot imply changes to an active camera session. Make settings validation errors specific, preserve user input on error and only commit on successful API response.

### Required verification

Test empty/large history, filter + export, historical review with same `track_id` across sessions, stale network response, failed export, settings 422, keyboard-only use, and refresh persistence.

### Deliverables for this step

UI field map, end-to-end workflow tests, and screenshots.

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
