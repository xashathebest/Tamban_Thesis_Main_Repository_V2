# Camera integration

The canonical camera implementation is `src/api/camera.py`; it is the sole owner
of the OpenCV capture handle. It runs Model 1 whole-fish detection/tracking, then
the Model 2 Head/Body/Tail evidence pipeline, and publishes the raw camera image
as MJPEG. Inference continues on the same captured frames. The browser never
opens the camera directly.

`GET /api/camera/settings` reports the active backend, resolution, FPS, pixel
format, color conversion, and camera control readbacks. Discovery performs no
camera writes. A readable property is a candidate control; write support is
checked when a change is requested. During explicit Calibration Mode, controls
such as exposure, gain, brightness, gamma, white balance, focus, resolution, and
FPS can be requested through `POST /api/camera/settings`. Driver acceptance and
readback verification are reported separately. An unavailable readback remains
unknown: notably, some DirectShow versions accept automatic exposure writes but
cannot report its state. Unsupported controls never crash inspection.

Inspection policy and acquisition changes clear active track evidence and create a
new durable configuration/session snapshot. The repository does not assume a
specific EMEET/UVC property range or device name, because OpenCV does not expose
those reliably across Windows camera backends.

## Automatic adjustments and camera selection

The repository profile requests automatic exposure and automatic white balance
where supported. It does not pin exposure, gain, brightness, gamma, resolution,
or FPS. Legacy unlocked, unconfirmed profiles use these automatic defaults;
profiles saved with control schema version 2, locked profiles, and explicitly
confirmed profiles retain their settings for the matching camera index. A
different index receives automatic defaults instead of another camera's values.
When an automatic mode is enabled, its measured numeric exposure/gain or white
balance values are observations and are not replayed as manual settings.

Choose the camera before starting the backend, then restart it after a change.
In the currently observed Windows device order, index `0` is HP True Vision,
index `1` is Logitech C270, and index `2` is OBS Virtual Camera. Device order can
change after reconnection. From the project directory in PowerShell:

```powershell
$env:LEMURU_CAMERA_INDEX = '0' # Use '1' for the Logitech C270.
.\run_dashboard.ps1
```

Compare the selected physical camera with Windows Camera under the same
lighting and framing, closing one application before opening the other. Allow
automatic exposure and white balance to settle. The application does not add
brightness, gamma, saturation, or white-balance filters to the image. YOLO and
JPEG encoding continue to receive OpenCV BGR frames without extra conversions.
See [the camera quality investigation](../docs/camera_quality_investigation.md)
for the confirmed software defects, hardware observations, and remaining
validation limits. Windows Camera parity and AI accuracy/FPS parity have not yet
been established on the physical setup.

## Formal research calibration

A saved profile is not automatically a calibrated profile. For an independent
study, an operator must explicitly complete this sequence while the camera is
running, unlocked, and in Calibration Mode:

1. Record the physical device identity, camera height/angle, conveyor position,
   and lighting position.
2. Adjust only controls the active driver exposes; the profile stores both actual
   hardware readbacks and unsupported properties.
3. Record an `empty_conveyor` reference through `POST /api/camera/reference`.
   A `representative_fish` reference is optional. Reference statistics include
   brightness mean/median/standard deviation, fish/background contrast when a
   fish is present, and informational HSV means. They never affect a grade.
4. Save the profile, then call `POST /api/camera/profile/confirm` with
   `operator_confirmed: true` and the recorded installation metadata.
5. Lock the inspection camera with `POST /api/camera/lock`.

Profile confirmation requires an empty-conveyor reference and all physical setup
fields. A locked profile reports camera disconnection, backend/resolution/control
drift, and reference-brightness warnings; it never silently alters hardware or
grades to compensate. A formal validation session must treat such warnings as
acquisition evidence and either document or restart the study.

Saving changed hardware/acquisition evidence or replacing a reference scene clears
the prior operator confirmation, requiring a fresh explicit confirmation. Lock and
unlock transitions alone preserve an otherwise unchanged confirmation; neither
operation adjusts the camera or the grading policy.
