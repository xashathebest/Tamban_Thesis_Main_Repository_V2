# Confirmed source-code touchpoints in supplied ZIP (2026-11-04 snapshot)

- `Thesis/sardinella-lemuru-ml/frontend/index.html`: sidebar nav buttons have `data-view="live"`, `history`, `review`, `model`; view sections `id="view-live"` etc.
- `frontend/app.js`: `viewMeta` near beginning and `showView(view)` with toggles, nav activation; modify minimally and add separate capture module if feasible.
- `frontend/styles.css`: existing theme/layout/responsive styles. Reuse rather than redesign.
- `src/api/app.py`: FastAPI app with camera status, selection, inspection start/stop, `GET /api/video-feed`, and `GET /api/video-feed/raw`. Existing inspection handlers are **protected**; only minimal additive registration of new capture routes is allowed if needed, and a separate sidecar app is preferable if strict startup isolation requires it.
- `src/api/camera.py`: **READ ONLY / DO NOT EDIT**. `CameraInspectionService` performs webcam reads in `_capture_frames`; provides frames to inference and optional raw preview. The separate dataset capture must not call this service or alter existing ownership and control.
- `src/api/raw_preview.py`: **READ ONLY / DO NOT EDIT**. Existing raw preview is subscriber-enabled, JPEG encoded, and bounded; it is *not* guaranteed full-fidelity data capture and must not be used by the independent Capture tab.
- `FISH_RAW_PREVIEW_ENABLED` defaults false in camera initialization; do not assume raw MJPEG works without configuration.
- `src/api/lan_security.py`: optional LAN auth; mutating requests must honor operator authorization and browser CSRF/same-origin requirements.
- `run_dashboard.ps1`: defaults `FISH_STRICT_MODEL_INTEGRITY=1`; capture-only mode must not defeat model verification for inspection.
- `src/inference/grading_policy.py`, `src/inference/grading_engine.py`, `src/inference/association.py`, `configs/grading_engine.yaml`, `models/MODEL_REGISTRY.json`, original COCO dataset: protected, not editable in this assignment.
- `docs/feature_fusion_experiment.md`: present feature-fusion evidence is offline research only; not authorized for live grading.
- `requirements.txt`: does not currently list a Google Drive Python client package. Obtain owner approval before adding new runtime dependency.

Add new files for the Capture-only backend (e.g. `src/api/dataset_capture/`) and frontend (`frontend/capture.js`) rather than editing inspection camera modules. The manually triggered `POST /api/capture/snapshot` must save one fresh original via capture-only acquisition; it is not an alias for existing inspection snapshot/preview.

These touchpoints were read from the uploaded ZIP, not an executed local Git clone. Re-check in the actual working checkout before editing.
