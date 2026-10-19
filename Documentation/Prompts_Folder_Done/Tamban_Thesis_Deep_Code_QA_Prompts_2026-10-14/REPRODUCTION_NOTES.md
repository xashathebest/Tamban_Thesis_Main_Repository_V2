# Reproduction notes (model-free, 14 October 2026)

The audit checked code from the ZIP's `Thesis-main/` directory, without changing the original source files. Results were obtained using fake HTTP request objects, method mocks, a temporary SQLite database, a controlled worker interleaving and a synthetic registry checkpoint.

## Commands

```bash
cd Thesis-main
python -m unittest discover -s tests -q
python -m compileall -q src tests
node --check frontend/app.js
```

Model-free run: 341 tests, 330 pass, 6 fail (all `test_multi_model_selection.py` missing checkpoints), 5 skipped. The available unit tests cannot establish actual device FPS, model accuracy or camera behavior.

## Exact model-free observed outcomes

```text
PARTIAL_SETTINGS: HTTP 422 detection_threshold_changed True
UPLOAD_SWITCH_ON_INVALID_IMAGE: HTTP 400 switch_called True
MODEL_SWITCH_WHILE_RUNNING: endpoint_success True switch_called True
SESSION_START_RACE: start_response True new_session_differs True event_in_prior_session True event_in_new_session 0
STOP_TIMEOUT: reported_stopped True worker_alive True state running
REGISTRY_CHECKSUM_MISMATCH_NOT_BLOCKED_BY_PATH_RESOLUTION: True
CHECKSUM_VERIFIER_AVAILABLE_AND_DETECTS_MISMATCH: True
```

The session-start experiment forces the interleaving where an event appears before new session creation; the actual incidence depends on camera/start scheduling. The stop experiment uses a worker whose join intentionally times out. The hash experiment creates dummy bytes inside a temporary fake registry layout; real missing checkpoints were neither claimed to be corrupt nor loaded.

## How to verify a fix

Each numbered prompt requests a new regression test. The expected outcome is that the triggering request returns an appropriate error or succeeds atomically, and neither global model state nor the wrong durable session changes. Preserve independent progress logs or CI results in the thesis repository.
