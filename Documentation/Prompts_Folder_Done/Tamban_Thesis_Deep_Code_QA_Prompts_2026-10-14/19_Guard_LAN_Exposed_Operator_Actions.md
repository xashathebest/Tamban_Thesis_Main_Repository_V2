# Prompt 19 - Guard LAN Exposed Operator Actions

**Priority/status:** P2 / CONDITIONAL SECURITY RISK

**Goal:** Protect camera and grading controls if the app is ever hosted beyond localhost.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/__main__.py`, `src/api/app.py` routes controlling inspection/models/manual reviews/exports/debug, and `frontend/` origin assumptions. Default host is 127.0.0.1 (local only), but `LEMURU_HOST` can expose endpoints to a LAN without built-in authentication or CSRF guard. Do not overstate risk in local-only mode. Add an opt-in safe LAN deployment profile: access token/session authentication and role-scoped authorization for state-changing routes; privacy-aware history/export access, safe debug defaults, secure cookies/CSRF if browser sessions are used, and explicit warnings on 0.0.0.0 binds. Do not break standard localhost mode. Add HTTP tests for auth enabled/disabled, unauthorized writes, and allowed read access.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Local mode remains simple; network mode cannot permit unauthenticated changes to live grades or model settings.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
