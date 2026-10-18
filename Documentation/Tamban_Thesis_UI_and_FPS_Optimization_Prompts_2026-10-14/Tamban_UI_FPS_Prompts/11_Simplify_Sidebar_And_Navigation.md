# 11 - Remove Duplicate Navigation and Clarify the Workspace

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Redesign the frontend's information architecture to be simpler for a fish-inspection operator while preserving research tools and data.

## Source observations
`frontend/index.html`: sidebar has Live Inspection, Inspection History, Review Queue, Model, Analytics, Export, Settings. Header also has Export and Settings. `frontend/app.js` Analytics button opens a nested disclosure in Live Inspection rather than a true view. Model page repeats model details from header and Settings.

## Implementation
- Propose a compact primary navigation centered on **Inspect**, **History**, **Review**, **Analytics** (or equivalent). Move secondary actions to context-appropriate places: Export in History/toolbar; model/device details under **System / Settings**; research-only diagnostics under **Advanced**.
- Remove duplicate high-level Export/Settings buttons or assign each action exactly one obvious primary home. Keep shortcuts only where justified, but not duplicate full navigation entries.
- Give Analytics a genuine view OR clearly label it as a subsection; avoid the current nav that appears to be a separate page but scrolls inside a disclosure.
- Preserve current data structures, endpoint functionality, model switching, camera calibration, history, review, export and keyboard access. Update aria-current/focus/navigation tests.
- Map old DOM IDs/handlers before modifying; avoid orphan event listeners and dead CSS selectors.

## Acceptance
Include a brief old -> new navigation map, clickable end-to-end route walkthrough and screenshots at desktop/tablet/mobile sizes. No functionality silently disappears.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
