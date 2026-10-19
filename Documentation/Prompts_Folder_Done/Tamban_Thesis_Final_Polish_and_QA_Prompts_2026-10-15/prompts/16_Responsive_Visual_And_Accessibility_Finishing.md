# Prompt 16: Make the app work well on common screens

**Priority / phase:** P2 - UI polish

## Paste this prompt into your coding assistant

You are working on our existing **Tamban fish detection, counting and body-part-based quality grading thesis system**, with a FastAPI/Python backend and browser frontend. Complete **only this task**; do not run the entire polish roadmap in one response. The current repository may have changed since the October 2026 audits.

**Objective:** Make the app work well on common screens.

### Inspection and implementation tasks

Inspect design tokens, CSS, semantic HTML and JavaScript event handling. Standardize headings, button hierarchy, fonts, spacing, card padding, icons, table density, modals, forms, notifications and charts. Support 1366x768 laptop and larger desktop resolutions without clipping or oversized empty regions; support narrower screens where practical.
Add visible focus states, accurate labels, keyboard navigation, readable contrast, noncolor status cues, proper modal focus/escape behavior, touch target sizing and reduced-motion support if animations exist. Remove dead buttons and placeholder labels. Avoid gratuitous aesthetic rewrites.
Check that image preview sizing maintains aspect ratio and boxes/overlays map correctly at every responsive resolution.

### Required verification

Run frontend static checks, interaction smoke tests, manual visual review at 1366x768, 1920x1080 and narrow width. Check overlay alignment, overflow, tab order, zoom, browser console, errors and layout screenshots.

### Deliverables for this step

Polish list with before/after screenshots, accessibility checks, CSS/JS changes and remaining known issues.

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
