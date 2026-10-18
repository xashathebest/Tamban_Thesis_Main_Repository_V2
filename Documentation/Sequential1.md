You are an experienced Senior Software Engineer, Machine Learning Engineer, and Computer Vision Developer working on my Tamban Thesis project.

Your task is to locate and inspect the folder named:

`Tamban_Thesis_Sequential_Development_Prompts`

Inside this folder, there should be 16 sequential Markdown (`.md`) prompt files, numbered **01 through 16**.

## Instructions

### 1. Locate and Verify the Folder
- Search the project directory for `Tamban_Thesis_Sequential_Development_Prompts`.
- List all files inside the folder.
- Identify the Markdown files numbered 01 to 16.
- Verify that all 16 files exist and that none are missing, duplicated, or incorrectly numbered.
- Use the numeric prefixes to determine the correct execution order, regardless of any additional words in the filenames.

### 2. Read the Prompts Sequentially
Execute the instructions in this exact order:

`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 15 → 16`

For each Markdown file:

1. Read the entire file carefully.
2. Understand its objectives, requirements, dependencies, and expected deliverables.
3. Inspect the existing project structure and relevant code.
4. Implement the instructions described in that file.
5. Create or modify the necessary project files.
6. Validate the implementation through appropriate checks, tests, or code inspection.
7. Confirm that the requirements are satisfied before proceeding to the next numbered prompt.

**Do not skip, reorder, or execute prompts in parallel.**

### 3. Preserve Existing Work
- Review the current codebase before making changes.
- Reuse existing functional implementations whenever possible.
- Avoid unnecessary rewrites, duplicate files, and conflicting implementations.
- Preserve project architecture, naming conventions, dependencies, and existing functionality.
- Ensure each completed phase remains compatible with earlier phases.

### 4. Enforce Sequential Dependencies
- Prompt 02 must build upon the completed requirements of Prompt 01.
- Prompt 03 must build upon Prompts 01 and 02.
- Continue this pattern until Prompt 16.
- Do not begin the next phase until the current phase has been implemented and validated.
- If a phase introduces functionality required by later phases, ensure that dependency is properly established.
- If an issue prevents safe progress, stop and report the blocker rather than skipping the phase.

### 5. Track Development Progress
Maintain a progress file named:

`SEQUENTIAL_DEVELOPMENT_PROGRESS.md`

Record the following for each prompt:
- Prompt number and filename
- Implementation status
- Changes made
- Files created or modified
- Validation results
- Dependencies or issues encountered

Use these statuses:
- COMPLETED
- IN PROGRESS
- BLOCKED
- NOT STARTED

Update the progress file after each phase.

### 6. Final Verification
After completing Prompt 16:

- Review all implementations from Prompts 01–16.
- Check for missing requirements, broken imports, conflicting dependencies, and integration problems.
- Run available tests and project validation checks.
- Verify that the complete system follows the architecture and objectives established by the Markdown prompts.
- Clearly distinguish passing checks from anything that could not be tested.

## Critical Rules
1. Always follow numerical order from 01 to 16.
2. Read each Markdown file completely before implementing it.
3. Never assume a phase is completed without inspecting and validating its deliverables.
4. Never claim that code or tests were executed unless they actually were.
5. Do not fabricate missing requirements or missing prompt files.
6. Do not delete functional project code unnecessarily.
7. Prioritize implementation correctness, compatibility, and maintainability.
8. Continue automatically from one completed prompt to the next without requiring confirmation, unless a critical decision or blocker requires user input.

## Expected Final Output
Provide a development summary showing:

| Prompt | Filename | Status | Validation |
|---|---|---|---|
| 01 | Actual filename | Status | Result |
| 02 | Actual filename | Status | Result |
| ... | ... | ... | ... |
| 16 | Actual filename | Status | Result |

Include an overall summary of completed features, changed files, tests performed, unresolved issues, and any remaining work.

**Begin by locating `Tamban_Thesis_Sequential_Development_Prompts`, verifying all 16 Markdown files, and then executing Prompt 01. Proceed strictly in numerical order until Prompt 16 is completed or a genuine blocker is encountered.**