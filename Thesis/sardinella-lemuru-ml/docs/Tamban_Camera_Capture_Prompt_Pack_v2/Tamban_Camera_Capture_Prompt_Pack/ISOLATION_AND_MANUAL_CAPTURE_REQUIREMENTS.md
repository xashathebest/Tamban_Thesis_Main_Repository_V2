# Camera Capture — independent entity + manual capture contract

## Purpose
This is an additional, **data-gathering-only** workspace. It must not change how Live Inspection uses the camera, handles devices, displays streams, starts/stops, tracks fish, runs inference, grades fish, or records inspection outcomes.

## Protected, read-only implementation
- No edits to `src/api/camera.py`, `src/api/raw_preview.py`, existing inspection camera API endpoint logic, current device preference/selection behavior, or existing inspection frontend handlers.
- No modifications to grading/association/ML modules, model registry, weights, original COCO dataset, existing inspection results, or strict inspection startup integrity.
- Changes to shared shell (`frontend/index.html`, a minimal additive nav registration in `frontend/app.js`, new capture-specific styles, thin route registration) must not modify existing handlers or UI flows.
- Build the feature as a separate `DatasetCaptureService`/router and `frontend/capture.js`, preferably supporting its own capture-only startup if checkpoints are absent.
- Never source dataset frames from MJPEG/video-feed screenshots, annotations, inspection buffers, or results; acquire unannotated source frames independently.

## The physical camera cannot be owned twice
- If the operator chooses a webcam already in use by Live Inspection, the Capture tab must show `Camera in use — stop inspection manually or choose a different camera` and refuse/disable capture. Never auto-stop/restart/switch/steal the inspection camera.
- The collection service may use a second separately selected physical camera if independent access is verified.
- If reliable protection against conflicting access cannot be done without editing existing camera code, STOP, explain the blocker and alternatives, and ask permission. Do not implement a shared lease by rewriting inspection.

## Manual capture interaction
- New Capture page prominently shows **Capture Photo** next to its *own* preview, with a clear local-save/Drive-sync status.
- In manual-only mode: open/start the capture-only camera, create/select a new collection session, and click **Capture Photo**. No countdown or automatic timer is required.
- One click must produce **exactly one** new, fresh, native-resolution, overlay-free frame and corresponding atomic file write + SHA-256 + manifest record. No file is created if capture fails, and the UI reports the actual failure.
- Multiple clicks produce distinct image IDs and distinct camera-frame identifiers; do not re-save an old cached frame. Use one capture-only camera reader regardless of manual vs timed capture; never open a second device handle for a snapshot.
- In a valid automatic session, manual requests serialize with scheduled shots; preserve correct scheduled cadence and report any delayed/skipped shot rather than hiding it.
- Allow keyboard Space shortcut when not typing, but do not trigger when focus is in inputs or dialogs.
- Store `capture_mode=manual|automatic`, UTC timestamp, camera/frame metadata, local path, checksum, provisional labels, and Drive queue status. Manual and automatic images use identical backup, safety and upload logic.

## Acceptance and stop gates
1. Test synthetic/manual: 1 click -> 1 fresh saved file; 2 clicks -> 2 unique files; no active auto timer needed.
2. Test conflict: preoccupied physical camera returns a clear busy state and leaves inspection running unchanged.
3. Test noninterference: existing inspection start/stop/device/preview APIs and UI remain as baseline; inspect `git diff` to verify their code is unchanged.
4. Test lost camera, disk full, interrupted writes, Drive disconnected/offline, and no-stale-frame behavior; capture never falsely claims a successful file or sync.
5. Hash the protected modules and dataset before and after. If protected camera code needs edits to proceed, STOP and ask rather than adjusting that code.
