# Prompt 06 - Validate Settings Before Any Change

**Priority/status:** P1 / REPRODUCED

**Goal:** Make multi-setting updates all-or-nothing.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/app.py` `/api/settings` (1063+), `src/api/domain.py` setters, and `src/api/camera_controls.py` hardware changes. Reproduce a request with a valid detection threshold plus invalid display settings returning HTTP 422 AFTER changing the threshold. Pre-validate all provided fields, types, ranges, model IDs, model availability, and inspection locks before applying any state changes. Define atomic apply/rollback for software settings; for hardware controls where atomicity is impossible, return granular outcomes and restore previous readbacks on failure if safe. Persist only committed settings and rotate policy/session metadata when necessary. Test mixed-validity payloads and exceptions. Preserve current defaults.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Failed requests leave software settings unchanged; success responses reflect actual applied settings and current session policy.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
