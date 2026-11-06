# Live camera exposure

Open **Camera controls** beside the live camera view. Choose **Manual EV** and
move the slider from **-2.0 to +2.0 EV**. The value applies to the running camera
view without reopening the device. **Auto Exposure** removes the preview offset;
in unlocked Calibration Mode it also requests native automatic exposure when
the driver supports it. **Reset to Default** removes the offset and restores
the exposure state captured before the first native EV adjustment in the current
calibration session. This is a session default, not a camera factory reset.

During ordinary inspection, software EV changes only the normal live preview.
Detection, segmentation, color measurements, grading, saved analysis evidence,
and the optional diagnostic raw preview continue to receive original camera
frames. Upload analysis is unaffected. Software changes do not reset fish IDs,
counts, or recording sessions.

Native adjustment follows the existing physical camera safeguard: enable
**Calibration Mode** and unlock the camera first. Calibration frames are not
recorded as inspection events. Native exposure is attempted only for backends
with a known exposure unit and verified control writes; other cameras use the
software preview adjustment. Changing a physical setting ends existing active
evidence through the existing acquisition-policy boundary. After a native EV
adjustment, leaving Calibration Mode keeps the selected physical setting as the
new acquisition baseline and returns the preview offset to zero. Saving a camera
profile uses the existing profile controls; preview EV itself is not persisted.

The preview adjustment uses a smooth tone curve on HSV value while retaining
hue and saturation. Shadow/midtone gain, gamma and contrast compensation
are bounded, with a highlight shoulder to limit clipping. EV changes settle
gradually in the preview worker. No software filter can recover detail in an
already black or clipped camera frame.

Hardware behavior, image quality and capture FPS still depend on the camera,
driver, lighting and shutter limits. Model-free tests cover fallback, native
readback/rollback, preview isolation, request validation and UI updates. Physical
EMEET parity and real camera FPS require a comparison using the same camera,
lighting and target; these are not established by synthetic tests.

## Implementation checks

Native EV currently uses DirectShow's integer log2 shutter units, as documented
by [Microsoft](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/ksproperty-cameracontrol-exposure).
Unknown backend units use software. Positive native shutter changes require a
readable FPS and cannot lengthen exposure beyond the reported frame interval.
Fractional EV is handled in the preview. Failed native writes restore the prior
exposure and automatic mode before falling back; a failed restoration is
reported explicitly with the acquisition change.

A local synthetic benchmark of 100 warmed-up frames measured preview-filter
p50/p95 of **2.679/3.322 ms at 1280x720** and **4.563/5.296 ms at 1920x1080**.
These are filter timings, not physical camera or end-to-end FPS measurements.
Runtime diagnostics report this work separately as `exposure_preview`.

The isolated model-free runner copies the source, UI, launcher and dependency
manifests to a temporary directory without checkpoints or inspection databases.
Run `python -B tests/run_model_free_isolated.py` from the project directory.

Validation on November 4, 2026: **1,874 passed, 12 skipped**, with 127 passing
subtests. JavaScript syntax and `git diff --check` also passed. The skips include
checks requiring checkpoints or external fixtures; no physical camera was opened.
