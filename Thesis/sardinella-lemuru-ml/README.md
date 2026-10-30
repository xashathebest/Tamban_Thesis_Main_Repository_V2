# Sardinella Lemuru — Tamban Quality Grading System

A local inspection dashboard for automated Sardinella lemuru (Tamban dried fish)
quality grading using a two-model YOLO pipeline.

---

## Architecture

```text
Camera frame
    │
    ▼
Model 1 (YoloFishDetector)          — Whole-fish parent detection + ByteTrack
    │  one bbox + track_id per fish
    ▼
Model 2 (YoloQualityModel)          — 12-class Head/Body/Tail part detection
    │  per-part confidence, no mask
    ▼
Association                          — Conservative geometric parent-part ownership
    │  ASSIGNED / AMBIGUOUS / UNASSIGNED per detection
    ▼
WeightedGradingEngine                — Evidence-gated, temporally-aggregated verdict
    │  Body 50 % · Head 30 % · Tail 20 %
    ▼
Inspection event (Class A/B/C/Rejected/Ungraded)
```

### What the system does NOT claim

- It does not infer structural defects, cracks, yellowing, or missing anatomy.
- Model 2 emits independent detection confidences, not calibrated whole-fish probabilities.
- Ungraded is not the same as Rejected. A fish is Rejected only when Model 2 emits
  trained Rejected_* evidence above the configured threshold.
- A Model 2 inference failure leaves affected, unfinished fish Ungraded with
  `UG_MODEL2_UNAVAILABLE`; counting continues and finalized results are retained.
  Automatic retries begin after 0.25 seconds and back off to at most 5 seconds.

---

## Models

| Role | File | SHA-256 (first 16 hex) |
|------|------|------------------------|
| Model 1 — fish detector | models/fish_detector/weights/model1_fish_parent_detector.pt | 87498c748ceceb6a |
| Model 2 (YOLO26m, default and current selection) | models/yolov26/model2_tamban_yolo26m_partdet_r03_devbest.pt | f74cd336b6ba9274 |
| Alternative Model 2 | models/fish_quality/weights/last.pt | 9b5e48ae228705ae |
| Part-preview seg. | models/yolo_parts/yolo26n_seg_exp4/weights/exp-4.pt | c29bef8666967c89 |

The persisted selection and environment overrides can change the active checkpoint; inspect `/api/status` for a running instance. Full SHA-256 checksums and provenance: [models/MODEL_REGISTRY.json](models/MODEL_REGISTRY.json)

### Model 2 class schema (12 classes, fixed order)

| ID | Class | ID | Class |
|----|-------|----|-------|
| 0 | Grade_A_Body | 6 | Grade_C_Body |
| 1 | Grade_A_Head | 7 | Grade_C_Head |
| 2 | Grade_A_Tail | 8 | Grade_C_Tail |
| 3 | Grade_B_Body | 9 | Rejected_Body |
| 4 | Grade_B_Head | 10 | Rejected_Head |
| 5 | Grade_B_Tail | 11 | Rejected_Tail |

---

## Quick start

```powershell
# Create a project environment, then install its runtime and tracker dependencies.
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-bytetrack.txt

# Run the inspection dashboard (default: camera index 0). Require real ByteTrack
# rather than silently accepting the IoU fallback for an operator session.
$env:FISH_REQUIRE_BYTETRACK = '1'
.\.venv\Scripts\python.exe -m src.api

# Open the dashboard at http://localhost:8000
```

Use the same project interpreter for installation and startup; installing
`lap` into one Python does not enable ByteTrack in another running process.
If Windows' `py` launcher is unavailable, create the environment with the
actual installed Python executable, for example the one identified in
[the runtime baseline](docs/runtime_baseline.md). Restart the API using the
project interpreter and check the active tracker in Runtime Diagnostics.

---

## Configuration

Key environment variables:

For the operator workflow, performance terminology, measurement procedure and
remaining validation gates, see [the UI/FPS handoff](docs/ui_fps_handoff.md).

| Variable | Default | Description |
|----------|---------|-------------|
| FISH_DETECTOR_MODEL_PATH | auto | Override Model 1 checkpoint path |
| FISH_QUALITY_MODEL_PATH | auto | Override Model 2 checkpoint path |
| FISH_DETECTION_CONFIDENCE | 0.5 | Model 1 confidence threshold |
| FISH_QUALITY_CONFIDENCE | 0.25 | Model 2 part evidence threshold |
| FISH_QUALITY_INTERVAL | 3 | Run Model 2 every N processed frames |
| FISH_QUALITY_INFERENCE_MODE | full_frame | Live whole-fish inspection always uses `full_frame` association. A stale `crop` request is safely promoted to `full_frame`; crop mode is retained only for isolated tooling/part-preview paths. |
| FISH_REQUIRE_BYTETRACK | 0 | Set to `1` to refuse startup if ByteTrack is unavailable |
| FISH_STRICT_MODEL_INTEGRITY | 0 | Set to `1` to require verified registry checkpoints for Model 1 and Model 2 |
| FISH_EVENT_PERSISTENCE_QUEUE_CAPACITY | 256 | Positive bounded FIFO capacity for durable fish-event writes. At capacity, the producer applies ordered backpressure rather than dropping or bypassing an older record; session close/reset/policy rotation flushes it first. |
| FISH_UPLOAD_MAX_BYTES | 10485760 | Maximum encoded image upload size in bytes |
| FISH_UPLOAD_MAX_DIMENSION | 4096 | Maximum image width or height in pixels |
| FISH_UPLOAD_MAX_PIXELS | 16777216 | Maximum decoded image pixel count |
| LEMURU_CAMERA_INDEX | 0 | OpenCV camera index |
| LEMURU_DECISION_DEADLINE_SECONDS | unset | Optional independently approved limit from first persistent Model 1 detection to the virtual count-line decision. It records `met`/`missed` telemetry only and never changes a fish count, class, or grade. |
| LEMURU_MODE | (runtime) | part_preview enables upload-test segmentation |
| FISH_RAW_PREVIEW_ENABLED | 0 | Set to 1 before startup to offer a separate raw camera preview. It has no AI overlays and is capped at 15 frames per second; Runtime Diagnostics reports this browser's observed MJPEG image-load rate, while browser paint/network latency remains unmeasured. The processed feed remains the default. |
| LEMURU_RUNTIME_DIAGNOSTICS | ? | Set to `true` for verbose inference logging |

Grading policy: [configs/grading_engine.yaml](configs/grading_engine.yaml)

Registered Model 2 checkpoints must match their registry SHA-256 before loading.
An unregistered YOLO `.pt` override is identified as custom and warned as
unverified; strict integrity mode rejects custom or unhashed checkpoints and
blocks inspection and whole-fish upload analysis unless both models match the
registry. Checkpoint fingerprints are calculated at load time and recorded in
session metadata, not recomputed for each frame.

Image uploads accept JPEG, PNG, and WebP. Their encoded stream is bounded while
reading, and image dimensions are checked before pixel decoding. Oversized
encoded bodies return HTTP 413; invalid formats and dimensions return HTTP 400.

Model 1 uses ByteTrack when its `lap` assignment dependency is available.
Otherwise, the application uses an IoU tracker and displays a warning; the
actual backend is recorded with the inspection session. The fallback can behave
differently during overlap and has not been validated as equivalent to ByteTrack.
To require ByteTrack, install the optional dependency and start the application
with `FISH_REQUIRE_BYTETRACK=1`; if initialization fails, inspection will not
start. For example, in PowerShell:

```powershell
py -m pip install --only-binary=:all: -r requirements-bytetrack.txt
$env:FISH_REQUIRE_BYTETRACK = '1'
```

The [lap 0.5.13 package](https://pypi.org/project/lap/0.5.13/) lists wheels for
supported Python versions on Windows x86-64, Linux x86-64/ARM64, and macOS
x86-64/ARM64; Windows ARM64 is marked experimental. Choose a wheel matching the
actual Python and platform, and check the resulting runtime status. Installing
the package or running a benchmark is not performed automatically.

---

## Running tests

```powershell
# Model-free test suite (no camera, GPU, or checkpoint required)
py -m pytest tests/ `
  --ignore=tests/test_camera_calibration.py `
  --ignore=tests/test_camera_calibration_ui.py `
  --ignore=tests/test_dataset_audit.py `
  -q

# Check the reported pass and skip counts; skips are not passes.
```

Tests requiring a camera or a real checkpoint are opt-in smoke tests that
skip cleanly unless their required assets and environment variables are present.

See [tests/README.md](tests/README.md) for a full description.

---

## Grading policy

The weighted grading engine is fully documented in
[src/inference/grading_engine.py](src/inference/grading_engine.py) and
[src/inference/grading_policy.py](src/inference/grading_policy.py).

### Adaptive Part-Weighted Fish Grading with Optional Tail Evaluation

The full design, assumptions and independent evaluation plan are documented in [adaptive_tail_policy.md](docs/adaptive_tail_policy.md).

The configured `tail_optional_v1` policy is a proposed design for cases where
the tail cannot be reliably evaluated. It has not been validated against an
independent expert-labeled study and is not evidence of improved accuracy.

Key rules:
- **Body and Head evidence are required.** Without either, the fish stays Ungraded.
- **Tail evaluated:** use the original Body 50%, Head 30%, Tail 20% weights.
- **Tail unavailable:** redistribute its weight proportionally: Body 62.5%,
  Head 37.5%, Tail 0%. This does not establish physical absence or an intact tail.
  A reliable Tail prediction, including a trained Rejected-class prediction,
  remains in the calculation; it is not discarded as a missing tail.
- **Minimum coverage gate.** The sum of original weights for observed regions must
  meet minimum_original_weight_coverage (default 50 %).
- **Temporal aggregation.** A live verdict requires `minimum_valid_frames`
  (default 2) distinct, quality-usable observations that each meet the active
  Body/Head, region-count, and coverage gates. Evidence expires as the configured
  candidate-frame window advances. Uncertain ownership clears active evidence;
  subsequent qualifying frames can recover, with warning counts retained.
  Callers should provide a unique frame ID; when none is supplied the engine
  cannot detect repeated source frames. Still-image analysis does not use the
  live temporal gate.
- **Ungraded ≠ Rejected.** Use UG_* reason codes for low evidence;
  RJ_GRADE_EVIDENCE for trained Rejected-class evidence.

Each result records `weighting_method`, `tail_status`, `weights_used` and the
original coverage. `below_threshold` means a low-confidence Tail detection was
received by the grading engine; detections filtered earlier are indistinguishable
from no detection. Ungraded records with incomplete mandatory evidence retain
partial support for review but do not claim a complete 100% weighting.

Set `grading.grading_mode` to `standard` to reproduce the previous fixed-weight
baseline. The separate `two_part_v1` candidate requires Body and either Head or
Tail, retains fixed original weights and remains a research option; it is not
an approved structural integrity rule. `strict` continues to require all parts.
Historical session snapshots should be replayed with their recorded policy.

| Example Class A evidence | Previous standard support | Tail-optional support |
|---|---:|---:|
| Body .87, Head .79, Tail unobserved | .672 | .840 |
| Body .87, Tail .79, Head unobserved | .593 (subject to gates) | Ungraded: Head required |

Structural review is separate from Model 2's trained `Rejected_*` grade labels.
For a counted fish in the current session, `GET /api/reviews/{track_id}/structure`
returns Head and Tail states, reason codes, and the retained claim history.
`POST` to the same path appends one observation, for example:

```json
{"region":"Head","state":"confirmed_absent","source":"expert_review","reviewer":"reviewer-id","provenance":"reviewed specimen or image reference","confidence":0.95}
```

States are `present`, `confirmed_absent`, and `unknown_or_occluded`; supported
manual sources are `expert_review` and `unverified`. An expert claim requires a
reviewer and provenance; a timezone-bearing observation timestamp is recorded
if omitted. Reported reviewer identity is not authenticated by this local API.
Contradictory claims remain visible and resolve to unknown pending review.
These observations do not change AI or manual grades. No automatic physical
head-loss rejection rule is active or approved; the missing-tail grade limit
and the head-loss criterion remain to be confirmed with the annotator.

The dashboard's **Supporting Image Measurements** and the corresponding
export field report optional rectangular-ROI color and brightness proxies with
fish, frame, source and algorithm provenance. They are not used for the final
grade and may include background. Set `grading.image_diagnostics_enabled` to
`false` to skip their calculation. Masked texture is unavailable in the live
pipeline because the deployed detectors do not provide a validated fish mask.

---

## Repository structure

```text
configs/                 Runtime YAML configuration
  grading_engine.yaml    Grading policy (version-tracked)
  camera_settings.yaml   Camera calibration profile (gitignored)

frontend/                Dashboard HTML + JS (served by FastAPI)

models/
  fish_detector/         Model 1 checkpoint
  fish_quality/          Alternative Model 2 checkpoint
  yolov26/               Registry-default YOLO26m part detector
  yolo_parts/            Part-preview segmentation checkpoint
  MODEL_REGISTRY.json    Checkpoint SHA-256 hashes and provenance

src/
  api/                   FastAPI application + domain state
  evaluation/            Evaluation scripts (model-free)
  features/              HSV color measurement (descriptive only)
  inference/             Model adapters + grading engine
  preprocessing/         Dataset utilities + audit
  training/              Training scripts
    legacy/              Archived Colab workbench (not importable locally)

tests/                   Model-free automated test suite
```

---

## Thesis reproducibility

To reproduce a grading session:

1. Record the model SHA-256 hashes from MODEL_REGISTRY.json.
2. Record configs/grading_engine.yaml (version-tracked by config_version).
3. Export inspection history via the dashboard (CSV or XLSX).

History requests are paginated in the database. Date ranges use the calendar date
recorded in each event's timestamp, including its original timezone offset.
Dashboard totals and averages include every matching event, while each trend is
limited to its latest 500 observations; the throughput caption identifies this
limit. Current-session summaries are cached and updated for chronological new
events and review-only changes. A changed older event, an out-of-order insertion,
or several updates to the same fish between reads requires a fresh streamed
summary; large sessions can therefore take longer on the first request after
such a change. Exports still include the full selection.

To review a past fish, choose its session in Inspection History, open the fish,
and record or clear its manual grade. The selector lists the 1,000 most recent
sessions; older session IDs can be supplied through the API. The review request
accepts `session_id`, `manual_grade` (or `null` to clear), and an optional
`reviewer`. If `session_id` is omitted, it uses the current session for older
clients. Reviewer names are self-reported; the application does not authenticate
them. Each durable review or clearing is recorded in the session/fish audit log,
available at `/api/sessions/{session_id}/reviews/{track_id}/audit`. The original
AI grade and evidence remain separate from manual grades. Dashboard grade
distribution is an AI prediction count, not a measured accuracy statistic.

### Optional protected LAN access

The default `python -m src.api` binds to `127.0.0.1` and uses the ordinary local
interface. Remote API requests are rejected when LAN authentication is off.
For a direct LAN bind, set `FISH_LAN_AUTH=1`, `LEMURU_HOST=0.0.0.0`, and
`FISH_LAN_OPERATOR_TOKEN` to a randomly generated, secret token of at least 32
non-whitespace ASCII characters. Set `LEMURU_TLS_CERTFILE` and
`LEMURU_TLS_KEYFILE` to existing PEM files for a certificate trusted by the
clients; the launcher refuses a non-loopback bind without authentication and
TLS and logs a warning. Generate role tokens independently, for example with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`; share them
through a secure channel and never commit them. Optionally configure distinct
`FISH_LAN_VIEWER_TOKEN` and `FISH_LAN_ADMIN_TOKEN` values. All users must sign in
to read API data, including camera streams, history and exports. Viewers can
read and export; operators can also change controls and reviews; administrators
can access debug endpoints only when `FISH_LAN_DEBUG=1`. Debug details are
hidden from other roles. Browser sessions use Secure, HttpOnly, SameSite=Strict
cookies and same-origin CSRF tokens; API clients can use an HTTPS
`Authorization: Bearer <token>` header. A session expires after eight hours,
and token rotation or sign-out revokes it, including active camera streams.

If using a TLS reverse proxy, enable the same LAN profile and bind the app to
localhost; configure the trusted proxy to terminate HTTPS and overwrite forwarded
headers. Do not expose an unauthenticated localhost app through a proxy, because
the app cannot distinguish proxy users if the proxy hides their addresses. Run a
single application worker: sessions and login throttling are process-local.
These role tokens are shared credentials, not individual authenticated reviewer
identities. The independent expert library retains its separate localhost-only
security gate and is unavailable through the LAN token profile. Real network,
certificate-trust, firewall and proxy configurations must be verified in the
target deployment.
   - Export fields can include grading configuration, part weights, reason codes,
     detector thresholds and weighted scores, depending on the selected format.

---

## Limitations

- Model 2 was trained on a single controlled background; performance on different
  backgrounds or lighting has not been benchmarked.
- Temporal aggregation parameters have not been validated on a held-out test set.
- No HSV or defect rule is active in the default configuration.
- The system does not count or verify fish by weight.

## Research and validation status

The color, texture and fusion studies are offline scaffolds, not validated grade
inputs. Structural review records claims separately from grades; the belly-defect
detector and independent fish study await expert-reviewed data. The expert clip
library is disabled by default, and real clips require consent and approved access.

See [release readiness](docs/release_readiness.md), [feature inventory](docs/feature_inventory.md),
[independent validation protocol](docs/independent_validation_protocol.md), and
[research notes and architecture](docs/research_architecture.md).

Model selection through `POST /api/models/select` and `POST /api/settings` is
blocked while an inspection is starting, running, stopping, or its worker remains
alive. If a durable session is still open, stop the inspection to close it before
changing models. Software settings in a request are validated together, and a
failed update restores the previous settings. Camera controls report individual
readbacks and best-effort rollback results, since drivers may reject restoration;
change calibration mode separately from physical controls. Uploaded images always
use the active Model 2: an `X-Model-Id` matching
that model is accepted, while a different compatible model returns HTTP 409 and
an unsupported model returns HTTP 400. Select a different model explicitly
before uploading. Upload inference waits for the current live frame and does not
change the selected model or rotate the session; live processing pauses while the
upload uses the shared models, so preview frames may be dropped. Start, stop, and
model changes are serialized within one API process; avoid multiple API workers
for one camera.

Inspection exports use the checked columns in the order shown. Select **Export
all evidence columns** to include every evidence field. API clients must supply
a nonempty `fields` list or explicitly set `complete_analysis` to `true`.
Excel exports also contain separately named summary, review, and rules sheets.
The dashboard's **Specific inspection run** choice lists the 1,000 most recent
durable runs and exports the selected run by its `session_id`; **Current
session** remains the default for the active/latest run.
Exports spanning multiple sessions require Excel, which includes each session's
recorded policy and a mapping from inspection rows to sessions. Missing historical
configuration is marked unavailable.
To keep operator-entered text from being interpreted as a spreadsheet formula,
CSV values with formula-like prefixes receive a leading apostrophe. Excel exports
store formula-like text as literal strings; saved inspection records are unchanged.
