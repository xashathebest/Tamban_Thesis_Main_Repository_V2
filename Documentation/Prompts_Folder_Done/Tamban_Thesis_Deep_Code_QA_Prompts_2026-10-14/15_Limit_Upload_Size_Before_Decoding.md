# Prompt 15 - Limit Upload Size Before Decoding

**Priority/status:** P2 / CONDITIONAL RISK

**Goal:** Prevent large or malformed uploads from exhausting memory.

## Copy/paste implementation request

I am improving an existing two-model dried tamban fish inspection thesis application. Please inspect the code before making changes and implement ONLY the task described in this prompt.

Inspect `src/api/app.py` `/api/analyze-image` and `src/api/image_analysis.py` `decode_uploaded_image`. A declared Content-Length guard exists, but the endpoint uses unbounded `await request.body()` when the header is absent/incorrect, then `cv2.imdecode` occurs before dimension limits are checked. Implement bounded incremental body reading with early 413 and validate format/dimensions as early as technically feasible; cap decoded pixel memory and reject decompression-bomb-like cases gracefully. Do not trust filename extension alone. Preserve valid JPEG/PNG/WEBP/EXIF behavior and 400/413 error contracts. Add unit tests for missing Content-Length, over-limit streams, corrupt images, huge dimensions, valid samples, and cleanup.

## Mandatory working rules
- Use the CURRENT thesis repository checkout attached to this task as the source of truth; file locations below refer to the 2026-10-13 ZIP and may have changed after earlier prompts.
- Before editing, reproduce/verify the issue with a focused test or identify the exact branch and why it is unsafe. Do not pretend an unmeasured risk is a confirmed field failure.
- Preserve Model 1 whole-fish detection/counting, Model 2 body-part grading, session/history integrity, and existing 50/30/20 weights unless this prompt explicitly requests an approved policy change.
- Make minimal, well-named, maintainable changes. Avoid unrelated UI rewrites, deleting historical data, training new models, or requiring large checkpoint binaries in unit tests.
- Include success tests, failure tests, and regressions for neighboring behavior. Use stubs/fakes when camera hardware or weights are absent. Never invent benchmark, scientific, or accuracy results.
- At the end, report changed files, behavior before/after, tests run and results, remaining risks, and any required user action. If a dependency is absent, explain the blocker instead of hiding it.


## Definition of done
Upload memory use is bounded without affecting valid analysis; invalid requests cannot mutate live state.

## Output format after running the task
1. What was verified (with file and function references).
2. What changed and why (including preserved behavior).
3. Tests added or updated, commands and results.
4. What is still untested, blocked, or awaiting expert/hardware validation.
5. A short recommendation for proceeding to the next numbered prompt.
