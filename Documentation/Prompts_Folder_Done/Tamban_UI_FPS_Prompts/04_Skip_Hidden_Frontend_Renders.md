# 04 - Avoid 900-ms Repainting of Hidden UI

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Reduce browser CPU, DOM churn and duplicate requests while keeping status responsive and views fresh.

## Confirmed code issue
`frontend/app.js` `render()` invokes `renderCamera`, `renderLatest`, `renderKpis`, `renderFeatureCounters`, `renderAnalytics`, `renderRecent`, `renderModel`, `syncSettings`, and `renderRuntimeDiagnostics` every poll, even when their views or disclosures are hidden. `getStatus` is scheduled with `setInterval(..., 900)`. History/review loaders also run when their views are active.

## Implementation
- Profile browser render p50/p95 using existing frontend metrics and browser performance tooling. Identify actual hot paths.
- Update always-visible live widgets only when necessary; refresh charts/history/diagnostics only on view entry, meaningful data revision or appropriately slow cadence.
- Avoid re-creating existing legend rows, chart bars and nested DOM when the values have not changed. Use stable keyed elements or small diff updates.
- Implement non-overlapping, abortable requests; prevent stale requests from overwriting newer session/view data. Respect page visibility and pause nonessential fetches in hidden browser tabs.
- Stop redundant history/review fetches from both route entry and status rerender. Keep updates after review submissions and new events.
- Preserve live Start/Stop feedback, error states, semantic labels, accessible live announcements and data integrity.

## Acceptance
Report old/new DOM update counts, request frequency, CPU-render p50/p95 and status freshness. Test rapid view changes, slow server, history pagination and review edits.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
