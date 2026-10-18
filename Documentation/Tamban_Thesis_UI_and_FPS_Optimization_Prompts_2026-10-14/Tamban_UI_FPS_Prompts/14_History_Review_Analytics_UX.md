# 14 - Improve History, Review and Analytics Without Clutter

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Make records usable without duplicating the same fish data in multiple large tables or misleading users about research features.

## Current components
`#recent-inspections`, `#view-history`, `#view-review`, `#analytics-section`, `frontend/app.js` `renderHistoryRows`, `renderReviewRows`, `renderAnalytics`, `loadHistory`, `loadReviewQueue`.

## Implementation
- Keep a small `Recent fish` preview on live view with a `View History` link rather than reproducing the full table; keep History as the canonical full searchable/paginated record.
- Preserve Review Queue for unresolved/needs-review items and expert/manual decisions. Provide simple, auditable status transitions and immediate confirmation after review; do not overwrite AI source verdict.
- Consolidate filter layout (Fish ID, grade, date/session, review state) and make active filters/removal obvious. Retain server-side pagination for large histories.
- Present analytics under a clear dedicated place, with charts that use only available and scientifically supportable metrics. Rename 'Detected features' if it means observed Head/Body/Tail rather than automated crack or brightness-based grading.
- Only load heavy analytics when the user opens it; avoid full redraws every status poll. Preserve CSV/XLSX export options.

## Acceptance
Demonstrate live -> record -> review -> history -> export flow, with accurate counters and manual-review audit history; confirm no redundant large tables or unnecessary polling.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
