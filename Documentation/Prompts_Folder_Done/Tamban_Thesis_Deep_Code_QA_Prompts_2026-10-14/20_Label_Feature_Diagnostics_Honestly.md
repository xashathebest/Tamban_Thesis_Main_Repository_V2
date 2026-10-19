# Prompt 20 - Label Feature Diagnostics Honestly

**Priority/status:** P2 / METHODOLOGY IMPROVEMENT

**Goal:** Make sure the app never implies inactive features are grading determinants.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/features/`, `src/inference/grading_engine.py`, `configs/grading_engine.yaml`, `src/api/export.py`, and frontend diagnostic text. Several brightness/HSV metrics are collected and texture/morphology scripts exist offline, but `hsv_adjustment.enabled` and defect adjustments are disabled. Audit every field shown as 'brightness', 'shininess', 'crack', 'belly defect', or 'confidence'. Label features as ACTIVE grading evidence, DIAGNOSTIC ONLY, OFFLINE RESEARCH, or PLANNED. Do not treat generic edge density as validated belly-hole detection. Define tests that prevent false UI labels, exported data headers, or unsupported wording. Keep active grading weights unchanged unless validated feature fusion is separately authorized.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
User-facing labels match what the code actually calculates and what truly affects A/B/C/Rejected.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
