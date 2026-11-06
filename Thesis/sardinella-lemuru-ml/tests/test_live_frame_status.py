"""Operational frame health must not confuse camera acquisition with inference."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.api.live_frame_status import LiveFrameStatus


def test_frame_health_distinguishes_loading_capture_processing_and_stall():
    frames = LiveFrameStatus()
    assert frames.snapshot(active=True, connected=False, loading=True, now=1)["camera_state"] == "loading"
    for stamp in (1, 1.2, 1.4):
        frames.capture(640, 480, when=stamp)
    captured = frames.snapshot(active=True, connected=True, now=1.5)
    assert captured["camera_state"] == "active"
    assert captured["ai_state"] == "waiting"
    assert captured["capture_fps"] == 3
    assert captured["processing_fps"] == 0
    assert captured["capture_resolution"] == [640, 480]
    frames.processed(when=1.4)
    processed = frames.snapshot(active=True, connected=True, now=1.5)
    assert processed["ai_state"] == "running"
    assert processed["processing_fps"] == 1
    stalled = frames.snapshot(active=True, connected=True, now=6)
    assert stalled["camera_state"] == "stalled"
    assert stalled["ai_state"] == "waiting"
    assert stalled["capture_fps"] == stalled["processing_fps"] == 0


def test_pausing_stopping_and_restart_never_retain_ai_rate():
    frames = LiveFrameStatus()
    frames.capture(1920, 1080, when=1)
    frames.processed(when=1)
    paused = frames.snapshot(active=True, connected=True, paused=True, now=1.1)
    assert paused["camera_state"] == "active"
    assert paused["ai_state"] == "paused"
    assert paused["processing_fps"] == 0
    stopped = frames.snapshot(active=False, connected=False, now=1.2)
    assert stopped["camera_state"] == "disconnected"
    assert stopped["ai_state"] == "stopped"
    assert stopped["capture_fps"] == stopped["processing_fps"] == 0
    frames.reset()
    assert frames.snapshot(active=True, connected=False, loading=True, now=2)["capture_resolution"] is None


def test_service_reports_acquisition_without_claiming_inference_when_diagnostics_disabled(monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from src.api.camera import CameraInspectionService
    from src.api.domain import InspectionState

    monkeypatch.setenv("FISH_RUNTIME_TELEMETRY", "0")
    state = InspectionState()
    service = CameraInspectionService(state, SimpleNamespace())
    assert state.begin_start()
    monkeypatch.setattr(service.raw_preview, "offer", lambda *_: service._stop_event.set())
    capture = SimpleNamespace(read=lambda: (True, np.zeros((480, 640, 3), dtype=np.uint8)))
    service._capture_frames(capture)
    health = service.live_frame_status()
    assert health["camera_state"] == "active"
    assert health["capture_resolution"] == [640, 480]
    assert health["capture_fps"] == 1
    assert health["ai_state"] == "waiting"
    assert health["processing_fps"] == 0
    assert not service._runtime_metrics.enabled


def test_frontend_presentation_uses_backend_freshness_not_smoothed_or_browser_fps():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for camera presentation checks")
    root = Path(__file__).resolve().parents[1]
    script = r'''
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync('frontend/app.js','utf8');
const start=source.indexOf('function cameraPresentation('),end=source.indexOf('\nfunction renderCamera(',start);
vm.runInThisContext(source.slice(start,end));
const base={inspection_status:'running',camera_status:'connected',fps:999,frame_size:[1,1],
 live_frame_status:{camera_state:'active',ai_state:'running',capture_fps:30,processing_fps:4,capture_resolution:[640,480]}};
const running=cameraPresentation(base),paused=cameraPresentation({...base,live_frame_status:{...base.live_frame_status,ai_state:'paused'}}),
 stalled=cameraPresentation({...base,live_frame_status:{...base.live_frame_status,camera_state:'stalled'}}),
 stopped=cameraPresentation({...base,inspection_status:'stopped',camera_status:'disconnected',live_frame_status:{camera_state:'disconnected',ai_state:'stopped'}});
console.log(JSON.stringify({running,paused,stalled,stopped}));
'''
    output = subprocess.run([node, "-e", script], cwd=root, check=True, capture_output=True, text=True)
    states = json.loads(output.stdout)
    assert states["running"]["badge"] == "INSPECTING"
    assert states["running"]["aiFps"] == 4
    assert states["running"]["captureFps"] == 30
    assert states["running"]["resolution"] == [640, 480]
    assert states["paused"]["badge"] == "PREVIEW"
    assert states["paused"]["aiFps"] == 0
    assert states["stalled"]["badge"] == "CAMERA STALLED"
    assert states["stalled"]["aiFps"] == states["stalled"]["captureFps"] == 0
    assert states["stopped"]["badge"] == "STOPPED"
