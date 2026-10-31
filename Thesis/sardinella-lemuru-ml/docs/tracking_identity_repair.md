# Fish tracking identity repair

Date: 2026-10-31. This repair changes tracking, counting, and identity display.
It does not change camera pixels, model checkpoints, or grading policy.

## Causes

Empty detection lists never incremented fish IDs. Native trackers can consume
IDs for tentative detections and false positives that never become counted
fish. The application previously exposed those native numbers as `Fish #...`,
so a large displayed ID did not mean that many fish had been inspected.

The simple IoU fallback matched detections greedily against stationary boxes.
Movement, overlapping fish, or short gaps could fragment an identity. ByteTrack
also received only detections above the public confidence threshold, excluding
its weaker association evidence. Explicit Reset Count retained the old ID
offset. Separately, an expired domain track lost its counted flag: the same ID
could return, cross again, and increment in-memory totals while persistence
upserted the existing `(session_id, track_id)` record. The Current fish ID card
could also show the latest completed event after the scene became empty.

## Implemented behavior

- `ConfirmedFishIdentities` keeps native association IDs private and allocates
  sequential public fish IDs only after two actual, consecutive observations
  meeting the configured public detection confidence. Tentative detections stay
  unnumbered; empty frames and predicted positions do not confirm a fish.
- ByteTrack can use weaker detections down to its association threshold
  (normally `0.1`) to maintain an existing association. These weak observations
  cannot allocate native candidates or display a public fish ID. New native
  candidates require the configured public confidence; the track's configured
  lost-frame buffer also governs public identity retention. Actual unconfirmed
  observations preserve the first box for a two-frame crossing, while long
  sequences of weak measurements retain an existing confirmed identity.
  Public detection confidence
  remains configurable with its existing `0.5` default; `detect()` retains that
  threshold.
- The IoU fallback uses motion prediction and a global one-to-one assignment
  instead of matching each detection greedily. It does not emit predicted fish
  on an empty frame.
- `DetectionConfirmation` preserves the first observed box, confidence, and
  timestamp. The domain seeds both observed frames and immediately evaluates a
  crossing, preserving a fish that crosses on its confirmation frame without
  counting that frame twice.
- A session counted-ID guard survives track expiry and active-track cleanup.
  Returning IDs remain finalized and cannot create another event. The camera
  service uses `TrackingManager.is_counted()` to avoid reopening Model 2 evidence
  after a counted track expires. Only explicit session reset clears the guard.
- Reset Count clears history, counters, and ID state so the next confirmed fish
  is `Fish #1`. Stop/Start preserves operator history and uses the highest
  allocated ID as the next range offset, keeping later identities unique.
- Current fish ID is empty when only a historical event remains. Completed
  results remain available separately. An ID identifies a confirmed track;
  production totals still require a directional counting-line crossing.

## Validation and limits

Focused domain checks passed: 56 tests and 39 subtests, including two-frame
crossings in all four directions, timing/lifetime evidence, timeout/reentry,
archive eviction, reset, malformed detections, and existing grading acceptance.
The fallback's 11 regression tests cover association behavior. A synthetic
four-fish measurement was approximately `0.2061 ms` per tracker update on this
machine; it is not an end-to-end camera or AI FPS benchmark.

Final focused checks: **211 passed, 75 subtests passed**. The wider suite had
**757 passed, 6 skipped, 10 failed, 127 subtests passed**. The same ten failures
(nine model-selection fixtures and one UI wording check) were reproduced in an
isolated, unchanged `9c89e9f` source snapshot. Temporary media was placed outside
the project because the expert-library security boundary intentionally rejects
media paths inside the repository. Baseline evidence is retained in ignored
`tmp/tracking_baseline/comparison_summary.json`. Node verified that Current fish
ID clears for historical-only results and displays an active confirmed fish.

The local backend was restarted with camera index 1 and the existing confidence
thresholds. Both models and ByteTrack report ready; inspection remains stopped.
Refresh the dashboard and start inspection to use the corrected identity path.

These changes suppress transient identity allocation and repair ID/counting
state. They do not guarantee removal of persistent, confident model false
positives or correct reidentification of identical fish after full occlusion or
leaving the scene. Validate empty conveyors, moving fish, overlap, occlusion,
and reentry against annotated real footage before claiming improved detection
accuracy or counting accuracy. No image filters or checkpoint changes were used
to hide detection errors.
