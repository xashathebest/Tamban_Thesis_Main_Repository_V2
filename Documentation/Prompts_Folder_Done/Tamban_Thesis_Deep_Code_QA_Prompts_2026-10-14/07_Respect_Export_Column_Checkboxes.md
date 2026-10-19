# Prompt 07 - Respect Export Column Checkboxes

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Make the exported data match the fields the operator selected.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `frontend/app.js` export form around line 1066, `src/api/app.py` `/api/export` (1150-1180), and `src/api/export.py`. The UI collects checkbox values but always sends `complete_analysis: true`, causing the backend to override the field selection with ALL columns. Fix the UI's semantics: checked fields should control the inspection rows unless the user explicitly chooses a full evidence export. Keep required metadata in clearly identified sheets or columns; do not silently add all data columns. Verify both CSV and XLSX, all-fields mode, empty selections, field order, and compatibility of the summary sheets. Add a regression that simulates user choices.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Selected-column exports contain exactly the requested inspection columns, and full exports are clearly opt-in.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
