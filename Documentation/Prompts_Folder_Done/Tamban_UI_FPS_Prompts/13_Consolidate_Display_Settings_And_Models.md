# 13 - One Consistent Home for Settings and Model Details

Work in my current Tamban dried-fish thesis repository based on the updated October 13 `Thesis-main (2).zip`. This is a **single independent implementation task**. Do not implement later prompts as part of this request.

## Goal
Reduce redundancy between feed options, the Settings drawer and the Model page without hiding safety-critical configuration.

## Verified duplication
`frontend/app.js` has `overlayControls` arrays binding `#toggle-*` and `#settings-*` to the same display settings. Threshold controls, FPS, model availability and model device also appear across feed/header/Settings/Model.

## Implementation
- Keep one **operator-friendly** feed overlay menu for on-screen label toggles OR consolidate them in a clearly labeled Settings section. If shortcuts remain, they must reflect the same state reliably and not create competing settings locations.
- Separate **Display** (safe toggles) from **Model / Research settings** (threshold, model selection, inference mode, provenance, advanced calibration). Distinguish read-only system status from editable settings.
- Preserve API safeguards that lock threshold/policy edits during inspection; show the reason and next step rather than offering controls that silently fail.
- Group camera calibration under its own intentional advanced workflow. Retain profile save, operator confirmation, lock and physical-device readbacks.
- After relocating UI, remove unused event listeners, duplicate copy and dead CSS. Ensure no duplicate IDs or contradictory displayed values.

## Acceptance
Show the resulting settings hierarchy and verify on/off synchronization, keyboard use, locked policy state, camera calibration and model selection with tests.

## Required way of working

Inspect the **actual current code** before editing. Make the smallest coherent change for this task; preserve fish counting, track identity, Model 2 association, 50/30/20 evidence, the Ungraded/Rejected distinction, camera calibration, durable history, manual review, model traceability, exports, and existing API clients. Do not invent model benchmarks or grading improvements. If checkpoints are absent, write and run model-free tests with mocks, then provide exact on-machine validation commands. After implementing, report (1) files/functions changed, (2) before/after findings, (3) tests and manual checks, (4) unresolved risks, and (5) how to revert.
