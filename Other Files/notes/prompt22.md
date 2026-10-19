We have completed the previous stabilization and validation-readiness work.

DO NOT perform another broad refactor.

We now have REAL runtime evidence from the conveyor UI showing four concrete
production problems:

1. Model 1 produces high-confidence false positives on non-fish objects.
2. Model 2 evidence exists internally, but Body/Head/Tail overlays are not
   visibly rendering in the live feed.
3. Most fish become Ungraded because Model 2 support is very low.
4. Runtime performance is poor: approximately 5.9 FPS on CPU.

This task is a focused runtime diagnosis and correction pass.

DO NOT:
- weaken grading safeguards just to produce more grades
- reduce the 50% final threshold merely to hide low Model 2 confidence
- restore missing-evidence renormalization
- modify Body=50%, Head=30%, Tail=20%
- fabricate physical missing-part claims
- make unsupported defect claims
- perform automatic threshold optimization
- retrain models unless explicitly instructed after diagnosis

==================================================
OBSERVED LIVE EXAMPLE
==================================================

The current live UI showed:

Model 1:
- a clearly non-fish red/white object was detected as:
  Fish #1 | D 85.1%

Other fish detections were approximately:
74.8%
79.7%
79.4%

Latest fish result:

Ungraded

Model 1 detection:
85.3%

Model 2:
Body:
Class C evidence 31.4%
original weight 50%
contribution 15.7%
22 frames

Head:
Class C evidence 33.6%
original weight 30%
contribution 10.1%
7 frames

Tail:
not detected

Final Class C support:
25.8%

Final threshold:
50%

Therefore Ungraded is mathematically correct under the current grading
policy.

The problem is NOT primarily the final grading arithmetic.

The problems to diagnose are upstream.

==================================================
1. DO NOT CHANGE GRADING POLICY
==================================================

Freeze:

Body = 50%
Head = 30%
Tail = 20%

No missing evidence renormalization.

Final support threshold remains unchanged for this diagnostic task.

Ungraded must remain a valid outcome.

We need to understand WHY Model 2 evidence is weak rather than lowering
standards until it passes.

==================================================
2. MODEL 1 FALSE-POSITIVE DIAGNOSTICS
==================================================

Model 1 currently labels obviously non-fish objects as fish, including at
high confidence (~85%).

Add diagnostic support to inspect Model 1 false positives.

For each Model 1 detection expose in debug mode:

track ID
confidence
bounding box
box width/height
aspect ratio
area
frame number
whether Model 2 found any compatible part evidence inside it

Do not create arbitrary geometric rejection rules unless clearly justified.

Do NOT simply raise the Model 1 threshold because the observed false
positive already had confidence around 85%.

Add a research/debug mechanism to save false-positive crops.

Example:

results/hard_negatives/
    session_x/
        frame_000123_track_1_conf_0.851.jpg
        ...

Allow operator to mark:

NOT_FISH

This is for future hard-negative dataset construction.

It must not feed directly into production inference.

Report clearly that high-confidence false positives generally require
dataset/model correction rather than only threshold adjustment.

==================================================
3. HARD-NEGATIVE DATA PREPARATION
==================================================

Prepare, but DO NOT retrain automatically, a research-only hard-negative
workflow.

Typical real conveyor negatives may include:

- tools
- rulers
- cables
- hands
- labels
- scraps
- belt hardware
- reflections
- light-colored objects
- background artifacts

Allow saved false-positive crops/frames to be catalogued for future Model 1
retraining.

Do not modify Model 1 checkpoint during this task.

==================================================
4. TRACE MODEL 2 END TO END
==================================================

The UI currently reports Model 2 evidence, meaning Model 2 is running.

However, the live feed does not visibly show Body/Head/Tail boxes even though:

Part overlays = enabled
Part labels = enabled

Trace the entire Model 2 visualization path:

Model 2 raw detector output
→ ROI coordinate system
→ conversion to full-frame coordinates
→ association
→ API/WebSocket serialization
→ frontend state
→ overlay rendering

Determine exactly where the part detections disappear.

Do not guess.

==================================================
5. ADD MODEL 2 RAW DEBUG OVERLAY
==================================================

Add a DEBUG-ONLY overlay mode with separate visibility controls:

[ ] Model 2 raw boxes
[ ] Model 2 associated boxes
[ ] Model 2 rejected/unassigned boxes
[ ] Model 2 labels
[ ] ROI boundary

Use visually distinguishable rendering.

Example semantics:

Raw candidate:
Body C 31.4%

Associated:
Body → Fish #4

Unassigned:
Head | ambiguous

Rejected:
Tail | below threshold

Do not change production grading based on visualization.

==================================================
6. VERIFY MODEL 2 CLASS MAPPING
==================================================

Audit checkpoint class metadata against runtime class interpretation.

Explicitly print/log the checkpoint class mapping at startup.

Verify:

class index
class name

and ensure the runtime does not accidentally interpret one class as another.

Check for mismatches between:

training data class names
checkpoint names
runtime configuration
frontend labels
grading policy labels

Fail loudly in diagnostics if mappings are inconsistent.

Do not silently remap unknown classes.

==================================================
7. INSPECT EXACT MODEL 2 INPUT
==================================================

This is critical.

Add debug capture so we can see EXACTLY what Model 2 receives.

For selected tracks save:

A. original frame

B. Model 1 fish box drawn on original frame

C. exact cropped ROI sent to Model 2

D. resized/preprocessed Model 2 tensor visualization where reasonable

E. raw Model 2 detections

Example:

results/debug/model2/
    fish_4/
        frame_001_original.jpg
        frame_001_roi.jpg
        frame_001_detections.jpg
        metadata.json

metadata should contain:

fish ID
frame number
Model 1 box
ROI padded box
ROI original dimensions
Model 2 input dimensions
resize method
padding/letterbox information
Model 2 confidence threshold
raw detections

This must be debug-only and bounded so it does not fill the disk.

==================================================
8. VERIFY ROI COORDINATE TRANSFORM
==================================================

Audit conversion between:

full-frame coordinates
Model 1 crop
padded ROI
Model 2 resized input
Model 2 output coordinates
full-frame overlay coordinates

Add unit tests.

Test:

normal fish
fish near left edge
fish near right edge
fish near top
fish near bottom
padded crop clipped by image boundary
non-square ROI
rotated-looking elongated ROI

Ensure letterboxing/resizing is correctly reversed.

A coordinate transform bug could explain why Model 2 evidence exists but its
boxes do not appear where expected.

==================================================
9. REVIEW ROI PADDING
==================================================

Do not automatically change ROI padding.

Measure it.

For each Model 2 inference record:

original Model 1 ROI
padded ROI
fraction of crop occupied by fish
fraction occupied by background

If padding is so large that fish becomes very small inside the Model 2 input,
report it.

If padding cuts off anatomy, report it.

Provide evidence before recommending a new value.

==================================================
10. MODEL 2 CONFIDENCE DIAGNOSTICS
==================================================

We are seeing Model 2 evidence near:

0.31
0.34

Do not immediately lower thresholds.

Collect distributions from a controlled run.

Record raw Model 2 confidence for:

Body
Head
Tail

including detections below the current production threshold in DEBUG MODE.

Produce summary statistics:

count
min
median
mean
max
p25
p75

Also distinguish:

raw detector confidence
selected candidate confidence
temporally aggregated support
final weighted contribution

These are NOT the same quantity.

The UI must make that distinction clear.

==================================================
11. MAKE THE UI TERMINOLOGY CLEAR
==================================================

Currently users may confuse:

Model confidence
Part evidence
Weighted contribution
Final support

Make these explicitly separate.

For example:

BODY
Detector confidence: 31.4%
Observed frames: 22
Original weight: 50%
Weighted contribution: 15.7%

Do not label all four concepts simply "confidence."

==================================================
12. WHY UNGRADED
==================================================

Improve the detailed explanation.

For the observed case it should communicate approximately:

Body C support:
31.4% × 50% = 15.7%

Head C support:
33.6% × 30% = 10.1%

Tail:
not sufficiently observed

Total Class C support:
25.8%

Required support:
50.0%

Result:
Ungraded

This is NOT Rejected.

Avoid implying a missing Tail is physically absent.

==================================================
13. PERFORMANCE PROFILING
==================================================

The live system currently runs around:

5.9 FPS

Profile, do not guess.

Measure separately:

camera capture time
Model 1 inference time
tracker time
ROI extraction time
Model 2 inference time per ROI
total Model 2 time per frame
association time
HSV time
overlay rendering time
JPEG encoding time
API/WebSocket transmission time
frontend render/update time

Report p50 and p95 where possible.

==================================================
14. REMOVE STALE-FRAME BACKLOG
==================================================

For a real-time conveyor system, do NOT allow an unbounded frame queue.

Use a latest-frame strategy where appropriate.

If inference is slower than camera capture:

discard stale unprocessed frames

rather than:

camera frame 1
camera frame 2
camera frame 3
camera frame 4
...
all accumulating in a queue.

Keep the latest useful frame.

Bound all queues.

Expose:

captured FPS
processed FPS
dropped frame count
current queue depth

==================================================
15. DECOUPLE PREVIEW FROM INFERENCE
==================================================

The UI preview should not need to wait for every complete two-model inference
cycle if the current architecture can safely avoid that.

Consider:

Camera capture thread/process
      ↓
latest frame
      ├── preview
      └── inference worker

Do not create a second VideoCapture.

The canonical camera manager remains the only camera owner.

==================================================
16. MODEL 2 SHOULD NOT RUN NEEDLESSLY
==================================================

Verify that Model 2 follows its configured interval.

Do not run Model 2 on every frame unless explicitly configured.

If Model 2 interval = N:

run it once every N eligible frames per active track or according to the
current documented semantics.

Prevent accidental multiple Model 2 inference passes for the same
track/frame.

Add counters:

Model1 calls/sec
Model2 calls/sec
Model2 ROI calls/sec

==================================================
17. DO NOT RUN MODEL 2 ON OBVIOUSLY INVALID TRACK STATE
==================================================

Use only already-supported runtime conditions.

Do not invent new fish-quality rules.

But ensure Model 2 is not repeatedly invoked for:

expired tracks
finalized tracks
invalid boxes
zero-area ROIs
boxes completely outside frame

Log skipped reasons in debug mode.

==================================================
18. CPU PERFORMANCE
==================================================

Current UI reports:

Device CPU

Optimize the existing CPU path conservatively.

Investigate:

PyTorch inference_mode/no_grad
model.eval()
avoiding repeated model loading
avoiding repeated tensor allocations where practical
bounded threads
OpenCV preprocessing overhead
unnecessary frame copies
unnecessary PIL conversions
redundant JPEG encode/decode
duplicate resizing

Do not change model behavior to gain speed.

==================================================
19. OPTIONAL GPU SUPPORT
==================================================

If the machine has a supported CUDA-capable NVIDIA GPU and the installed
PyTorch build supports CUDA, allow:

device = cuda

Otherwise remain on CPU.

Do not assume CUDA exists.

At startup report:

Requested device
Detected device
PyTorch CUDA availability
Model 1 device
Model 2 device

Do not download or replace PyTorch automatically.

==================================================
20. INPUT RESOLUTION
==================================================

Do NOT blindly reduce model resolution.

First report:

camera resolution
Model 1 input size
Model 2 input size
preview resolution

If optimization is considered, preserve model-compatible preprocessing and
document any change.

No silent accuracy/speed tradeoff.

==================================================
21. FRONTEND FEATURE AUDIT
==================================================

User reports that multiple features appear not to work.

Audit every visible Live Inspection control:

Part overlays
Fish IDs
Grades
Detector/support
Part labels
Outlines
Camera settings
Start inspection
Stop
Reset session
Analyze image
Export
settings button

For each control verify:

click handler
frontend state
request sent if applicable
backend state
actual visible effect

Add focused tests where practical.

Remove no-op UI controls only if truly obsolete.

Do not leave controls that visually toggle but do nothing.

==================================================
22. CAMERA SETTINGS AUDIT
==================================================

Verify the camera calibration/settings controls actually affect the single
canonical camera device.

For each supported property:

request value
apply value
read back actual value
return actual value to UI

If unsupported:
show unsupported

Never fake success.

==================================================
23. DEBUG PANEL
==================================================

Add a developer-only Runtime Diagnostics panel.

Include:

Capture FPS
Processing FPS
Dropped frames
Model 1 latency
Model 2 latency
Model 2 calls/sec
Active tracks
Current Model 1 detections
Current raw Model 2 candidates
Current associated parts
Unassigned parts
Inference device
Queue depth

Off by default.

==================================================
24. FALSE POSITIVE / MODEL 2 TEST MODE
==================================================

Add a research/debug workflow where operator can pause on a frame and inspect:

Model 1 boxes
Model 2 ROI
Model 2 raw boxes
Model 2 associated boxes
confidence values

This should help distinguish:

bad model
bad crop
bad threshold
bad coordinate conversion
bad association
bad overlay

Do not write these debug runs to production inspection history.

==================================================
25. DO NOT HIDE PROBLEMS BY TUNING
==================================================

During this pass:

DO NOT:
- lower Model 2 threshold merely to show more boxes
- lower final grade threshold
- raise Model 1 threshold merely to suppress the observed false positive
- change grading weights
- change missing-evidence policy

First produce diagnostics.

Any future threshold change must be evidence-based using development data,
not the final locked test set.

==================================================
26. REQUIRED TESTS
==================================================

Add regression tests for:

Model 2 raw detection serialization
ROI-to-full-frame coordinate conversion
part overlay payload
part overlay frontend rendering state where testable
one Model 2 call per scheduled track/frame
bounded frame queue
latest-frame replacement
finalized track does not run Model 2
unsupported UI controls do not silently succeed
camera property read-back
Model 1 false-positive debug capture does not alter production prediction

Preserve all existing tests.

==================================================
27. FINAL REPORT
==================================================

After completing the diagnostic/fix pass, report:

A. MODEL 1
- why the non-fish object can reach high confidence if determined
- whether this is code, dataset, or model behavior
- false-positive debug workflow created

B. MODEL 2
- whether raw detections exist
- exact raw class/confidence examples
- exact ROI fed to the model
- whether class mapping is correct
- whether coordinate transforms are correct
- whether overlays are fixed
- whether association is discarding candidates
- whether low confidence originates in model output or later aggregation

C. PERFORMANCE
- capture FPS
- processing FPS
- Model 1 latency
- Model 2 latency
- encoding/render latency
- identified bottleneck
- improvements applied
- resulting FPS

D. UI
- list every inspected control
- working / fixed / unsupported

E. GRADING
- confirm 50/30/20 unchanged
- confirm missing evidence remains non-renormalized
- explain why observed example remained Ungraded

Most importantly:

DO NOT make the system produce more grades just to make the UI look better.

Find the actual upstream causes.