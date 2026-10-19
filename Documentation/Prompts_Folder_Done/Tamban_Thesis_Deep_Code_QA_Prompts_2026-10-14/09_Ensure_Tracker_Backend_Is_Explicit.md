# Prompt 09 - Ensure Tracker Backend Is Explicit

**Priority/status:** P1 / SOURCE-CONFIRMED

**Goal:** Avoid silently changing fish-tracking algorithms because a dependency is absent.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/inference/yolo_fish_detector.py` (238-246), `requirements.txt`, tracking tests, and tracker diagnostics. With `lap` unavailable, the code falls back to `_IoUTracker` despite a `bytetrack.yaml` default. Identify supported OS/platform install options (for example, explicit optional dependency/group for lap) and document which tracker actually runs. If fallback remains acceptable, expose a prominent runtime status/warning and track-backend session metadata so reports never claim ByteTrack incorrectly. If strict ByteTrack is required for research, fail cleanly rather than silently switching. Test startup/backend selection and overlap-ID consistency with synthetic tracks; benchmark on the user's computer separately.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Operators can tell whether ByteTrack or fallback is running; no hidden tracker change across deployments.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
