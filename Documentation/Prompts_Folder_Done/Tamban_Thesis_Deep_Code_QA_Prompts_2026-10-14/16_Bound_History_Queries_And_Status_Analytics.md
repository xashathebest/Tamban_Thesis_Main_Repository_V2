# Prompt 16 - Bound History Queries And Status Analytics

**Priority/status:** P2 / PERFORMANCE RISK

**Goal:** Stop database/history growth from slowing every dashboard refresh.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `InspectionDatabase.events` in `src/api/database.py` (359-403), `_status_payload` in `src/api/app.py` (491-559), and frontend polling. Current code loads all matching SQLite rows and filters dates in Python; status refresh also recomputes analytics over durable events. Add parameterized SQL date filters, pagination, selective field queries, and incremental/cached summaries with correct invalidation when new events or manual reviews occur. Avoid stale data and maintain the same exports (complete exports can stream/batch). Benchmark with synthetic 100, 10k and 100k records. Record latency/memory before and after, not speculative FPS gain. Tests must preserve timezone/date filtering and session boundaries.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
History memory is bounded for ordinary UI calls; dashboard performance remains stable as records grow.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
