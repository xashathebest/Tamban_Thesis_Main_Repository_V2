You are a Senior Software Engineer, Computer Vision Engineer, Machine Learning Performance Engineer, and Frontend UI/UX Specialist working on my Tamban Thesis fish inspection system.

Your task is to locate, inspect, and execute every numbered Markdown (`.md`) prompt inside:

`Tamban_Thesis_UI_and_FPS_Optimization_Prompts_2026-10-14`

## 1. Locate and Verify All Prompt Files

Search the entire repository for the specified folder.

1. List every numbered Markdown file.
2. Identify the exact filename and numerical prefix.
3. Determine the total number of prompts.
4. Check for missing or duplicate numbers.
5. Sort all numbered files in ascending numerical order.
6. Establish the correct execution sequence before making changes.

Do not assume a predetermined number of prompts.

## 2. Review Previous Development and QA Work

Before executing the first prompt, inspect the existing codebase and the following progress trackers if available:

- `TAMBAN_UI_FPS_DEVELOPMENT_PROGRESS.md`
- `TAMBAN_DEEP_CODE_QA_PROGRESS.md`
- `TAMBAN_FINAL_POLISH_QA_PROGRESS.md`

The previous Final Polish QA phase processed 21 prompts and reported:

- 588 model-free tests passed.
- 2 CPU checkpoint compatibility tests passed.
- Browser checks passed across selected screen sizes.
- Real-camera FPS and independent scientific validation remain incomplete.
- Prompt 11's empirical optimization remains blocked.

Verify these records against the actual repository.

**Do not undo previous fixes, duplicate existing functionality, or assume unresolved hardware-dependent requirements have been validated.**

## 3. Execute All Prompts Sequentially

Follow the exact numerical order:

`First → Second → Third → ... → Final`

For each Markdown prompt:

1. Read the entire file.
2. Identify its objectives, requirements, and dependencies.
3. Inspect the relevant existing code.
4. Determine whether its requirements are already implemented.
5. Preserve existing working implementations.
6. Implement missing requirements or fix verified defects.
7. Run appropriate automated tests.
8. Perform regression checks.
9. Record the actual results.
10. Proceed to the next numbered prompt when its prerequisites are satisfied.

If a requirement is already correctly implemented, validate it and document the result instead of rewriting it.

## 4. UI Optimization

Where applicable, review and improve:

- Live camera preview and inspection layout
- Dashboard clarity and navigation
- Real-time detection overlays
- Individual fish identification and tracking
- Classification labels and quality results
- Head, body, and tail evaluation displays
- Inspection session controls
- Loading, processing, and error states
- Responsive layout
- Keyboard navigation and accessibility
- History, settings, and export workflows

Avoid unnecessary visual redesigns.

Preserve the existing user experience unless a prompt explicitly requires changes.

## 5. FPS and Computer Vision Optimization

Inspect the actual runtime pipeline, including:

- Camera acquisition
- Frame decoding
- Fish detection
- Tracking and part association
- Model inference
- Classification and grading
- Preview rendering
- Frontend updates
- FPS instrumentation
- Memory and resource management

Identify genuine bottlenecks using available measurements.

Do not invent baseline FPS measurements or claim improvements without comparable before-and-after evidence.

Avoid optimizing model inference using synthetic benchmarks alone when the acceptance criteria require representative real-camera footage.

Where appropriate, consider frame scheduling, model reuse, unnecessary inference calls, preview decoupling, and resource cleanup, but implement changes only when supported by the prompt requirements and validation.

## 6. Protect Scientific and Grading Integrity

Preserve the latest approved grading specifications.

Where already implemented, maintain the optional-tail weighting:

- Head, body, and tail available: Body 50%, Head 30%, Tail 20%.
- Tail unavailable but head and body valid: Body 62.5%, Head 37.5%.
- Missing tail evidence must not automatically become a zero-score penalty.
- Verified tail defects must not be silently ignored.
- Missing mandatory head or body evidence must follow the established incomplete-inspection policy.

Do not change classification thresholds, model weights, or scientific rules solely to increase FPS.

Preserve accurate per-fish grading attribution.

## 7. Hardware and Performance Limitations

If the actual conveyor camera, GPU, or representative footage is unavailable:

1. Run available software tests and controlled synthetic checks.
2. Record any measured results with their actual environment.
3. Distinguish simulated throughput from camera-to-display FPS.
4. Record hardware-dependent acceptance as pending.
5. Preserve the procedures needed for later real-camera testing.

Do not claim real-world performance improvements without appropriate evidence.

If an optimization cannot be validated safely, document the blocker rather than introducing an unverified change.

## 8. Dedicated Progress Tracker

Create or update:

`TAMBAN_UI_FPS_OPTIMIZATION_PROGRESS.md`

For each prompt, record:

- Prompt number
- Actual filename
- Objectives
- Existing implementation status
- Changes made
- Files modified
- Tests performed
- Results
- Pending dependencies
- Final phase status

Use:

- COMPLETED
- ALREADY IMPLEMENTED AND VERIFIED
- PROVISIONALLY VALIDATED
- PENDING HARDWARE VALIDATION
- BLOCKED
- NOT STARTED

Update the tracker after each phase.

## 9. Final Regression Verification

After the final numbered prompt:

1. Run the full available model-free regression suite.
2. Run compatible model-backed checks where supported.
3. Perform Python and JavaScript syntax checks.
4. Review UI responsiveness and accessibility.
5. Verify camera and inference integration wherever possible.
6. Confirm that the optional-tail grading logic remains unchanged.
7. Check for FPS telemetry and tracking regressions.
8. Compare current results with the previously documented QA baseline.
9. Identify any newly introduced defects.
10. Preserve unresolved scientific and hardware validation requirements.

## 10. Final Report

Provide a table containing:

| Prompt | Actual Filename | Status | Changes | Validation |
|---|---|---|---|---|
| 01 | Actual filename | Status | Summary | Result |
| 02 | Actual filename | Status | Summary | Result |
| ... | ... | ... | ... | ... |
| Final | Actual filename | Status | Summary | Result |

Summarize:

- Total prompts discovered
- Prompts already implemented
- Prompts newly implemented
- Verified defects fixed
- Tests passed and failed
- Measured FPS changes, if available
- Remaining hardware blockers
- Regression findings
- Overall system readiness

## CRITICAL EXECUTION RULES

1. Execute numbered prompts in strict ascending order.
2. Never silently skip requirements.
3. Do not execute dependent phases in parallel.
4. Verify existing functionality before modifying it.
5. Preserve previous QA fixes.
6. Never fabricate FPS or classification results.
7. Avoid unnecessary refactoring.
8. Do not alter trained model weights without authorization.
9. Document unverified hardware-dependent requirements.
10. Continue automatically through phases whose prerequisites are satisfied.

## START EXECUTION

Locate:

`Tamban_Thesis_UI_and_FPS_Optimization_Prompts_2026-10-14`

Verify the numbered Markdown files and establish their numerical sequence.

Begin with the first prompt, inspect the existing implementation, complete its requirements, run available validation, and update:

`TAMBAN_UI_FPS_OPTIMIZATION_PROGRESS.md`

Continue in numerical order until every prompt has been processed or a genuine dependency prevents further progress.

**The objective is to optimize the existing Tamban Thesis UI and FPS pipeline without sacrificing classification correctness, undoing previous QA fixes, or misrepresenting real-world performance.**