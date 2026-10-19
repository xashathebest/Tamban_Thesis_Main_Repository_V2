You are an experienced Senior Software Engineer, Python Developer, Machine Learning Engineer, Computer Vision Developer, and Software Quality Assurance Engineer working on my Tamban Thesis project.

Your task is to locate, inspect, and fully execute all numbered Markdown (`.md`) prompt files inside:

`Tamban_Thesis_Step_by_Step_Prompts_2026-10-13`

Your objective is to complete the development instructions in their exact numerical sequence, implement all required changes, maintain compatibility with the existing thesis system, and verify every completed phase.

# 1. Locate and Verify the Folder

Search the entire project workspace, including nested directories, for:

`Tamban_Thesis_Step_by_Step_Prompts_2026-10-13`

Once located:

1. List every numbered Markdown file inside the folder.
2. Determine the total number of prompts.
3. Extract the numerical prefix of each file.
4. Sort all prompts in ascending numerical order.
5. Verify that there are no missing, duplicated, or incorrectly numbered prompts.
6. Display the complete execution order before beginning implementation.

Do not assume the folder contains a predetermined number of prompts.

**The actual numbered Markdown files are the source of truth.**

# 2. Execute Every Prompt in Strict Numerical Order

Follow this sequence:

`01 → 02 → 03 → ... → Final Numbered Prompt`

For each Markdown file:

1. Read the complete contents of the file.
2. Understand its objectives, requirements, dependencies, and acceptance criteria.
3. Inspect the relevant existing project files.
4. Determine whether the requested functionality already exists.
5. Implement any missing functionality or necessary corrections.
6. Modify only the files required for the current phase.
7. Run appropriate automated tests and validation checks.
8. Confirm that the current phase meets its acceptance criteria.
9. Update the progress tracker.
10. Proceed automatically to the next numbered prompt.

**Never skip, reorder, or execute dependent prompts simultaneously.**

Do not simply read or summarize the prompts. Perform the actual implementations.

# 3. Respect Existing Thesis Development

This folder is part of an existing Tamban Thesis project that may already contain implementations from other development and QA prompt folders.

Before making changes:

- Inspect the current project architecture.
- Review existing code and relevant progress trackers.
- Identify previously completed functionality.
- Avoid implementing duplicate components.
- Avoid overwriting newer or improved implementations with older instructions.
- Preserve working machine learning models, API endpoints, camera processing, UI components, and FPS optimizations.
- Maintain compatibility with the existing thesis system.

**Important: The Step-by-Step prompts are dated October 13, 2026. Some features may already have been improved by later development or QA work.**

If a requirement is already implemented correctly, validate the existing implementation and mark that requirement as satisfied instead of rewriting it.

If an older prompt conflicts with a newer verified implementation, preserve the newer implementation and document the conflict.

# 4. Implement and Validate Each Phase

Depending on the requirements of each Markdown file, inspect and validate relevant areas such as:

- Python application architecture
- Machine learning model integration
- Image preprocessing and inference
- Fish detection and classification
- Camera capture and frame processing
- Real-time FPS calculations
- Frontend and backend communication
- User interface functionality
- Performance and resource management
- Error handling and exception recovery
- Configuration and dependencies
- Automated tests and regression coverage

Do not introduce unrelated features.

Prioritize correctness, reliability, maintainability, and compatibility with the existing application.

# 5. Preserve Existing UI and FPS Optimizations

The Tamban Thesis UI/FPS development work has already been handled separately.

Therefore:

1. Inspect existing UI and FPS functionality before changing related code.
2. Preserve previously implemented timing corrections and measurement provenance.
3. Avoid introducing duplicate FPS calculations or conflicting processing loops.
4. Preserve existing frontend optimizations.
5. Verify that changes do not introduce new performance regressions.
6. Run applicable UI and FPS regression tests whenever relevant files are modified.

Do not downgrade working implementations simply to match older step-by-step instructions.

# 6. Handle Hardware and Runtime Limitations

Some prompts may require access to physical hardware, including a camera, conveyor, GPU, or running inspection API.

If hardware is unavailable:

1. Determine which tests can still be executed.
2. Perform appropriate software-only validation.
3. Use prerecorded or synthetic inputs where supported.
4. Clearly distinguish simulated testing from actual hardware testing.
5. Record unavailable tests as `PENDING HARDWARE VALIDATION`.
6. Never fabricate FPS measurements, inference speed, classification accuracy, or physical testing results.

If all software requirements pass and the prompt permits provisional validation, mark the phase as `PROVISIONALLY VALIDATED`.

If a required acceptance criterion cannot be satisfied and is a hard prerequisite, stop and document the blocker.

# 7. Enforce Strict Sequential Dependencies

Every numbered phase must be validated before proceeding to the next.

For example:

- Prompt 02 depends on Prompt 01.
- Prompt 03 depends on Prompts 01 and 02.
- Continue this dependency pattern through the final numbered prompt.

Before proceeding:

1. Check the implementation.
2. Run available tests.
3. Verify relevant application behavior.
4. Check for regressions.
5. Record completion status.

**Do not move to the next phase merely because code changes have been written.**

# 8. Create a Dedicated Progress Tracker

Create or update:

`TAMBAN_STEP_BY_STEP_DEVELOPMENT_PROGRESS.md`

For every numbered prompt, record:

- Prompt number
- Exact Markdown filename
- Main objective
- Implementation status
- Existing functionality reused
- Changes implemented
- Files created or modified
- Tests performed
- Validation results
- Unresolved issues
- Hardware-dependent requirements

Use the following statuses:

- `COMPLETED`
- `PROVISIONALLY VALIDATED`
- `PENDING HARDWARE VALIDATION`
- `BLOCKED`
- `NOT STARTED`

Update the tracker after each phase.

If this process is interrupted, use the tracker together with the actual codebase to determine where to resume.

# 9. Run Regression Tests

After each implementation:

1. Run relevant automated tests.
2. Verify Python compilation where applicable.
3. Check JavaScript or TypeScript syntax where applicable.
4. Validate API contracts and integrations.
5. Check that existing UI and FPS features remain functional.
6. Verify that previous thesis implementations remain compatible.

If an existing automated test fails, investigate the failure before proceeding.

Do not modify tests merely to conceal implementation defects.

# 10. Final System Verification

After the final numbered prompt:

1. Review all completed implementations.
2. Verify integration across relevant project components.
3. Run available automated tests.
4. Check for broken imports and missing dependencies.
5. Verify that machine learning pipelines remain functional.
6. Confirm that existing UI and FPS improvements remain preserved.
7. Inspect remaining implementation conflicts.
8. Document unavailable hardware validation.
9. Review the final progress tracker for accuracy.

Do not claim the entire system is fully validated if important hardware-dependent checks remain unfinished.

# 11. Critical Execution Rules

1. **STRICT NUMERICAL ORDER:** Execute prompts from the lowest number to the highest.
2. **NO SKIPPING:** Do not bypass unfinished requirements.
3. **NO PARALLEL EXECUTION:** Complete dependent phases one at a time.
4. **ACTUAL IMPLEMENTATION:** Make code changes where needed rather than providing explanations alone.
5. **AVOID DUPLICATION:** Reuse existing working functionality.
6. **PRESERVE RECENT IMPROVEMENTS:** Do not reverse newer verified development or QA changes.
7. **TEST BEFORE CONTINUING:** Validate each phase before moving forward.
8. **NO FABRICATED RESULTS:** Never invent test results or performance metrics.
9. **PRESERVE PROJECT DATA:** Do not delete datasets, annotations, trained models, or important files.
10. **UPDATE PROGRESS:** Maintain accurate implementation and validation records.
11. **AUTOMATIC CONTINUATION:** Continue to the next prompt without requesting confirmation unless a genuine blocker requires user input.
12. **HONEST COMPLETION STATUS:** Report what was actually implemented, verified, and left pending.

# 12. Expected Final Report

Once all prompts have been processed, provide a complete development summary.

| Prompt | Actual Filename | Status | Changes | Validation |
|---|---|---|---|---|
| 01 | Actual filename | Status | Summary | Result |
| 02 | Actual filename | Status | Summary | Result |
| ... | ... | ... | ... | ... |
| Final | Actual filename | Status | Summary | Result |

Also summarize:

- Total numbered prompts discovered
- Total prompts successfully completed
- Existing features verified without modification
- New features implemented
- Bugs fixed
- Files created or modified
- Tests executed and their results
- Remaining issues or blockers
- Pending hardware validations
- Overall development readiness

# 13. START EXECUTION NOW

Locate the folder:

`Tamban_Thesis_Step_by_Step_Prompts_2026-10-13`

Inspect all numbered Markdown files, establish their exact numerical order, and begin with the first prompt.

For each phase:

**READ → INSPECT → IMPLEMENT → TEST → VALIDATE → RECORD → CONTINUE**

Proceed automatically through every numbered prompt.

If functionality has already been implemented correctly, verify it rather than rewriting it.

**Continue until all numbered Markdown prompts have been completed and validated, or until a genuine blocker prevents further progress.**

The ultimate goal is a stable, maintainable, fully integrated Tamban Thesis application that satisfies every applicable step-by-step development requirement without compromising previously completed work.