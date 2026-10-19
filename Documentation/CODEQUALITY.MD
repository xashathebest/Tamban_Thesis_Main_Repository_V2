You are an experienced Senior Software Engineer, Software Quality Assurance Engineer, Python Developer, Machine Learning Engineer, and Computer Vision Systems Architect.

Your task is to locate, inspect, and sequentially execute every numbered Markdown (`.md`) prompt inside the following folder:

`Tamban_Thesis_Deep_Code_QA_Prompts_2026-10-14`

This is a comprehensive code quality assurance and technical verification process for my existing Tamban Thesis system.

## 1. Locate and Verify the Folder

Search the entire project repository for:

`Tamban_Thesis_Deep_Code_QA_Prompts_2026-10-14`

Once located:

1. List every numbered Markdown file.
2. Determine the total number of prompts.
3. Extract their numerical prefixes.
4. Sort them in ascending numerical order.
5. Check for missing, duplicated, or incorrectly numbered prompt files.
6. Establish the exact execution sequence before modifying any code.

Do not assume the folder contains 16, 18, or any predetermined number of prompts.

Use the actual filenames and their numerical prefixes as the source of truth.

## 2. Execute Every Prompt in Strict Numerical Order

Execute the Markdown prompts sequentially, beginning with the lowest numbered file and ending with the highest.

For each prompt:

1. Read the entire Markdown file.
2. Understand its QA objectives, technical requirements, acceptance criteria, and dependencies.
3. Examine the relevant files, modules, functions, configurations, and project components.
4. Perform the code inspection or analysis required by the prompt.
5. Identify actual bugs, implementation defects, performance problems, security risks, and architectural inconsistencies.
6. Fix verified issues that fall within the prompt's scope.
7. Run appropriate tests and validation checks.
8. Confirm that the implemented changes satisfy the prompt's requirements.
9. Record the results before proceeding to the next prompt.

**Never skip, reorder, or execute dependent prompts simultaneously.**

Do not merely summarize the instructions. Perform the actual QA analysis and implement necessary corrections.

## 3. Deep Code Quality Assurance

When required by the Markdown prompts, evaluate the following aspects of the Tamban Thesis application:

### A. Code Quality and Maintainability

- Syntax and runtime errors
- Broken imports and dependencies
- Incorrect function calls
- Duplicate or redundant implementations
- Dead code and unused dependencies
- Poor separation of responsibilities
- Exception handling and recovery
- Configuration inconsistencies
- Resource and memory management
- Potential race conditions
- Fragile or unnecessarily complex code

### B. Machine Learning and Computer Vision

- Model loading and initialization
- Image acquisition and preprocessing
- Detection and classification logic
- Model inference execution
- Bounding-box handling
- Confidence thresholds
- Class-label consistency
- Correct fish-level classification attribution
- Model output interpretation
- Frame processing and FPS calculations
- Performance measurements and timing accuracy
- Potential data leakage or invalid evaluation logic

Do not modify model architectures, trained weights, or classification criteria without a verified reason and clear documentation.

### C. User Interface and System Integration

- Frontend and backend communication
- API endpoint consistency
- Camera feed integration
- Real-time detection display
- Data synchronization
- FPS measurement and visualization
- UI state handling
- Error messages and recovery mechanisms
- Resource cleanup
- Potential interface freezes or processing bottlenecks

### D. Reliability and Security

- Input validation
- File path handling
- Configuration and environment variables
- Unsafe file operations
- Dependency vulnerabilities
- Sensitive information exposure
- Error and exception reporting
- Stability under unexpected inputs

Only perform checks that are relevant to the actual codebase and the corresponding Markdown prompts.

## 4. Preserve Existing Project Functionality

Before making any modifications:

1. Inspect the project architecture.
2. Identify existing functional components.
3. Review recent implementations and progress trackers.
4. Check whether reported problems have already been resolved.
5. Avoid duplicate fixes and unnecessary rewrites.
6. Preserve compatibility with existing computer vision models, APIs, UI components, and thesis workflows.

**Do not rebuild the application from scratch.**

Apply minimal, targeted, maintainable fixes unless the prompt explicitly requires a larger refactor.

Do not delete datasets, trained models, annotations, configuration files, or existing project functionality without explicit authorization.

## 5. Handle Hardware and Environment Limitations

Some QA requirements may involve physical cameras, conveyor operation, GPU acceleration, or live FPS measurements.

If the required hardware is unavailable:

1. Attempt appropriate software-only validation.
2. Use synthetic or prerecorded inputs where supported.
3. Run available unit, integration, and regression tests.
4. Record unavailable tests as `PENDING HARDWARE VALIDATION`.
5. Clearly distinguish simulated results from real-world performance results.
6. Never fabricate FPS values, detection accuracy, model performance, or successful physical testing.

If the software implementation is complete and its available checks pass, mark the phase as `PROVISIONALLY VALIDATED` only when the prompt's acceptance criteria permit it.

If a prompt requires successful hardware validation as a hard prerequisite, stop at that phase and document the blocker rather than bypassing the requirement.

## 6. Enforce Strict Sequential Dependencies

Every QA prompt must be completed and validated before proceeding to the next numbered prompt.

For example:

- Prompt 02 must consider the results of Prompt 01.
- Prompt 03 must preserve the corrections made in Prompts 01 and 02.
- Continue the same pattern through the final numbered prompt.

After each phase:

1. Review the modifications.
2. Run relevant validation checks.
3. Verify that previously working behavior has not regressed.
4. Confirm that dependencies remain compatible.
5. Update the QA progress tracker.
6. Proceed to the next prompt only when its prerequisites are satisfied.

If a genuine blocker prevents continuation, document it clearly.

## 7. Maintain a Dedicated QA Progress Tracker

Create or update:

`TAMBAN_DEEP_CODE_QA_PROGRESS.md`

For each prompt, record:

- Prompt number
- Actual Markdown filename
- QA objective
- Files inspected
- Problems identified
- Severity of each confirmed issue
- Corrections implemented
- Files modified
- Tests executed
- Test results
- Remaining risks
- Completion status

Use these statuses:

- `COMPLETED`
- `PROVISIONALLY VALIDATED`
- `PENDING HARDWARE VALIDATION`
- `BLOCKED`
- `NOT STARTED`

Update the tracker after every phase.

If a previous execution was interrupted, inspect both the tracker and actual codebase to determine where to resume. Do not rely on the tracker alone.

## 8. Severity-Based Issue Management

Classify confirmed defects according to severity:

**CRITICAL:** System-breaking errors, data corruption risks, severe security issues, or invalid core detection/classification behavior.

**HIGH:** Major functional defects, serious integration failures, or substantial reliability problems.

**MEDIUM:** Incorrect edge-case behavior, moderate performance problems, or maintainability issues affecting functionality.

**LOW:** Minor code-quality issues, noncritical inconsistencies, or small improvements.

Prioritize critical and high-severity defects within each phase.

Do not report hypothetical issues as confirmed defects. Clearly distinguish verified findings from potential risks requiring investigation.

## 9. Final Repository-Wide Verification

After executing the final numbered Markdown prompt:

1. Review all QA findings and implemented corrections.
2. Run available automated tests.
3. Perform Python compilation and JavaScript syntax checks where applicable.
4. Check for broken imports and incompatible dependencies.
5. Validate API and UI integration where possible.
6. Examine critical computer vision execution paths.
7. Check that earlier fixes remain effective.
8. Review unresolved issues and pending hardware tests.
9. Confirm that the final system conforms to the actual QA prompt requirements.

Do not claim full system validation if physical integration tests remain incomplete.

## 10. Critical Execution Rules

1. **STRICT ORDER:** Follow the numeric filename sequence without exceptions.
2. **NO SKIPPING:** Do not bypass incomplete QA requirements.
3. **NO PARALLEL PHASES:** Finish each phase before the next begins.
4. **REAL CODE INSPECTION:** Examine actual source files rather than assuming behavior.
5. **IMPLEMENT FIXES:** Correct verified issues instead of producing reports only, provided the prompt permits modification.
6. **MINIMAL CHANGES:** Avoid unnecessary refactoring and duplicated functionality.
7. **NO FABRICATION:** Never invent test results, QA findings, performance metrics, or successful executions.
8. **PRESERVE DATA:** Protect datasets, annotations, models, and existing project files.
9. **REGRESSION TESTING:** Verify that new fixes do not break completed functionality.
10. **CONTINUOUS PROGRESS:** Continue automatically from one validated prompt to the next unless a genuine blocker prevents progress.
11. **SOURCE OF TRUTH:** Treat the actual numbered Markdown files as authoritative, while respecting existing project requirements and dependencies.
12. **HONEST REPORTING:** Distinguish between completed validation, provisional validation, and outstanding hardware-dependent checks.

## 11. Expected Final QA Report

Once all available prompts have been processed, provide a detailed summary.

| Prompt | Actual Filename | QA Status | Issues Fixed | Validation |
|---|---|---|---|---|
| 01 | Actual filename | Status | Count | Result |
| 02 | Actual filename | Status | Count | Result |
| ... | ... | ... | ... | ... |
| Final | Actual filename | Status | Count | Result |

Also include:

- Total prompts discovered
- Total prompts executed
- Total confirmed bugs found
- Total bugs fixed
- Remaining critical or high-severity issues
- Files modified
- Automated test results
- Regression test results
- Pending hardware-dependent validations
- Unresolved environmental blockers
- Overall codebase readiness

## 12. START EXECUTION

Begin by locating:

`Tamban_Thesis_Deep_Code_QA_Prompts_2026-10-14`

Inspect its contents and establish the complete numerical sequence.

Read and execute the first numbered Markdown prompt.

Complete its QA requirements, implement necessary corrections, run applicable validation, and update:

`TAMBAN_DEEP_CODE_QA_PROGRESS.md`

Then automatically proceed to the next numbered prompt.

**Continue in strict numerical order until every Markdown prompt has been executed and validated, or a genuine blocker prevents further progress.**

The objective is to produce a thoroughly inspected, corrected, stable, maintainable, and integration-ready Tamban Thesis codebase—not merely a collection of QA reports.