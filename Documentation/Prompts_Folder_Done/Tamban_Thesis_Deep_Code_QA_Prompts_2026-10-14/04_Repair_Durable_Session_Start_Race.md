# Prompt 04 - Repair Durable Session Start Race

**Priority/status:** P0 / REPRODUCED

**Goal:** Ensure every fish event is written to the session that captured it.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/app.py` `start_inspection` (around 666-671) and `_persist_tracking_event` (250-260), plus `InspectionSessionContext` in `src/api/database.py` (459-508). `service.start()` begins the worker before `inspection_sessions.start`, so an early event can be saved under the prior closed session; this was reproduced with controlled callback interleaving. Design an atomic startup handshake: register/commit the new session before the worker can emit events; roll back / close safely when startup fails. Prevent recording events under closed prior sessions; define late-event behavior clearly. Handle double-start requests, rapid stop/start, exceptions while creating the session, worker errors, and shutdown. Do not delete or rewrite existing histories.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Race test proves first event belongs to new session and no previous session receives it; failures leave consistent worker/session state.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
