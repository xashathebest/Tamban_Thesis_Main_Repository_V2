You are an experienced Senior Software Engineer, UI/UX Developer, Frontend Engineer, and Computer Vision Systems Developer working on my Tamban Thesis project.

Your task is to locate, inspect, and sequentially execute all Markdown (`.md`) prompt files inside the folder:

`Tamban_UI_FPS_Prompts`

## 1. Locate and Verify the Folder

- Search the entire project directory for `Tamban_UI_FPS_Prompts`.
- List all Markdown prompt files inside the folder.
- Identify their numerical prefixes and determine the correct execution order.
- Verify that no numbered prompts are missing, duplicated, or incorrectly named.
- Do not assume the folder contains exactly 16 prompts. Determine the actual number of prompts from its contents.
- Arrange the files in ascending numerical order, starting from the lowest numbered prompt.

## 2. Execute Every Prompt Sequentially

Follow the numerical order established by the filenames.

For each Markdown prompt:

1. Read the entire `.md` file carefully.
2. Identify its objectives, technical requirements, dependencies, and expected deliverables.
3. Inspect the existing project architecture and relevant code.
4. Implement all applicable instructions from the prompt.
5. Create or modify the necessary files.
6. Integrate the changes with the existing Tamban Thesis application.
7. Validate the implementation through appropriate testing, code inspection, and available development tools.
8. Confirm that the current phase meets its requirements before proceeding.

**Never skip prompts, execute them out of order, or run dependent phases simultaneously.**

## 3. UI and FPS Development Requirements

Because these prompts concern the Tamban Thesis UI and FPS functionality, prioritize the requirements defined in the actual Markdown files.

Where applicable, ensure:

- The user interface is functional, responsive, organized, and suitable for the thesis application.
- Camera feeds integrate correctly with the existing computer vision pipeline.
- Real-time detection and classification results are displayed accurately.
- FPS measurements reflect actual processing performance rather than hardcoded values.
- Camera capture, model inference, and UI rendering are handled efficiently.
- UI updates do not unnecessarily block or slow down computer vision processing.
- Existing machine learning models, detection pipelines, and classification functionality remain compatible.
- Performance optimizations do not compromise detection accuracy or system stability.

Do not introduce additional functionality that conflicts with the actual prompt requirements.

## 4. Preserve Existing Implementations

Before modifying any code:

- Inspect the existing project structure.
- Identify reusable components, functions, and modules.
- Preserve working functionality from previous thesis development phases.
- Avoid unnecessary rewrites, duplicated components, or incompatible dependencies.
- Follow existing coding conventions and architecture.
- Ensure that new UI and FPS functionality integrates with the existing Tamban Thesis system.

**Do not rebuild the application from scratch unless explicitly required by the prompts.**

## 5. Enforce Strict Sequential Dependencies

Each numbered prompt must build upon the successfully completed phases before it.

For example:

- Prompt 02 must be compatible with Prompt 01.
- Prompt 03 must preserve the functionality established by Prompts 01 and 02.
- Continue this process until the final numbered prompt.

Before proceeding to the next file:

1. Verify the current implementation.
2. Check for syntax errors and broken imports.
3. Validate relevant UI functionality.
4. Verify FPS-related behavior when applicable.
5. Resolve implementation conflicts.
6. Record the completed phase.

If a critical issue prevents safe continuation, stop at that phase and explain the blocker. Do not silently skip it.

## 6. Maintain Development Progress

Create or update a tracking file named:

`TAMBAN_UI_FPS_DEVELOPMENT_PROGRESS.md`

For every prompt, record:

- Prompt number
- Actual filename
- Implementation status
- Features implemented
- Files created or modified
- Validation and test results
- Issues or blockers
- Integration notes

Use the following statuses:

- COMPLETED
- IN PROGRESS
- BLOCKED
- NOT STARTED

Update the progress tracker immediately after finishing each phase.

If the development process is interrupted, use this tracker to verify completed work before resuming. Never assume a phase is complete based solely on its recorded status.

## 7. Final Integration and Verification

After executing the final numbered prompt:

1. Review the implementations from all prompt files.
2. Verify that the UI components work together.
3. Check compatibility with the existing Tamban Thesis computer vision pipeline.
4. Validate FPS measurement and display functionality wherever applicable.
5. Check for performance bottlenecks and unnecessary processing overhead.
6. Run available project tests and validation checks.
7. Identify unresolved bugs, missing dependencies, or incomplete requirements.
8. Confirm that the final implementation aligns with the specifications in the Markdown files.

Do not claim successful performance testing unless actual measurements were performed.

## 8. Critical Execution Rules

1. **STRICT ORDER:** Execute every numbered `.md` file in ascending numerical order.
2. **NO SKIPPING:** Do not bypass incomplete phases.
3. **NO PARALLEL EXECUTION:** Complete one phase before starting the next.
4. **FULL IMPLEMENTATION:** Implement the requirements rather than merely describing them.
5. **NO ASSUMPTIONS:** Treat the actual Markdown files as the source of truth.
6. **PRESERVE EXISTING CODE:** Avoid breaking completed thesis functionality.
7. **VERIFY EACH PHASE:** Validate every implementation before continuing.
8. **TRACK PROGRESS:** Maintain an accurate development progress file.
9. **NO FABRICATED RESULTS:** Never invent successful tests, FPS values, or implementation outcomes.
10. **AUTOMATIC CONTINUATION:** Proceed through all numbered prompts without requesting confirmation between phases unless a critical blocker requires clarification.

## 9. Expected Final Report

Once all prompts have been processed, provide the following:

| Prompt | Filename | Implementation Status | Validation |
|---|---|---|---|
| 01 | Actual filename | Status | Result |
| 02 | Actual filename | Status | Result |
| ... | ... | ... | ... |
| Final | Actual filename | Status | Result |

Also summarize:

- Total prompts discovered
- Total prompts completed
- UI features implemented
- FPS-related functionality implemented
- Existing components modified
- Integration results
- Tests performed
- Unresolved issues
- Overall development status

## START EXECUTION

Begin by locating:

`Tamban_UI_FPS_Prompts`

Inspect its contents, verify the numbered Markdown files, and establish their exact numerical sequence.

**Then immediately execute the first numbered prompt, complete its implementation, validate the changes, update the progress tracker, and proceed to the next prompt.**

Continue sequentially until every Markdown prompt inside `Tamban_UI_FPS_Prompts` has been successfully implemented and validated, or until a genuine blocker prevents further progress.sS