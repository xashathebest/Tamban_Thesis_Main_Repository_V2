# 12 - Make the Live Inspection Screen Easier to Use

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Make live fish monitoring straightforward: **camera, start/stop, counts, latest credible grade** should be obvious; research diagnostics should not dominate the screen.

## Current areas
`frontend/index.html`: `.camera-card`, `#result-panel`, `#kpi-grid`, `.session-details`, `#recent-inspections`, `.feature-section`, `#analytics-disclosure`, `#advanced-diagnostics`; `frontend/app.js`: `renderCamera`, `renderKpis`, `renderLatest`, `renderRecent`.

## Implementation
- Present one clear primary Start/Stop control, with distinct state for Starting/Running/Stopped/Error/Calibration. Avoid redundant empty-state Start as a separate competing primary CTA when feasible.
- Make the feed prominent with non-obscuring overlays and a compact performance/readiness row. If there are separate raw/annotated feeds (Prompt 09), label preview FPS vs AI FPS honestly.
- Show simple KPIs once: Fish counted, Graded, Ungraded/Needs Review, Rejected. Avoid repeating the same FPS, current grade or count in three cards. Keep detailed metrics behind `View details`.
- Display latest fish ID, grade and one concise evidence summary; distinguish **provisional** from **final** and **AI** from **manual review**. Never call a raw YOLO confidence 'percentage quality'.
- Include clear empty/error/camera-unavailable/model-unavailable states with actionable messages. Ensure color isn't the only signal of a grade.
- Keep track-based counting and grade rules unchanged; UI is read-only with respect to quality decisions.

## Acceptance
Deliver a before/after interface structure, concise operator workflow, and interaction tests. Verify the first-time operator can start/stop, find current verdict and locate review items without reading technical documentation.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
