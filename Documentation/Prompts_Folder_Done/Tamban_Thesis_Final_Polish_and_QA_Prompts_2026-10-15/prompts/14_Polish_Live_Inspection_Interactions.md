# Prompt 14: Make live operation clear and confidence-inspiring

**Priority / phase:** P2 - UI polish

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make live operation clear and confidence-inspiring.

### Inspection and implementation tasks

Audit the real Live Inspection page for start/stop feedback, camera selection, loading progress, model status, quality counters, tracker identifiers and grades. Create a coherent operator state machine: IDLE/STARTING/RUNNING/STOPPING/STOPPED/ERROR, matching backend truth.
Add restrained feedback for no camera, no checkpoint, warming up, slow inference, lost signal, retry, unknown grade and invalid user action. Prevent double-click races, misleading success toasts and multiple spinners. Explain grade reasons and evidence coverage without calling confidence 'accuracy'.
Keep live feed visually primary and avoid obscuring fish with too many overlapping text labels. Support color-blind-readable grade design via text + shape/label, not color alone.

### Required verification

Manual and automated workflows: first boot, start, stop, restart, unavailable camera, dropped frames, multiple fish, Ungraded, Rejected, frontend reload, API error, long-running inspection. Match backend state at all points.

### Deliverables for this step

Operator flow screenshots, state table, interaction tests and UI changes.

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
