# Prompt 17 - Review Past Sessions Without Losing AI Truth

**Priority/status:** P2 / IMPROVEMENT

**Goal:** Make historical review operations precise and auditable.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `/api/reviews/{track_id}` and `/api/reviews` in `src/api/app.py`, `InspectionDatabase.apply_manual_review`, history filters, and analytics. The review route defaults to the current session and an unqualified track ID; older selected sessions cannot reliably be reviewed through the same interface. Add an explicit session-qualified review path or payload with validation and backward-compatible current-session default; guard against accidentally reviewing a reused track ID in another session. Preserve original AI grade/evidence and separately store manual grade, reviewer (if available/appropriate), timestamp, and audit provenance. Make analytics label whether a value is AI accuracy or reviewed outcome. Tests for current/past IDs, unknown session, repeat review, clear override, and unchanged AI result.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Operator can review the correct historical fish, and reports distinguish AI predictions from human corrections.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
