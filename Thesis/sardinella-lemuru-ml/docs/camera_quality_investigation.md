# Inspection camera quality investigation

Date: 2026-10-31. The software could disable automatic camera adjustments and
restore stale manual values. Those defects are corrected. Physical probes still
returned very dark images, and the user confirmed Windows Camera remained bright
while the inspection system was dark. The fix is not evidence of parity. The
investigation continues with an isolated OpenCV version comparison and a
comparison using the same camera, lighting, and framing.

## Confirmed software defects and history

`CameraHardwareController._probe_capabilities()` previously wrote every current
property value to test support. Writing the current exposure, white balance, or
focus is not a harmless read: it can select a manual mode. The controller then
recorded its reset snapshot after these writes. Discovery now uses getters only.

The checked-in profile introduced in `b6f4664` contained exposure `-5`, gain `0`,
brightness `0`, and both automatic modes recorded as false. `7cfdc4d` changed the
profile to exposure `-4`, brightness `50`, and reported FPS `120.0005`; both
automatic flags remained false. Startup replayed these values. These are saved
readings from a particular device/session, not portable webcam defaults. The
Camera settings trigger was removed in `85ad949`, while startup profile replay
remained active. No removed brightness, gamma, CLAHE, or white-balance image
enhancement was found in the camera/inference history.

The automatic exposure implementation also confused backend conventions and
interpreted an unavailable DirectShow getter (`-1`) as false. A false saved state
therefore did not prove automatic exposure had been off on the device before the
application touched it. DirectShow automatic exposure requests now use `1`/`0`;
an accepted write without a getter is reported separately from a verified state.
The [OpenCV DirectShow implementation](https://raw.githubusercontent.com/opencv/opencv/4.11.0/modules/videoio/src/cap_dshow.cpp)
shows the exposure setter, unavailable getter fallback, and manual-property
writes. Autofocus readback uses the automatic bit rather than treating every
positive flag as enabled, matching Microsoft's
[CameraControlFlags definitions](https://learn.microsoft.com/en-us/windows/win32/api/strmif/ne-strmif-cameracontrolflags).

## Implemented acquisition policy

- Startup requests automatic exposure and automatic white balance where exposed.
  The repository profile no longer pins manual exposure/gain, brightness, gamma,
  resolution, or FPS.
- Legacy unlocked, unconfirmed profiles are not replayed at startup. Matching
  profiles with control schema version 2, a lock, or explicit operator
  confirmation retain their acquisition policy. Profiles for another camera
  index are not applied.
- Manual exposure/gain, white balance, or focus observations are skipped when
  their corresponding automatic mode is requested. Automatic flags are applied
  after numeric settings, independently of request order.
- White-balance temperature discovery checks backend/version aliases without
  writing them. Gamma, pixel format/FourCC, color conversion, startup policy,
  and automatic requests are exposed in diagnostics. Unknown automatic state is
  displayed as unknown instead of off. The available property identifiers are
  described in [OpenCV's video I/O reference](https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html).

Capture still has one owner and a bounded latest-frame queue. The changes add no
per-frame brightness correction, gamma filter, white-balance filter, or color
conversion. YOLO receives BGR NumPy frames; adapters requiring RGB convert at
their existing model boundary. JPEG encoding receives BGR directly, and the
frontend applies no image color filter. No forced pixel-format or backend switch
was justified by the observed results.

## Physical observations and limits

The enumerated devices were HP True Vision (`0`), Logitech C270 (`1`), and OBS
Virtual Camera (`2`). Both physical cameras reported native automatic controls
already enabled during the later probes. DirectShow frames remained dark after
automatic requests and with driver defaults; changing between MJPG and YUY2 did
not resolve the darkness. Approximate samples were:

| Device | Observed capture | Mean grayscale, 0-255 | Other reported driver values |
| --- | --- | --- | --- |
| HP True Vision | About 1 FPS | About 0.1 | Default brightness 0; gamma 300 |
| Logitech C270 | About 15 FPS | About 4-6 | Default brightness 128; exposure -4, gain 101, white balance 2600 |

These samples are diagnostic observations, not recommended camera settings or a
controlled performance benchmark. Media Foundation produced no usable frames
for index `0`; opening index `1` hung during the probe. The application therefore
keeps its existing backend fallback policy. The Windows Camera capture
configuration and any additional driver/ISP processing have not been directly
measured. The remaining physical darkness cannot yet be attributed solely to
the fixed software defects.

The installed OpenCV package was `5.0.0.93`, outside the repository's declared
`opencv-python<5` requirement. An isolated `4.14.0.94` comparison was prepared
without replacing the project environment; its physical result is pending while
the camera is released by Windows Camera. This is a compatibility finding, not
yet a demonstrated explanation for the darkness.

Windows capture paths can also apply different controls. Microsoft's
[camera settings documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/camera-settings-page)
describes persisted defaults and how application writes can override current
values. Its [video capture controls documentation](https://learn.microsoft.com/en-us/windows/apps/develop/camera/capture-device-controls-for-video-capture)
describes optional HDR, denoising, and exposure priority, which can trade capture
FPS for longer exposure. These are possible differences to measure; their use by
Windows Camera on either device has not been established.

## Completing validation

Restart the backend with `LEMURU_CAMERA_INDEX=0` for HP or `1` for Logitech; see
[camera startup instructions](../camera/README.md). Compare Windows Camera and
the inspection feed sequentially with the same physical device, resolution,
lighting, and target, allowing automatic controls to settle. Record actual
control readbacks and distinguish unavailable getters from rejected requests.
Check neutral colors and a representative fish, not only overall brightness.

After image quality is comparable, use the existing
[runtime baseline procedure](runtime_baseline.md) with unchanged model
checkpoints and grading settings for empty, one-fish, and overlapping-fish
scenarios. Check labelled detection/grade outcomes as well as capture FPS,
processed FPS, and latency. No improvement or preservation of physical AI
accuracy/FPS is claimed until that comparison is complete.
