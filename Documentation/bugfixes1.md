# TAMBAN THESIS — COMPLETE FPS, TRACKER, FEATURE INTEGRATION & LIVE APPLICATION REPAIR

You are a Senior Computer Vision Engineer, Machine Learning Optimization Specialist, Full-Stack Software Engineer, and Research Software Quality Assurance Engineer.

Your assignment is to **actively diagnose, repair, optimize, integrate, and validate my existing Tamban Thesis conveyor-belt inspection application**.

THIS IS AN IMPLEMENTATION TASK, NOT AN AUDIT-ONLY TASK.

I want actual improvements to my working application, not just code changes, test files, or documentation.

You must preserve the existing system while making the camera, detection, tracking, grading, interface, analytics, and performance features function together.

---

# 1. REQUIRED RESEARCH DOCUMENT

Locate and thoroughly read:

`Tamban_Thesis_Requirements_Dataset_Checklist_and_Validation_2026-10-20.docx`

This document contains the research requirements, dataset collection checklist, grading decisions, and validation procedures.

Treat it as a primary specification alongside the latest approved system configuration.

Read all 14 pages, particularly:

- Pages 1–2: Operating requirements, grading and optional-tail policy.
- Page 3: Model 2, features, masks and crack assessment.
- Pages 4–9: Dataset and real-world inspection scenarios.
- Page 10: Relative crack measurements and pending vendor approval.
- Page 11: Model annotation and dataset integrity.
- Page 12: Vendor comparison and scientific evaluation.
- Page 13: Implementation, speed and regression QA.
- Page 14: Pending research decisions and sign-off.

If the document is unavailable in the repository, explicitly report this. Use the requirements reproduced below where sufficient, but do not claim to have inspected an inaccessible document.

Classify requirements as:

- AGREED: Researcher-selected operating requirements.
- PROPOSED: Methods that require implementation and evaluation.
- PENDING: Decisions requiring vendor, professor, or team approval.

Do not silently convert experimental proposals into validated grading rules.

# 2. PRIMARY OBJECTIVES

Repair and optimize the following:

1. Low real-time AI processing FPS.
2. Tracker warning: `Active tracker: IoU fallback (optional ByteTrack lap dependency unavailable)`.
3. Camera initialization and session reliability.
4. Actual live camera feed and image display.
5. Model 1 fish detection and tracking.
6. Model 2 Head, Body, and Tail grading evidence.
7. Existing visual feature extraction and its appropriate application.
8. Accurate individual fish grading.
9. Real-time frontend and backend synchronization.
10. Session analytics, counters, history and exports.
11. Actual FPS telemetry and performance diagnostics.
12. Continuous conveyor operation without stopping the belt.

**CRITICAL: Implement these improvements in the existing application. Do not create isolated functions or utilities that are never called by the real inspection workflow.**

# 3. FIRST DIAGNOSE THE ACTUAL APPLICATION

Inspect the complete repository, including:

- Backend entry point
- Camera controller
- Model loading and registry
- Model 1 detector
- Model 2 part detector
- Fish tracking and association
- Temporal evidence and grading engine
- Visual feature extraction
- API routes
- Frontend components
- Runtime diagnostics
- Session records and database
- Export functionality
- Existing QA progress trackers
- Model checkpoints and dependencies

Map the real execution path:

Camera → Frame Capture → Model 1 → Fish Tracking → Model 2 → Part Association → Visual Feature Analysis → Temporal Grading → Session Records → Frontend Display.

Identify exactly which functions are actually called during live inspection.

Determine which existing features are:

- Fully integrated
- Partially implemented
- Diagnostic-only
- Experimental
- Not connected to the live application
- Broken or unavailable

Do not describe unused code as a working feature.

# 4. FIX CAMERA INITIALIZATION AND OFFLINE STATE

The current UI has displayed:

- Inspection feed: OFFLINE
- AI processing: 0.0 FPS
- Camera is currently stopped
- Preview FPS and display latency are not measured

First distinguish normal stopped-state behavior from actual camera startup failure.

When the camera is stopped, 0.0 FPS is expected and should not be reported as a performance defect.

Inspect and repair:

1. Camera device detection.
2. Camera initialization.
3. Correct device selection.
4. Backend API connectivity.
5. Camera permission and device conflicts.
6. Frame acquisition.
7. Start/stop/restart lifecycle.
8. Camera resource cleanup.
9. Frontend live-feed connection.
10. Error reporting.

Ensure that clicking **Start inspection** actually starts the real processing pipeline when the configured camera and models are available.

Ensure that **Stop inspection** releases the camera and processing resources.

Ensure that **Reset session** correctly resets relevant session state without unintentionally modifying model configuration or saved records.

Do not fake an online camera status.

# 5. RESOLVE THE BYTETRACK WARNING

Current warning:

`Active tracker: IoU fallback (optional ByteTrack lap dependency unavailable)`

Investigate its root cause.

Verify:

- The actual Python interpreter running the backend.
- The activated virtual environment.
- Installed Ultralytics version.
- Installed tracking dependencies.
- Availability and compatibility of `lap` or other dependency required by the installed tracker implementation.
- Windows and Python compatibility.
- Actual tracker configuration and execution path.

If the required package can be installed safely:

1. Install it in the correct project environment.
2. Record the compatible dependency.
3. Update the appropriate dependency specification.
4. Restart the backend.
5. Confirm tracker initialization.
6. Confirm that actual tracking uses the intended algorithm.

Do not merely suppress the warning or replace its text.

If the intended tracker remains unavailable, preserve a functional fallback and report why.

Verify fish ID stability through:

- Single-fish movement
- Multiple separated fish
- Touching fish
- Overlapping fish
- Temporary occlusion
- Fish entering and leaving the frame
- Partial detections

The application must not assign one fish's head, body, tail, or grade to another fish.

An ambiguous overlapping pair must not make a distant, clearly visible third fish ambiguous.

# 6. INVESTIGATE AND IMPROVE LOW FPS

Target inspection environment:

- HP Victus 15
- NVIDIA RTX 2050
- Windows
- Overhead camera
- Controlled white LED lighting
- Continuously moving conveyor belt

Previous observations suggest approximately 5 FPS, but this must be remeasured rather than treated as a hardware limit.

## A. Verify Hardware Acceleration

Check:

- NVIDIA GPU availability
- Driver compatibility
- CUDA-enabled PyTorch installation
- `torch.cuda.is_available()`
- Actual device used by Model 1
- Actual device used by Model 2
- Model initialization and device transfers
- GPU memory utilization
- CPU and RAM utilization

An NVIDIA GPU being physically installed does not establish that CUDA is active in the application's Python environment.

If CUDA is unavailable, investigate a compatible solution without blindly replacing dependencies or breaking model compatibility.

Never report GPU acceleration unless the actual process uses it.

## B. Profile Each Processing Stage

Measure separately:

1. Camera capture
2. Frame transfer and decoding
3. Model 1 inference
4. Tracker association
5. Model 2 inference
6. Part-to-fish assignment
7. Visual feature extraction
8. Grading calculations
9. Database operations
10. Frame annotation
11. Image encoding
12. Frontend delivery and rendering

Collect actual timing measurements.

Measure average and percentile latency where useful.

Do not estimate FPS from configuration values.

## C. Optimize Real Bottlenecks

After identifying the slowest stages, implement appropriate optimizations.

Investigate:

- Repeated model loading
- CPU/GPU transfers
- Unnecessary inference calls
- Repeated full-frame Model 2 processing
- Inefficient per-fish crops
- Excessive frame copying
- Image encoding overhead
- Blocking database operations
- Preview rendering bottlenecks
- Unnecessary synchronous processing
- Inefficient tracking or association
- Excessive frontend polling
- Memory growth and resource leaks

Where supported by the actual architecture, consider:

- Persistent model instances
- GPU inference
- Controlled inference scheduling
- Safe model batching
- Selective Model 2 inference
- Reusing valid temporal evidence
- Independent preview and AI processing pipelines
- Bounded frame queues
- Dropping obsolete preview frames rather than accumulating latency
- Performing expensive feature extraction only when justified

Do not introduce optimization changes blindly.

Do not trade grading correctness for higher FPS without measured, documented evaluation.

# 7. KEEP LIVE VIDEO RESPONSIVE

The raw camera preview and AI processing should not unnecessarily block each other.

Preserve the existing raw preview functionality, which is currently disabled by default.

If beneficial, improve its architecture so that:

- Camera acquisition remains responsive.
- AI inference runs at a measured processing rate.
- The interface receives fresh available frames.
- Old queued frames do not accumulate indefinitely.
- Tracking identities remain associated with the correct source frames.
- Session controls remain responsive.
- Classification results correspond to the correct fish.

Track these independently:

- Camera capture FPS
- AI processing FPS
- Preview/display FPS
- End-to-end display latency
- Time from fish entry to final grade
- Frame or evidence age

Do not label preview FPS as AI inference FPS.

Do not invent measurements for the existing MJPEG or browser rendering path.

# 8. MAKE BOTH MODELS WORK CORRECTLY

## Model 1 — Fish Detection and Tracking

Model 1 is responsible for:

- Detecting actual Tamban fish
- Supporting fish tracking
- Supporting unique fish counting
- Distinguishing fish from non-fish objects

Rejected-quality Tamban are still fish and must remain valid Model 1 detections.

Do not classify packaging, shadows, tools, or empty-belt objects as Rejected fish.

A non-fish false positive is a detection error, not a valid Ungraded fish.

## Model 2 — Anatomical Quality Evidence

Model 2 is responsible for grade-aware evidence from:

- Head
- Body
- Tail

Verify that Model 2 outputs are assigned to the correct parent fish.

Keep each fish's:

- Detection ID
- Track ID
- Part observations
- Part scores
- Temporal evidence
- Final classification

separate.

Do not copy one fish's grade to every fish in a multi-fish frame.

Test overlapping and closely positioned fish.

# 9. PRESERVE ADAPTIVE TAIL-OPTIONAL GRADING

The documented grading policy uses:

### Scenario A — Three Reliable Components

Body: 50%

Head: 30%

Tail: 20%

Weighted Support =
(Body × 0.50) + (Head × 0.30) + (Tail × 0.20)

### Scenario B — Tail Unavailable

Body: 62.5%

Head: 37.5%

Tail: 0%

Weighted Support =
(Body × 0.625) + (Head × 0.375)

The absence of tail evidence must not automatically create a zero-score penalty.

However:

- Reliable defective-tail evidence must not be silently discarded.
- An occluded head is not equivalent to a physically missing head.
- An unavailable mandatory head or body leaves insufficient grading evidence under the discussed policy.
- A detector miss must not be interpreted as physical damage.
- A physically missing head must follow a vendor-approved rule, not an invented one.
- Low confidence or conflicting evidence may require Ungraded.

Test tail detection appearing, disappearing and flickering over time.

Preserve all existing approved thresholds.

Do not invent new grade caps or rejection criteria.

# 10. INTEGRATE THE EXISTING VISUAL FEATURES

The research documentation specifies that Model 2 and validated visual features are intended to work together.

Inspect all existing feature modules.

Identify whether the application already supports:

- Color and saturation
- Brightness
- Discoloration or yellowing
- Shininess and specular highlights
- Texture
- Morphology
- Foreground or part masks
- Visible cracks
- Belly tears
- Relative defect length
- Relative defect width
- Relative defect area

Trace every feature through:

Input Image → Correct Fish/Part Region → Feature Extraction → Result → Grading or Diagnostics → Frontend.

If a feature exists but is not connected to the real inspection pipeline, determine whether it can be safely integrated.

IMPORTANT:

Not every feature may influence the final grade immediately.

Separate:

1. Validated grading features
2. Diagnostic measurements
3. Experimental feature fusion
4. Unsupported or incomplete feature claims

Keep unvalidated feature fusion disabled by default and expose it clearly as experimental where useful.

Do not automatically grade every yellowish fish as C.

Do not assume every shiny fish is A.

Do not interpret every image edge as a crack.

Do not apply a new crack threshold or automatic rejection rule without the required vendor/professor approval.

Where features are only diagnostic, make that visible in the application rather than pretending they affect grading.

Benchmark the cost of enabled feature extraction.

# 11. CONNECT EVERYTHING TO THE ACTUAL USER INTERFACE

THIS SECTION IS MANDATORY.

I do not want features that exist only in source files.

I want the existing application to use them correctly.

Inspect and repair the following actual application sections.

## A. Inspection Feed

- Show the real camera feed when running.
- Show accurate processing and connection status.
- Show Model 1 fish detections where applicable.
- Show Model 2 part evidence and annotations where applicable.
- Preserve correct track identity.
- Avoid stale overlays.
- Show meaningful camera, model and runtime errors.

## B. Camera Settings

Verify working settings for the supported camera properties.

Ensure applied settings affect actual camera operation where supported.

Unsupported settings must be clearly identified.

## C. Inspection Controls

Ensure the following work:

- Start inspection
- Stop inspection
- Reset session
- Analyze image

Verify actual backend behavior through the UI.

For Analyze image, ensure the uploaded image uses the correct detection and grading pipeline while preserving isolation from the active live-camera session.

## D. Feed Display Options

Ensure display controls modify the actual feed presentation.

Where supported, let users view:

- Processed annotated feed
- Raw camera preview
- Detection overlays
- Track IDs
- Part evidence

Keep expensive optional displays disabled when appropriate.

## E. Session Totals

Make these counters reflect actual backend results:

- Fish detected
- Graded fish
- Class A
- Class B
- Class C
- Rejected
- Ungraded

Prevent duplicate counts from repeated frames.

Track physical fish uniquely.

Do not count the same fish every time Model 1 detects it.

## F. Latest Inspection

Display the actual latest fish result.

Include:

- Fish/track identifier
- Final grade, if available
- Confidence or support with correct labeling
- Grading mode
- Component evidence
- Ungraded reason when applicable

Do not show fabricated part evidence.

## G. Part Evidence

Display individual:

- Body evidence
- Head evidence
- Tail evidence

Clearly distinguish observed, unavailable and uncertain regions.

Show which weighting scheme was used.

## H. Recent Inspections

Ensure completed fish are recorded and displayed after the appropriate finalization/counting event.

Preserve access to full inspection history.

## I. Part Observations

Head, Body and Tail counters must reflect actual Model 2 observations.

Do not replace them with simulated counts.

## J. Session Analytics

Connect actual data to:

- Grade distribution
- Throughput
- Detection outcomes
- Ungraded reasons
- Evidence measurements
- Tracking statistics

## K. Runtime Diagnostics

Make diagnostics useful for identifying actual bottlenecks.

Include:

- Active tracker and fallback reason
- Model devices
- Camera status
- Actual AI FPS
- Actual preview FPS, if instrumented
- Capture and inference timing
- Per-stage processing timing
- Frame latency
- Skipped or dropped frames
- Queue or backlog indicators
- Recording overhead where measurable
- Model and configuration identity

Values must come from actual runtime instrumentation.

If a metric is unavailable, display `Not measured`, not an invented value.

## L. Historical Records and Exports

Verify that saved inspections retain:

- Original AI grade
- Fish/track identification
- Model identity
- Configuration or grading-policy version
- Part evidence
- Final grading mode
- Ungraded reason
- Relevant timing information
- Reviewer outcome separately from the original AI output

Ensure CSV/XLSX exports preserve these distinctions and existing export safety protections.

# 12. CONTINUOUS CONVEYOR REQUIREMENTS

The physical conveyor must continue moving.

Do not assume that the belt can stop while the AI finishes classifying a fish.

Each physical fish must:

1. Enter the usable inspection region.
2. Be detected by Model 1.
3. Receive a consistent tracking identity.
4. Accumulate valid Model 2 evidence.
5. Receive eligible feature measurements where supported.
6. Produce a final grade or Ungraded outcome.
7. Be finalized before the applicable inspection deadline where achievable.
8. Be counted only once.

Measure whether the system can make its decision before the fish exits the relevant inspection area.

If the deadline is missed, record the failure.

Do not assign a late grade to a different fish.

# 13. TEST AGAINST THE RESEARCH CHECKLIST

Use the dataset categories in the uploaded document as the validation plan.

### A — Fish Reference Scenarios

Test A/B/C/Rejected samples, different poses, sizes, positions, borderline grades, missing tails and distinct physical specimens.

### N — Non-Fish Negatives

Test empty conveyor frames, trays, plastic, foil, paper, tools, cloth, shadows, glare, printed fish images and observed false-positive objects.

### M — Mixed and Overlapping Fish

Test multiple fish, mixed grades, touching fish, overlapping fish, occluded regions, ambiguous ownership and crowding.

### L/V — Lighting and Video Motion

Test normal controlled LEDs, lighting challenges, moving fish, different belt speeds, motion blur, and full entry-to-exit passages.

### D — Cracks and Defects

Test intact fish, natural texture lines, possible belly openings, visible damage and occluded defects.

Do not treat proposed defect categories or measurements as approved automatic grading rules.

Use existing authentic datasets where available.

Do not fabricate images, labels, vendor grades or missing observations.

Preserve specimen-level separation between training, validation and final testing.

# 14. PERFORMANCE AND SCIENTIFIC ACCEPTANCE

The goal is not FPS alone.

The application must maintain scientifically meaningful behavior.

Measure, when evidence is available:

- Model 1 detection and false positives
- Model 2 part evidence reliability
- Tracking and counting errors
- Parent-part association errors
- Fish grading coverage
- Vendor-grade agreement
- Ungraded frequency and reasons
- Final decision latency
- AI processing FPS
- Preview FPS
- Actual conveyor deadline compliance

Use the same representative scenarios when comparing before and after optimization.

The reference vendor must provide grades independently before seeing AI outputs.

Preserve original judgments separately from later disagreement reviews.

Do not tune on an independent final test set.

Do not claim an arbitrary FPS target, accuracy percentage, or acceptable Ungraded threshold has been approved.

# 15. REQUIRED ACTUAL APPLICATION TESTING

After implementing changes, run the existing application using its supported startup procedure.

Where the environment permits:

1. Start the backend.
2. Start the frontend.
3. Open the actual application.
4. Test Start inspection.
5. Confirm camera acquisition.
6. Confirm Model 1 is executing.
7. Confirm tracking and active tracker identity.
8. Confirm Model 2 is executing when required.
9. Confirm grading results are generated appropriately.
10. Confirm correct UI updates.
11. Check runtime diagnostics.
12. Test Analyze image.
13. Test Stop and restart.
14. Verify history and exports.
15. Test representative screen sizes.

Do not stop at Python unit tests.

If browser automation is available, use it.

If hardware is unavailable, use prerecorded real frames or supported test fixtures to verify the application integration, but distinguish these results from physical-camera acceptance.

Never claim a real camera test occurred if it did not.

# 16. AUTOMATED AND REGRESSION TESTING

Preserve the existing successful QA work.

The previous Final Polish QA phase reported:

- 588 model-free tests passed
- 6 skipped
- 2 CPU checkpoint compatibility tests passed
- Browser checks passed at selected viewport sizes

Treat these as historical results, not guarantees about the current code.

After changes:

- Run appropriate unit tests.
- Run integration tests.
- Test camera lifecycle.
- Test tracker availability and fallback.
- Test multi-fish tracking.
- Test optional-tail grading.
- Test missing head/body behavior.
- Test false positives.
- Test Model 2 evidence ownership.
- Test frontend API integration.
- Test session counters.
- Test history and exports.
- Run relevant full regression checks.

Fix newly introduced regressions before proceeding.

# 17. DEVELOPMENT AND PROGRESS RECORD

Create or update:

`TAMBAN_LIVE_FPS_TRACKER_FEATURE_REPAIR.md`

Record:

- Original problem
- Root cause
- Affected source files
- Changes implemented
- Features connected to the live pipeline
- Dependencies repaired
- Before/after performance measurements
- Tests executed
- Browser and UI checks
- Hardware tests performed
- Unverified requirements
- Remaining research approvals
- Rollback considerations

Clearly identify any unavailable hardware or independent data.

# 18. SUCCESS CRITERIA

This task is successful only when the available evidence supports the following:

1. Camera startup and lifecycle are functional in the tested environment.
2. Intended tracker dependencies are correctly resolved, or the remaining fallback is clearly justified.
3. Actual tracking remains associated with the correct fish.
4. Models are loaded and executed through the real inspection pipeline.
5. The latest approved grading rules are preserved.
6. Existing validated features are used as intended.
7. Unvalidated features remain explicitly experimental or diagnostic.
8. The frontend correctly displays real runtime outputs.
9. Session counters and inspection records are consistent.
10. Actual performance measurements are reported honestly.
11. Any FPS improvements are supported by comparable measurements.
12. No significant regression in counting, grading, or false-positive handling is introduced.
13. The application remains usable on the intended inspection laptop.
14. Remaining research and hardware validation gaps are documented.

Do not declare full success solely because automated tests pass.

# 19. FINAL OUTPUT

Provide a structured report:

| Component | Initial Problem | Fix Implemented | Validation | Status |
|---|---|---|---|---|
| Camera | Actual finding | Actual fix | Actual result | Status |
| Tracker | Actual finding | Actual fix | Actual result | Status |
| Model 1 | Actual finding | Actual fix | Actual result | Status |
| Model 2 | Actual finding | Actual fix | Actual result | Status |
| FPS | Actual finding | Actual fix | Actual result | Status |
| Grading | Actual finding | Actual fix | Actual result | Status |
| Features | Actual finding | Actual fix | Actual result | Status |
| Frontend | Actual finding | Actual fix | Actual result | Status |
| Analytics | Actual finding | Actual fix | Actual result | Status |
| History | Actual finding | Actual fix | Actual result | Status |

Also include:

- Actual files modified
- Dependencies installed or changed
- Whether ByteTrack is truly active
- Whether CUDA is truly active
- Original measured FPS
- Optimized measured FPS
- Actual real-camera or replay conditions
- Features successfully connected to the UI
- Remaining blockers
- Remaining vendor/professor approvals
- Final release readiness

# START IMPLEMENTATION

Begin by inspecting the uploaded requirements document and existing application.

Reproduce the reported tracker warning.

Establish the real runtime environment and camera state.

Identify why tracking falls back to IoU and why AI processing is slow when the camera is genuinely active.

Then repair and optimize the actual system.

Connect the resulting functionality to the existing frontend and verify it end-to-end.

**Do not finish with code-only changes or generic optimization recommendations. Perform the implementation, run available validation, and show what actually works in the application.**