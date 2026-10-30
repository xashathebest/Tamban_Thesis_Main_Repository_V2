# Model-free test suite

The normal suite exercises the canonical local inspection system without a
webcam, GPU, network service, secret, or model checkpoint. It covers the shared
live/offline grading policy, original and adaptive anatomy weights, temporal aggregation,
tracking/counting invariants, camera-control readbacks, SQLite persistence, and
CSV/XLSX exports.

Install `requirements.txt` and `requirements-test.txt`, then run from the
project directory. The isolated command copies source and test fixtures into a
temporary directory, excludes checkpoint files, clears local runtime overrides,
and runs both pytest functions and unittest classes:

```powershell
python -B tests/run_model_free_isolated.py
```

To run against the current working copy instead, use `python -B -m pytest -q
tests`. `unittest discover` alone does not collect pytest-style functions. The
workflow at the Git repository root runs the isolated command on Python 3.11;
the nested workflow is a template for using this project as a standalone repo.
CI installs CPU PyTorch and does not need a GPU or model files.

For a separate real-checkpoint smoke test, first install the registered Model 1
and default Model 2 checkpoint files listed in `models/MODEL_REGISTRY.json`, with
matching SHA-256 hashes, and install the runtime/test requirements. Then invoke:

```powershell
$env:RUN_CHECKPOINT_SMOKE = "1"
python -B -m pytest -q tests/test_checkpoint_smoke.py
Remove-Item Env:RUN_CHECKPOINT_SMOKE
```

On Linux/macOS use `RUN_CHECKPOINT_SMOKE=1 python -B -m pytest -q
tests/test_checkpoint_smoke.py`. The smoke test loads both real checkpoints on
CPU and runs one synthetic black frame; it verifies loading and inference only,
not camera integration, accuracy, or FPS. The separate reference-image
regression in `test_real_model2_reference.py` also needs the documented dataset
image and must be explicitly enabled with `RUN_REAL_MODEL_TESTS=1`. Camera smoke
tests have their own `FISH_DETECTOR_SMOKE_IMAGE` and
`FISH_SEGMENTER_SMOKE_IMAGE` prerequisites.

`test_dataset_independence.py`, `test_camera_calibration.py`,
`test_camera_calibration_ui.py`, `test_validation_study.py`, and
`test_end_to_end_validation.py` also exercise the
research-only independent-study safeguards: lineage leakage, camera confirmation,
locked manifests, blind truth, retained Ungraded outcomes, and performance-label
gating. They do not run a checkpoint or certify a model.

## Browser smoke checks

The temporary browser checks exercise the real dashboard against a temporary
local API and SQLite database; they do not open a physical camera or modify the
normal inspection history. They require Chrome at the path used by the scripts.

```powershell
python -B tests\dashboard_status_smoke.py
python -B tests\export_form_smoke.py
python -B tests\historical_review_smoke.py
```

Some constrained Windows QA environments cannot launch headless Chrome with its
normal sandbox. Only in such an environment, opt in for the smoke process:

```powershell
$env:TAMBAN_CHROME_NO_SANDBOX = '1'
python -B tests\dashboard_status_smoke.py
Remove-Item Env:TAMBAN_CHROME_NO_SANDBOX
```

This flag is test-only and is not an application startup setting. The responsive
navigation smoke writes screenshots by default, so set
`TAMBAN_NAV_SMOKE_OUTPUT` to a temporary directory before running
`tests\navigation_qa_smoke.py`.
