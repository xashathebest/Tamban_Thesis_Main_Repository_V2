# Tamban Camera Capture / Pre-Collection Upgrade — Prompt Pack

**What this ZIP is:** Copy-ready instructions for a coding agent that has access to an actual Git checkout. These are NOT installed fixes. The uploaded repo ZIP lacks `.git` history and has LFS pointers instead of usable models, so do not claim hardware/model/Drive validation based on a ZIP audit.

**Use now:** Send `MASTER_PROMPT.md` to your coding agent. It must do only Phase 0 first and wait for `go`. For narrower changes, use `01` through `05` in sequence, authorizing each separately.

**What you asked for:** A new, INDEPENDENT, data-gathering-only sidebar `Camera Capture` entity that does not touch or change existing Live Inspection camera usage; a prominent one-click **Capture Photo** manual button (no timer required); timer buttons 5s and 10s; continuous capture one fresh frame every second; option for 5s/10s timed bursts; capture session metadata and gallery; direct automatic Google Drive syncing with durable local backup; streamlined dataset provenance/quality review.

**What the user must provide later:** Google Drive **folder link(s)**, whether the destination is personal My Drive or a shared drive, and which secure authorization mode to use. The app needs OAuth authorization or a service account with actual folder access; just a link is insufficient. Do not put credentials in chat prompts or repositories.

**Safety:** No changes to `src/api/camera.py`, `src/api/raw_preview.py`, existing Live Inspection camera routes, controls or startup/shutdown behavior. The new capture component must never auto-stop or manipulate inspection. The same physical webcam cannot be simultaneously opened by two owners; the capture page must refuse gracefully and ask the user to stop inspection manually or choose a different camera. No change to grade logic, model weights, model registry, original dataset, or production feature fusion. New captures are kept separate. Tests and real camera uploads must be verified, not asserted.

Files:
- `MASTER_PROMPT.md` — full agent prompt with explicit phase gates.
- `01_BASELINE_AND_PRECOLLECTION_AUDIT.md` — inspect and prioritize before touching code.
- `02_CAMERA_CAPTURE_UI_AND_ENGINE.md` — sidebar, countdown, interval, acquisition mode, gallery.
- `03_GOOGLE_DRIVE_UPLOAD.md` — auth, sync, retries, integrity, offline support.
- `04_METADATA_AND_IMAGE_QUALITY.md` — annotation readiness and capture quality.
- `05_TESTS_AND_HANDOFF.md` — acceptance tests, regression gates, documentation.
- `DRIVE_SETUP_TEMPLATE.md` — safe fields to fill after sharing links.
- `REPO_TOUCHPOINTS.md` — source-code locations confirmed in supplied archive.
- `ISOLATION_AND_MANUAL_CAPTURE_REQUIREMENTS.md` — noninterference contract, manual button requirements, and acceptance tests.
- `ACCEPTANCE_CHECKLIST.md` — operator walk-through and acceptance gate.
- The feature extraction and offline feature-fusion upgrade is in the **separate** `Tamban_Feature_Extraction_and_Grading_Fusion_Prompt_Pack.zip`. Do not merge their authorization gates.
