"""Real Chrome UI checks with candidate fixtures; no model or GPU inference.

Run with the project root on PYTHONPATH. The API runs on an ephemeral loopback
port with lifespan disabled. Candidate fixtures validate rendering behavior,
never segmentation accuracy. Output artifacts go to results/qa/mobilesam.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np
from websockets.sync.client import connect

from dashboard_status_smoke import free_port, wait_json


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    image = np.full((350, 500, 3), (35, 45, 50), np.uint8)
    cv2.ellipse(image, (180, 105), (135, 28), 0, 0, 360, (105, 160, 190), -1)
    cv2.ellipse(image, (300, 235), (145, 30), 0, 0, 360, (135, 160, 170), -1)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    preview = 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode()
    events = []
    for identity, y, frame in [(7, 150, 'video-frame-2'), (8, 410, 'video-frame-3')]:
        box = [80, y, 650, y + 125]
        part = {'bbox': [180, y + 15, 440, y + 100], 'region': 'Body',
                'grade': 'Class B', 'coordinate_space': 'original_frame'}
        event = {'id': identity, 'track_id': identity, 'quality': 'Class B',
                 'quality_confidence': .8, 'bbox': [0, 0, 20, 20],
                 'parts': [{'bbox': [1, 1, 2, 2], 'region': 'Head', 'grade': 'Class B'}],
                 'analysis': {'final_grade': 'Class B', 'final_score': .8,
                    'weighted_scores': {'Class A': 0, 'Class B': .8, 'Class C': 0, 'Rejected': 0},
                    'body_width': {'threshold_configuration': {'calibrated': False},
                                   'score_status': 'Not calibrated'},
                    'fish_geometry': {'status': 'unreliable', 'measurement_validated': False,
                        'used_for_grading': False,
                        'sampling': {'mode': 'mobilesam_candidate', 'estimated': True,
                            'native_shape': [700, 1000], 'native_output_shape': [125, 570],
                            'native_boundary_validated': False},
                        'candidate_measurements': {'fish_length_px': 280., 'max_body_width_px': 60.,
                            'relative_width_ratio': .2143}},
                    'geometric_support': {'original_grade': 'Class B', 'final_grade': 'Class B',
                                          'applied_score_shift': 0, 'width_changed_classification': False},
                    'inspection_source': {'frame_id': 'best-grade-frame-9'},
                    'segmentation': {'backend': 'mobilesam_experimental', 'experimental': True,
                        'status': 'candidate', 'ownership_status': 'ambiguous',
                        'parent_track_id': identity, 'frame_id': frame,
                        'used_for_grading': False, 'validation_status': 'Not validated',
                        'mask_score_unvalidated': .99,
                        'checkpoint_sha256': 'fixture-not-a-model-checkpoint',
                        'reasons': ['Candidate fixture; ownership is not independently validated'],
                        'source_parent_bbox': box, 'source_parts': [part],
                        'timings': {'embedding_ms': 12.3, 'prompt_ms': 4.5},
                        'mask_overlay': {'coordinate_space': 'original_frame', 'frame_id': frame,
                            'frame_width_px': 1000, 'frame_height_px': 700,
                            'contours': [[[90, y + 20], [640, y + 20], [640, y + 100], [90, y + 100]]],
                            'source_preview_image': preview}}}}
        events.append(event)
    return {'fish': events, 'annotated_image': preview, 'analyzed_at': '2026-11-02T12:00:00Z'}


EXERCISE = r'''(async () => {
  const sample = window.__samFixture;
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const checks = {defaultOff: !elements.segmentationExperiment.checked,
                  advancedCollapsed: !elements.segmentationOptions.open};
  const originalFetch = window.fetch;
  const requests = []; const headers = [];
  window.__samRequestHeaders=headers;
  window.fetch = async (url, options = {}) => {
    const path = String(url); requests.push(path);
    if (path === '/api/status/live') {
      const response = await originalFetch(url, options); const payload = await response.json();
      return new Response(JSON.stringify({...payload,upload_analysis_available:true}), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (path === '/api/analyze-image' || path === '/api/analyze-video') {
      headers.push({path, ...(options.headers || {})});
      await delay(375);
      return new Response(JSON.stringify(path.endsWith('video') ? {job_id:'fixture-job'} : sample), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (path === '/api/analyze-video/fixture-job') return new Response(JSON.stringify({status:'complete',result:{...sample,annotated_frames:[sample.annotated_image]}}), {status:200,headers:{'Content-Type':'application/json'}});
    return originalFetch(url, options);
  };
  toggleUpload(true);
  elements.segmentationOptions.open = true; await delay(150);
  checks.lazyCapabilityRead = requests.filter(path => path === '/api/segmentation/status').length === 1;
  checks.capabilityWording = /Candidates remain unvalidated/.test(elements.segmentationNote.textContent);
  const bytes = Uint8Array.from(atob(sample.annotated_image.split(',')[1]), letter => letter.charCodeAt(0));
  const photo = new File([bytes], 'candidate-fixture.jpg', {type:'image/jpeg'});
  latestStatus = {...latestStatus, upload_analysis_available:true};
  setUploadSelection(photo); updateUploadControls(); elements.analyze.click();
  for (let tries=0;tries<200 && uploadInFlight;tries++) await delay(25);
  checks.defaultHeaderAbsent = !Object.hasOwn(headers[0] || {}, 'X-Segmentation-Backend');
  const reportedSeconds = Number(elements.uploadStatus.textContent.match(/completed in ([\d.]+)s/)?.[1]);
  checks.realElapsedSeconds = reportedSeconds >= .3 && reportedSeconds < 10;
  checks.resultsOwnCards = resultDatasets.upload.rows.length === 2;
  latestStatus = {...latestStatus,upload_analysis_available:true};
  elements.segmentationExperiment.checked = true; updateUploadControls(); elements.analyze.click();
  await delay(90);
  checks.runningTimer = /\d+\.\d+s/.test(elements.uploadStatus.textContent) && uploadInFlight && elements.segmentationExperiment.disabled;
  for (let tries=0;tries<200 && uploadInFlight;tries++) await delay(25);
  checks.explicitPhotoHeader = headers[1]?.['X-Segmentation-Backend'] === 'mobilesam_experimental';
  checks.unvalidatedCompletion = /ownership review|unvalidated/.test(elements.uploadStatus.textContent);
  const fish = resultDatasets.upload.rows;
  const group=elements.resultsGroups.querySelector('[data-grade="Class B"]');
  group.open=true; await delay(35);
  const card=group.querySelector('.result-fish-card');card.open=true;await delay(35);
  const widthSection=card.querySelectorAll('.result-evidence-section')[1];widthSection.open=true;await delay(35);
  checks.estimatedGeometryVisible=['Estimated fish length (px; experimental SAM)','Estimated maximum body width (px; experimental SAM)','280','60','0.2143','fish ownership'].every(value=>widthSection.textContent.includes(value));
  checks.experimentalCmWithheld=!widthSection.textContent.includes('Physical length (cm)') && widthSection.textContent.includes('Not validated for anatomical measurement');
  elements.fishZoomMask.checked = true;
  await openFishZoom('upload', fish, fish[0]);
  checks.snapshotCoordinates = fishZoom.frameId === 'video-frame-2' && fishZoom.nativeWidth === 1000 && fishZoom.nativeHeight === 700 && fishZoom.image.naturalWidth === 500;
  checks.snapshotParts = JSON.stringify(fishZoom.detection.parts) === JSON.stringify(fish[0].analysis.segmentation.source_parts) && fishZoom.detection.bbox[0] === 80;
  checks.noValidationClaim = elements.fishZoomDetails.textContent.includes('not independently validated');
  checks.bothChoices = elements.fishZoomChoices.querySelectorAll('button').length === 2;
  const trace = [];
  const context = {beginPath(){},moveTo(x,y){trace.push(['move',x,y]);},lineTo(x,y){trace.push(['line',x,y]);},
    closePath(){},fill(){trace.push(['fill']);},stroke(){},strokeRect(...box){trace.push(['box',...box]);},setLineDash(){}};
  drawFishZoomOverlay(context,fishZoom.detection,[0,0,1000,700],1000,700);
  checks.selectedOnly = JSON.stringify(trace.filter(item => item[0] === 'move')) === JSON.stringify([['move',90,170]]) && trace.filter(item=>item[0]==='box').length === 2;
  const mismatched = structuredClone(fishZoom.detection); mismatched.analysis.segmentation.parent_track_id = 99; trace.length = 0;
  drawFishZoomOverlay(context,mismatched,[0,0,1000,700],1000,700);
  checks.mismatchedParentWithheld = !trace.some(item => ['move','fill','box'].includes(item[0]));
  const wrongFrame = structuredClone(fishZoom.detection); wrongFrame.analysis.segmentation.mask_overlay.frame_id = 'wrong-frame'; trace.length=0;
  drawFishZoomOverlay(context,wrongFrame,[0,0,1000,700],1000,700);
  checks.mismatchedFrameWithheld = !trace.some(item => ['move','fill','box'].includes(item[0]));
  await openFishZoom('upload',fish,fish[1]);
  checks.nextFishOwnFrame = fishZoom.frameId === 'video-frame-3' && fishZoom.detection.id === 8 && fishZoom.detection.bbox[1] === 410;
  await openFishZoom('upload',fish,fish[0]);
  window.__samScreenshotReady = true;
  return {checks,reportedSeconds,headers,requests,syntheticFixture:true,modelInference:false,gpuInference:false};
})()'''


RESET_AND_VIDEO = r'''(async () => {
  const delay = milliseconds => new Promise(resolve=>setTimeout(resolve,milliseconds));
  const checks = {};
  setUploadSelection(new File(['fake-video'], 'fixture.mp4', {type:'video/mp4'}));
  checks.freshSelectionClears = fishZoom.image === null && fishZoom.detection === null && fishZoom.frameId === null && resultDatasets.upload.rows.length === 0 && elements.inspectMasks.disabled && !elements.segmentationExperiment.checked;
  latestStatus = {...latestStatus,upload_analysis_available:true};
  elements.segmentationExperiment.checked = true; updateUploadControls(); elements.analyze.click();
  for(let tries=0;tries<200 && uploadInFlight;tries++) await delay(25);
  checks.videoFinished = !uploadInFlight && resultDatasets.upload.rows.length === 2;
  checks.explicitVideoHeader = window.__samRequestHeaders.at(-1)?.path === '/api/analyze-video' && window.__samRequestHeaders.at(-1)?.['X-Segmentation-Backend'] === 'mobilesam_experimental';
  checks.videoCandidateDisclosed = /ownership review|unvalidated/.test(elements.uploadStatus.textContent);
  const fish = resultDatasets.upload.rows;
  await openFishZoom('upload',fish,fish[0]);
  checks.videoMatchingSnapshot = fishZoom.frameId === 'video-frame-2' && fishZoom.detection.bbox[0] === 80 && fishZoom.detection.parts[0].region === 'Body';
  closeFishZoom();
  checks.closeClears = fishZoom.image === null && fishZoom.frameId === null && fishZoom.detection === null;
  const imageLoader = fishZoomImage; let finish;
  fishZoomImage = () => new Promise(resolve=>{finish=resolve;});
  const pending = openFishZoom('upload',fish,fish[0]);
  clearUploadAnalysisState(); finish({naturalWidth:500,naturalHeight:350}); await pending;
  fishZoomImage=imageLoader;
  checks.lateImageCancelled = fishZoom.image === null && fishZoom.detection === null && fishZoom.frameId === null && resultDatasets.upload.rows.length===0;
  return checks;
})()'''


def main():
    chrome = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    if not chrome.is_file():
        raise RuntimeError('Chrome executable not found')
    output = ROOT / 'results/qa/mobilesam'
    output.mkdir(parents=True, exist_ok=True)
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix='tamban_sam_browser_') as tmp:
        env = dict(os.environ, FISH_INSPECTION_DB_PATH=str(Path(tmp) / 'history.sqlite3'),
                   YOLO_CONFIG_DIR=tmp, PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='')
        hidden = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        code = ("import importlib, uvicorn; m=importlib.import_module('src.api.app'); "
                f"uvicorn.run(m.app,host='127.0.0.1',port={api_port},lifespan='off')")
        server = subprocess.Popen([sys.executable, '-B', '-c', code], cwd=ROOT, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f'http://127.0.0.1:{api_port}/api/status/live', server)
            args = ['--headless=new', '--disable-gpu', '--no-first-run',
                    f'--user-data-dir={Path(tmp) / "chrome"}', f'--remote-debugging-port={cdp_port}',
                    '--remote-allow-origins=*', '--window-size=1440,1100']
            if os.getenv('TAMBAN_CHROME_NO_SANDBOX', '').lower() in {'1', 'true', 'yes', 'on'}:
                args.append('--no-sandbox')
            browser = subprocess.Popen([str(chrome), *args, f'http://127.0.0.1:{api_port}/'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(item for item in wait_json(f'http://127.0.0.1:{cdp_port}/json', browser) if item.get('type') == 'page')
            with connect(page['webSocketDebuggerUrl'], open_timeout=5, max_size=16 * 1024 * 1024) as ws:
                counter = 0

                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    ws.send(json.dumps({'id': counter, 'method': method, 'params': params or {}}))
                    while True:
                        response = json.loads(ws.recv(timeout=15))
                        if response.get('id') == counter:
                            if 'error' in response:
                                raise AssertionError(response['error'])
                            if 'exceptionDetails' in response['result']:
                                raise AssertionError(response['result']['exceptionDetails'])
                            return response['result']

                def evaluate(expression):
                    return call('Runtime.evaluate', {'expression': expression, 'returnByValue': True,
                                                     'awaitPromise': True})['result'].get('value')

                for _ in range(100):
                    if evaluate("typeof openFishZoom === 'function' && typeof latestStatus !== 'undefined' && latestStatus !== null"):
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('UI did not load')
                evaluate('window.__samFixture=' + json.dumps(fixture()) + ';true')
                result = evaluate(EXERCISE)
                assert all(result['checks'].values()), result
                screenshot = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
                (output / 'ui_candidate_fixture.png').write_bytes(base64.b64decode(screenshot['data']))
                result['reset_and_video_checks'] = evaluate(RESET_AND_VIDEO)
                assert all(result['reset_and_video_checks'].values()), result
                result['chrome_version'] = call('Browser.getVersion')['product']
                result['scope'] = 'Isolated real Chrome; synthetic candidate payloads; no model inference, no mask accuracy evaluation'
                (output / 'ui_browser_smoke.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
                print(json.dumps(result, indent=2))
        finally:
            for process in (browser, server):
                if process is not None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == '__main__':
    main()
