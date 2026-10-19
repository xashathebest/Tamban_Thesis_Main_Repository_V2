# Prompt 08: Make saved data faithful to what happened

**Priority / phase:** P1 - data correctness

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make saved data faithful to what happened.

### Inspection and implementation tasks

Inspect `src/api/database.py`, `src/api/app.py` history/manual-review/export endpoints and `frontend/app.js`. Ensure each session persists effective model IDs, checkpoint identity, runtime settings, grading policy version and relevant evidence. Old exports MUST use historical session settings, not today's `_status_payload()` grading rules.
Make user-selected export columns effective end-to-end; investigate frontend `complete_analysis: true` overriding checkboxes. Ensure historical review routes require or unambiguously resolve session ID along with track ID. Fix lookup hard limits, duplicate record risks, empty CSV/XLSX, timezone and field-label consistency.
Never silently rewrite old AI predictions or convert operator review decisions into claimed model predictions. Preserve an audit trail.

### Required verification

Round-trip test selected export columns, export past session after settings changed, duplicate track ID in two sessions, missing session, review and undo/review audit trail, large history pagination, special chars and timestamps.

### Deliverables for this step

Schema/path changes with migration plan, export samples, tests, and before/after user workflow.

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
