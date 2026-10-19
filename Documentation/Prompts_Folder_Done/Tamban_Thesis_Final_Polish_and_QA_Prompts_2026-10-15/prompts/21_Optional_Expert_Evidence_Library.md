# Prompt 21: Optional consent-respecting consultation evidence UI

**Priority / phase:** OPTIONAL - only if desired

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Optional consent-respecting consultation evidence UI.

### Inspection and implementation tasks

ONLY if requested by research team, inspect the latest sidebar routing and existing evidence storage before adding an `Expert Validation` read-only page. Implement short consultation video snippets with descriptive titles, original recording name/timestamp, transcript excerpt, approval status, and links to which grading assumptions are supported.
Treat annotator statements as qualitative evidence. A clip stating body matters more does NOT establish the mathematical 50/30/20 weights. Keep original recordings secure; display only permitted clips and obtain consent for in-app/panel presentation. Prefer storing a compact metadata manifest to hardcoding media URLs. Avoid shipping personally identifying or unconsented raw recording files in a public repo.
Do not let this optional UI alter any AI inference or grading decisions.

### Required verification

Test missing/unavailable clip, restricted access, transcript loading, keyboard player control, deep link and correct timestamp metadata. User can navigate back to Live Inspection without changing inspection state.

### Deliverables for this step

Small evidence-library component, metadata schema, permission checklist and tests, or a documented decision not to implement.

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
