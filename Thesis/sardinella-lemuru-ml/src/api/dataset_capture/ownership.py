"""Fail closed when exclusive device deployment has not been established.

Inspection deliberately remains unchanged and does not honor capture leases.
Neither a process-local mutex nor an environment flag proves OS exclusivity.
The administrator may enable hardware only inside a deployment that already
prevents inspection and other applications from accessing the chosen device.
"""
from .errors import CaptureError


ISOLATION_MESSAGE = (
    "Camera unavailable: physical device isolation has not been established. "
    "Camera Capture cannot reserve a webcam against unchanged Live Inspection. "
    "Stop inspection manually or choose a verified separate camera, and ask the "
    "administrator to establish exclusive device access before enabling capture."
)


def require_isolated_hardware(enabled: bool) -> None:
    if not enabled:
        raise CaptureError(409, "PHYSICAL_ISOLATION_REQUIRED", ISOLATION_MESSAGE)

