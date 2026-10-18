# 15 - Accessibility, Responsiveness and User Feedback

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Improve legibility and user friendliness on the actual browser/device, without a wholesale framework rewrite.

## Inspect
`frontend/index.html`, `frontend/styles.css` breakpoints at 640/1024/1280, `frontend/app.js` modal/drawer controls, current focus/ARIA patterns and status updates.

## Implementation
- Audit tablet/laptop widths as well as mobile and large desktop. Avoid horizontal scrolling, cramped camera/result split or tiny confidence labels. Keep feed readable at 1366x768 Windows laptop layout.
- Ensure 44px-equivalent hit targets where applicable, sufficient contrast, focus visibility, semantic headings, table labels, non-color verdict cues and keyboard access.
- Maintain focus trapping/restoration for settings, export and calibration dialogs; esc to close when safe; correct `aria-expanded` and `aria-hidden` states.
- Add consistent skeleton/loading, slow-model, reconnecting, no-camera and unavailable-checkpoint messages. Do not cover the video indefinitely after first frame.
- Respect reduced motion and avoid frequent assertive screen-reader announcements on 900ms updates.
- Write browser-facing regression checks for open/close, navigation, review, export, camera error and modal focus. Avoid external frontend frameworks unless clearly needed.

## Acceptance
Provide before/after screenshots at 375, 768, 1366 and 1920 px plus a concise keyboard/accessibility checklist, tested against existing app workflows.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
