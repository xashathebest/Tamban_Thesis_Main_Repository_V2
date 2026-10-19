# Prompt 05 - Truthful Stop Timeout And Restart

**Priority/status:** P0 / REPRODUCED

**Goal:** Fix false stop-success responses while inference worker remains alive.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `CameraInspectionService.stop` in `src/api/camera.py` (551-566), its `start`, and `/api/inspection/stop` in `src/api/app.py` (674-682). On join timeout, `stop()` returns True even with a live worker and running state (reproduced using an unresponsive mock thread). Make the returned status truthful: indicate stopping/in-progress/timeout, keep session open until work is really finished, avoid releasing camera assets before worker exits, and prevent starting a second worker. Choose a bounded, cancellation-safe finalization mechanism; never block the API indefinitely. Add tests for successful stop, timeout, asynchronous cleanup, repeated stop, rapid restart, and persisted-session closure at the correct time.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
No endpoint claims 'stopped' while worker remains alive; no overlapping workers or misattributed events.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
