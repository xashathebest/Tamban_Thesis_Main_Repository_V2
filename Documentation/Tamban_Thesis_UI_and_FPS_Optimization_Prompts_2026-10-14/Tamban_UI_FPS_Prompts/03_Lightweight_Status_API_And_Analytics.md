# 03 - Stop Rebuilding History on Every Status Poll

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Reduce unnecessary backend work and response size from fast UI polling without losing any records or breaking exports, reviews or current-session stats.

## Confirmed code issue
`frontend/app.js` calls `/api/status` every 900 ms. In `src/api/app.py`, `_status_payload` calls `_durable_events()`, builds `_feature_counters` and `_analytics`, includes `available_models`, `runtime_diagnostics`, and `state.snapshot()`, potentially rereading/reprocessing all durable events repeatedly.

## Implementation
1. Profile `/api/status` p50/p95 server latency, JSON size and DB query count at 0, 100, 1,000 and 10,000 recorded fish using safe fixtures.
2. Split fast-changing live summary fields from less-frequent analytics, model metadata and archival/review data. Prefer event-version invalidation or incremental aggregates; keep a backward-compatible `/api/status` during transition.
3. Preserve SQLite as source of truth, including event updates, late grading and manual review. Cache keys must include session and revision; resetting/rotating sessions must invalidate appropriately.
4. Keep `/api/history`, `/api/reviews`, `/api/export` semantics unchanged. Fetch full analytics only when visible or on meaningful data change.
5. Add regression tests ensuring counters, grades, filters and exports are identical before/after, including manual grade corrections and new sessions.

## Acceptance
Show measured latency, query count and response-size improvement on the fixtures. No stale current fish, incorrect grade totals, lost events or broken historical exports.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
