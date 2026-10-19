# Tamban Thesis — Final Polish and Full QA Prompt Pack

**Version:** 15 October 2026  
**Purpose:** A step-by-step final stabilization, UI/UX polish, performance optimization and thesis-defense quality assurance sequence for the user's current two-model Tamban system.

## How to use

1. Unzip this package. Use the **latest local source code** (not the original uploaded ZIP if you have already applied earlier fixes).
2. Open `prompts/01_Audit_Current_Code_And_Baseline.md`. Copy the full prompt into your coding assistant with access to the repository.
3. Have it finish the task, run and show tests, and commit/review the changes **before** moving to the next prompt.
4. Continue **one Markdown file at a time** in filename order. The prompt for expert consultation evidence (`21_...`) is optional.
5. If a task is already resolved in your latest code, have the assistant demonstrate the existing behavior and skip modifications. Do not manufacture changes simply to complete a step.
6. Keep one running log of results; `QA_PROGRESS_CHECKLIST.md` can be updated after each prompt.

## What this pack is / is not

This is a set of **instructions to verify and improve code**, not a claim that they have been executed. Earlier code audits identified potential and reproduced issues, but the latest working tree must be inspected and tested again. Large YOLO checkpoint files may be missing from shared repository archives; mark blocked tests accordingly rather than claiming the models are broken.

## Prompts at a glance

| # | Focus | Priority |
|---|---|---|
| 01 | [Fresh repository audit and evidence baseline](prompts/01_Audit_Current_Code_And_Baseline.md) | P0 - start here |
| 02 | [Prevent changes to model identity during active inspections](prompts/02_Freeze_Model_Selection_And_Isolate_Uploads.md) | P0 - data integrity |
| 03 | [Make camera lifecycle and durable sessions race-safe](prompts/03_Session_Start_Stop_Restart_Reliability.md) | P0 - data integrity |
| 04 | [Validate entire configuration and checkpoint identities safely](prompts/04_Atomic_Settings_Checkpoint_Integrity.md) | P0 - prevent silent inconsistency |
| 05 | [Protect per-fish identity and body-part ownership](prompts/05_Tracker_And_Parent_Part_Association.md) | P0 - grading validity |
| 06 | [Make evidence aggregation robust but scientifically honest](prompts/06_Temporal_Grading_Uncertainty_And_Dropouts.md) | P0 - grading validity |
| 07 | [Protect research methodology from unintended changes](prompts/07_Expert_Rules_And_Feature_Claims.md) | P1 - scientific clarity |
| 08 | [Make saved data faithful to what happened](prompts/08_Historical_Records_Review_And_Exports.md) | P1 - data correctness |
| 09 | [Harden external operations without overengineering](prompts/09_Input_Validation_Error_Recovery_And_LAN_Safety.md) | P1 - stability |
| 10 | [Establish reproducible performance baseline](prompts/10_Measure_Actual_FPS_And_Timing.md) | P1 - measure before optimizing |
| 11 | [Reduce measured latency without damaging grading](prompts/11_Safely_Optimize_Model_Inference.md) | P1 - performance |
| 12 | [Improve perceived smoothness truthfully](prompts/12_Decouple_Preview_From_Heavy_AI.md) | P1 - live operator experience |
| 13 | [Remove redundant navigation and visual clutter](prompts/13_Simplify_Sidebar_And_Dashboard.md) | P2 - UI polish |
| 14 | [Make live operation clear and confidence-inspiring](prompts/14_Polish_Live_Inspection_Interactions.md) | P2 - UI polish |
| 15 | [Make secondary workflows predictable and self-explanatory](prompts/15_Polish_History_Settings_Exports_UX.md) | P2 - UI polish |
| 16 | [Make the app work well on common screens](prompts/16_Responsive_Visual_And_Accessibility_Finishing.md) | P2 - UI polish |
| 17 | [Remove hidden maintenance and uptime risks](prompts/17_Code_Cleanup_Resource_And_Long_Run_QA.md) | P2 - reliability |
| 18 | [Build a traceable PASS/FAIL/BLOCKED quality matrix](prompts/18_Comprehensive_Automated_Manual_QA.md) | P0 - final QA gate |
| 19 | [Verify research claims and practice the real demonstration](prompts/19_Independent_Science_Validation_And_Demo_Rehearsal.md) | P0 - thesis gate |
| 20 | [Close the loop with a defensible readiness decision](prompts/20_Final_Release_Review_And_Documentation.md) | P0 - last |
| 21 | [Optional consent-respecting consultation evidence UI](prompts/21_Optional_Expert_Evidence_Library.md) | OPTIONAL - only if desired |

## Suggested milestones

- **Data integrity and grading:** 01–09. These matter more than visual polishing because session/model ownership and part association determine whether results can be trusted.
- **Performance:** 10–12. Establish measurements on your actual thesis PC before tuning FPS.
- **UI/UX:** 13–16. Remove redundancy while preserving all operator workflows.
- **Stability and quality assurance:** 17–18.
- **Scientific claims and defense:** 19–20.
- **Optional extra:** 21 (Expert Evidence sidebar). Do not insert unconsented videos into a public deployment.

## Mandatory distinctions

- Camera preview FPS, AI processed FPS and grading update rate are DIFFERENT quantities.
- Detector confidence is not a calibrated probability that the fish grade is correct.
- Whole-fish detection and body-part classification are separate models; a post-model decision policy combines evidence.
- Physical absence of a head is not the same as its nondetection behind another fish.
- Not-detected / ambiguous fish should not be called Rejected without affirmative evidence.
- Offline features (brightness/texture/reflectance) are not necessarily live grading inputs.
- Expert interviews can justify investigating a rule; experimental tests are needed to show it works.

## Minimum final evidence

By the final step, you should have test output, a change log, a QA matrix, measured FPS on target hardware (or an explicit BLOCKED status), UI before/after screenshots, export samples, policy version evidence, and a documented READY / CONDITIONALLY READY / NOT READY decision.
