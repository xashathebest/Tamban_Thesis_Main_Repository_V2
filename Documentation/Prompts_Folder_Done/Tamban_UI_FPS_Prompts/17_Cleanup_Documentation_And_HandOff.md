# 17 - Remove Dead UI Code and Update System Documentation

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Make the optimized UI and pipeline maintainable, consistent and thesis-defense ready.

## Scope
`README.md`, `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `src/api/app.py`, runtime configs, and relevant unit/UI tests.

## Implementation
- Audit obsolete selectors and styles left by UI consolidation; remove dead code only after proving no callers/tests depend on it.
- Fix documentation differences, notably README's crop-default description versus `FISH_QUALITY_INFERENCE_MODE=full_frame` in `src/api/app.py` (verify final chosen default after experiments).
- Document accurate meanings of `capture FPS`, `AI FPS`, `preview FPS`, `Model 2 confidence`, `weighted grade support`, and `Rejected` vs `Ungraded`.
- Add one operator quick-start: Start, monitor fish, inspect verdict, review, history, export, stop, safe calibration and settings access.
- Add one developer performance guide: config/env vars, profiler collection, hardware reports, expected failure modes, rollback flags and quality gates.
- Keep current model roles, provenance, required validation status and limitations explicit. Do not present incomplete crack/belly-hole research features as deployed grading.
- Run lint/syntax/unit tests and UI smoke checks; create a short changelog and precise list of remaining issues.

## Acceptance
New UI has no broken selector references or hidden functionality, docs match runtime behavior and test outputs are recorded.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
