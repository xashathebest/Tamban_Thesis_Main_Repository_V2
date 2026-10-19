You are a Senior Software Engineer, Quality Assurance Engineer, Machine Learning Engineer, Computer Vision Architect, and UI/UX Specialist responsible for the final polishing and quality assurance of my Tamban Thesis system.

Your task is to locate and sequentially execute every numbered Markdown (`.md`) prompt inside:

`Tamban_Thesis_Final_Polish_and_QA_Prompts_2026-10-15`

## 1. Locate and Verify the Folder

Search the entire repository for the specified folder.

1. Identify all numbered Markdown files.
2. List their exact filenames.
3. Determine the total number of prompts.
4. Sort them by their numerical prefixes in ascending order.
5. Identify missing, duplicated, or incorrectly numbered files.
6. Establish the exact execution sequence.

Do not assume the folder contains a predetermined number of prompts.

If gaps or duplicate numbers exist, report and resolve the sequencing ambiguity before execution.

## 2. Review Existing Project Progress

Before starting, inspect the actual codebase and relevant development records, including, where present:

- `SEQUENTIAL_DEVELOPMENT_PROGRESS.md`
- `TAMBAN_UI_FPS_DEVELOPMENT_PROGRESS.md`
- `TAMBAN_DEEP_CODE_QA_PROGRESS.md`

Determine which implementations and fixes already exist.

Avoid repeating completed work unnecessarily, but independently verify functionality rather than relying solely on progress reports.

Identify unresolved issues from earlier development and QA phases that may affect final polishing.

## 3. Execute Every Prompt Sequentially

Follow the exact numerical order of the Markdown files.

For each prompt:

1. Read the entire Markdown file.
2. Identify its objectives and acceptance criteria.
3. Inspect the relevant code and existing functionality.
4. Perform the requested final polishing or QA activities.
5. Implement necessary fixes and improvements.
6. Preserve previously working functionality.
7. Run applicable automated checks.
8. Verify that the prompt's requirements are satisfied.
9. Record the results.
10. Proceed to the next numbered prompt.

**Do not skip prompts, reorder phases, or execute dependent prompts in parallel.**

## 4. Final Polish Requirements

Where required by the actual prompts, focus on:

### User Interface and Experience

- Consistent visual design
- Clear navigation and workflows
- Responsive layout
- Accurate inspection information
- Clear classification results
- Meaningful loading and error states
- Proper camera and FPS presentation
- Improved usability for thesis demonstrations

### Backend and Integration

- API correctness
- Frontend-backend synchronization
- Reliable data handling
- Correct error handling
- Stable model inference integration
- Proper resource initialization and cleanup
- Accurate inspection and grading outputs

### Computer Vision and Classification

- Correct fish detection and identification
- Reliable head, body, and tail evaluation
- Correct per-fish grading attribution
- Consistent class labels and confidence handling
- Accurate FPS and timing instrumentation
- Stable processing of multiple fish
- Appropriate handling of unavailable fish components

### Adaptive Tail-Optional Grading

Inspect the latest implemented grading specifications.

Where applicable, ensure:

- All three components available: Body 50%, Head 30%, Tail 20%.
- Tail unavailable but head and body valid: Body 62.5%, Head 37.5%.
- Unavailable tail measurements do not automatically produce a zero-score penalty.
- Reliably observed tail defects are not silently treated as detection failures.
- Missing mandatory head or body measurements are handled according to established inspection rules.

If this logic has not yet been formally approved or implemented, identify it as a pending requirement rather than silently changing the grading methodology.

Do not modify quality-grade thresholds or trained model weights without justification.

## 5. Preserve the Existing Thesis System

- Do not rebuild the application from scratch.
- Do not unnecessarily rewrite working modules.
- Do not delete datasets, annotations, or trained model files.
- Do not introduce unrelated features.
- Avoid duplicated code and conflicting configurations.
- Maintain compatibility across the frontend, backend, and machine learning pipeline.
- Prefer targeted, maintainable fixes.

## 6. Testing and Validation

For each prompt, perform relevant available checks, including:

- Python syntax and compilation checks
- JavaScript syntax checks
- Unit tests
- Integration tests
- Regression tests
- API contract verification
- UI behavior testing where tools are available
- Grading and classification boundary tests
- Performance and FPS checks where the environment supports them

Do not claim a test passed unless it was actually executed.

If real-camera testing, CUDA acceleration, conveyor operation, or browser interaction is unavailable, document the limitation clearly.

Use `PENDING HARDWARE VALIDATION` where appropriate, without inventing measurements.

## 7. Maintain a Dedicated Progress Tracker

Create or update:

`TAMBAN_FINAL_POLISH_QA_PROGRESS.md`

For each prompt, record:

- Prompt number and filename
- Objectives
- Files inspected
- Issues identified
- Corrections and improvements implemented
- Files changed
- Tests performed
- Results
- Remaining issues
- Completion status

Supported statuses:

- COMPLETED
- PROVISIONALLY VALIDATED
- PENDING HARDWARE VALIDATION
- BLOCKED
- NOT STARTED

Update the tracker after every phase.

## 8. Final Regression and Integration Review

After the last numbered prompt:

1. Review all changes made during this QA phase.
2. Run the complete available test suite.
3. Verify that earlier development and QA fixes remain functional.
4. Check inspection workflows from input through classification output.
5. Verify consistent backend and frontend behavior.
6. Review outstanding performance and hardware requirements.
7. Identify any remaining critical or high-severity issues.
8. Confirm which features are ready for a thesis demonstration and which still require validation.

Do not claim full production or defense readiness if critical tests remain incomplete.

## 9. Critical Execution Rules

1. Execute every numbered prompt in strict ascending order.
2. Complete and validate the current phase before proceeding.
3. Do not skip or silently bypass requirements.
4. Perform actual code changes when necessary.
5. Preserve existing working functionality.
6. Avoid unnecessary refactoring.
7. Keep records of all modifications and results.
8. Never fabricate test outcomes, FPS values, classification metrics, or successful hardware tests.
9. Distinguish completed checks from provisional or pending validation.
10. Continue automatically through all prompts unless a genuine blocker prevents further progress.

## 10. Expected Final Report

Provide a summary table:

| Prompt | Actual Filename | Status | Changes Made | Validation |
|---|---|---|---|---|
| 01 | Actual filename | Status | Summary | Result |
| 02 | Actual filename | Status | Summary | Result |
| ... | ... | ... | ... | ... |
| Final | Actual filename | Status | Summary | Result |

Also report:

- Total prompts discovered
- Total prompts completed
- Total issues fixed
- Total tests passed and failed
- UI and integration improvements
- Remaining bugs
- Pending hardware validation
- Overall demonstration readiness

## START EXECUTION

Locate:

`Tamban_Thesis_Final_Polish_and_QA_Prompts_2026-10-15`

Verify its numbered Markdown files, establish the exact sequence, and immediately execute the first prompt.

Complete each phase, validate the implementation, and update `TAMBAN_FINAL_POLISH_QA_PROGRESS.md` before moving to the next.

**Continue through every numbered prompt in strict numerical order until all requirements are satisfied or a genuine blocker prevents further progress.**

The goal is to deliver a stable, polished, thoroughly tested, and demonstration-ready Tamban Thesis application while preserving the integrity of the existing computer vision and grading system.