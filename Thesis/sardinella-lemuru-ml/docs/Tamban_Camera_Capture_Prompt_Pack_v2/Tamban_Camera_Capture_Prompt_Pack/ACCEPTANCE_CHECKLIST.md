# Owner acceptance checklist — Camera Capture

## Before collection
- [ ] The Capture tab is visible in the existing sidebar and existing pages work.
- [ ] Camera Capture is a separately owned **data-gathering-only** entity, not a mode or refactor of Live Inspection.
- [ ] Inspection camera API, current camera usage, device settings, start/stop, preview and model/inference path remain unchanged.
- [ ] A busy shared webcam produces an explicit refusal; Capture never stops/restarts/modifies inspection. Selecting a verified separate physical camera is permitted.
- [ ] Capture-only camera works when model checkpoints are unavailable; inspection still correctly requires its checkpoints.
- [ ] Starting Capture while live inspection owns the webcam is refused or handled with an explicit safe transition; no competing camera readers.
- [ ] Preview shows real camera readback resolution/index; saved image is original unannotated frame, not preview screenshot.
- [ ] Session includes date, source/batch, physical fish ID (if known), provisional label and notes.

## Timed capture
- [ ] 5-second countdown; then a unique fresh image is scheduled once per second.
- [ ] 10-second countdown; then a unique fresh image is scheduled once per second.
- [ ] Separate 5-second and 10-second capture durations are available.
- [ ] A prominent **Capture Photo** button works with NO automatic timer; each click saves exactly one fresh original photo with `capture_mode=manual`.
- [ ] Manual shots work safely alongside automatic capture without double-saving the same frame and use the same local + Drive path.
- [ ] 1s default interval; configurable 2s/5s; count presets and manual shutter.
- [ ] Start, pause, resume and stop are responsive; duplicate/stale frames are not silently saved as new shots.
- [ ] Gallery, counters, thumbnail review, warnings, native resolution and exported manifest are correct.

## Google Drive
- [ ] No credentials committed to Git or visible in JS/logs/browser storage.
- [ ] A Drive folder link without authorization leaves sync disabled (honest status).
- [ ] After authorized connection, a real test image appears in the requested folder with correct name and metadata.
- [ ] Unsynced local files survive offline mode, restart, token expiration, throttling and retry.
- [ ] Duplicate remote files are not created on retry, and synced status requires an actual Drive API success.
- [ ] Existing destination files are never overwritten or deleted.

## Science and safety
- [ ] The system does not mistake 1,000 photos for 1,000 independent fish.
- [ ] Blurry/duplicate warnings are non-destructive; tentative tags are not expert ground truth.
- [ ] Old COCO dataset, model weights, registry, grading logic and original results are unchanged.
- [ ] Test IDs and outcomes have been compared with baseline; real camera/Drive demonstrations labeled measured or untested.
