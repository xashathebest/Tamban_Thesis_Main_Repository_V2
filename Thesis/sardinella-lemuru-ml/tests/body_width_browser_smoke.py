"""Exercise width cards and print-report contents with isolated headless Chrome."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import re
import sys
import tempfile
import time

from websockets.sync.client import connect

from dashboard_status_smoke import free_port, wait_json
from src.inference.body_width import analyze_body_width
from src.inference.part_types import PartDetection


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome executable not found")
    part = PartDetection.from_source_class(0, 0.9, (40, 15, 150, 55))
    width = analyze_body_width((10, 10, 210, 60), [part], detection_confidence=0.9, frame_shape=(200, 300))
    assert width["relative_width_proxy"] == 0.2
    event = {"track_id": 7, "id": 7, "quality": "Class A", "final_confidence": 0.9, "bbox": [10, 10, 210, 60],
             "parts": [part.to_dict()], "analysis": {"body_width": width, "final_grade": "Class A", "final_score": 0.8,
             "weighted_scores": {"Class A": 0.8, "Class B": 0.1, "Class C": 0.1, "Rejected": 0},
             "geometric_support": {"original_grade": "Class A", "original_support": 0.8, "width_changed_classification": False},
             "supporting_image_measurements": {"regions": {"Body": {"status": "measured", "values": {
                 "mean_hue_deg": 45, "mean_saturation": 0.2, "mean_value": 0.6, "yellow_ratio_proxy": 0.1,
                 "brown_ratio_proxy": 0.15, "dark_patch_ratio_proxy": 0.2, "discoloration_coverage_proxy": 0.25,
                 "specular_ratio_proxy": 0.3}}}}}}
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_width_smoke_") as tmp:
        env = dict(os.environ, FISH_INSPECTION_DB_PATH=str(Path(tmp) / "history.sqlite3"),
                   PYTHONDONTWRITEBYTECODE="1", YOLO_CONFIG_DIR=tmp)
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        code = ("import importlib, uvicorn; m=importlib.import_module('src.api.app'); "
                f"uvicorn.run(m.app, host='127.0.0.1', port={api_port}, lifespan='off')")
        server = subprocess.Popen([sys.executable, "-B", "-c", code], cwd=root, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f"http://127.0.0.1:{api_port}/api/status/live", server)
            chrome_args = ["--headless=new", "--disable-gpu", "--no-first-run",
                           f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                           "--remote-allow-origins=*"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes", "on"}:
                chrome_args.append("--no-sandbox")
            chrome_args.append(f"http://127.0.0.1:{api_port}/")
            browser = subprocess.Popen([str(chrome), *chrome_args], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(item for item in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if item.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                counter = 0

                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    ws.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(ws.recv(timeout=10))
                        if response.get("id") == counter:
                            if "error" in response:
                                raise AssertionError(response["error"])
                            if "exceptionDetails" in response["result"]:
                                raise AssertionError(response["result"]["exceptionDetails"])
                            return response["result"]

                def evaluate(expression):
                    return call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                      "awaitPromise": True})["result"].get("value")

                for _ in range(100):
                    if evaluate("typeof resultReportHtml === 'function' && typeof elements !== 'undefined'"):
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("Width UI did not load")
                evaluate(f"window.__widthSample = {json.dumps(event)}; true")
                result = evaluate("""(async () => {
                  const sample = window.__widthSample;
                  const delay = () => new Promise(resolve => setTimeout(resolve, 30));
                  const missing = {...sample, id: 8, track_id: 8, quality: 'Ungraded', parts: [], analysis: {final_grade: 'Ungraded', verdict_reason_text: 'Missing required Body evidence', body_width: {measurement_status: 'Missing Detection', calibration_status: 'Not Calibrated', relative_width_proxy: null}}};
                  renderResultsDashboard([sample], {source:'live', complete:true});
                  renderResultsDashboard([sample, sample, missing], {source:'upload', scope:'photo:smoke', complete:true, metadata:{source_name:'Reviewed fish photo'}});
                  elements.resultsSource.querySelector('option[value="upload"]').disabled = false;
                  selectResultsSource('upload'); toggleUpload(true); elements.uploadResults.classList.remove('hidden'); mountResultsDashboard(true);
                  const output = {deduplicated: resultsEvents.length === 2, oneWorkspace: document.querySelectorAll('#results-groups').length === 1,
                    lazyGroups: elements.resultsGroups.querySelectorAll('.result-fish-card').length === 0,
                    noExternalMeasurements: !document.querySelector('#upload-fish-measurements, #upload-fish-evidence'),
                    summaryCounts: elements.resultsCounts.textContent.includes('Total unique fish2') && elements.resultsCounts.textContent.includes('Graded fish1') && elements.resultsCounts.textContent.includes('Ungraded fish1')};
                  const group = elements.resultsGroups.querySelector('[data-grade="Class A"]'); group.open=true; await delay();
                  const card = group.querySelector('.result-fish-card'); output.collapsedCard = !card.open && !card.querySelector('table'); card.open=true; await delay();
                  output.fourLazySections = card.querySelectorAll('.result-evidence-section').length === 4 && !card.querySelector('table');
                  const widthSection = card.querySelectorAll('.result-evidence-section')[1]; widthSection.open=true; await delay();
                  output.width = ['200 x 50 px','110 x 40 px','0.2','Reliable proxy','Not calibrated','No:'].every(value => widthSection.textContent.includes(value));
                  const colorSection = card.querySelectorAll('.result-evidence-section')[2]; colorSection.open=true; await delay();
                  output.allMeasurements = ['Brown proxy','Dark-area proxy','Discoloration proxy','Highlight proxy','0.15','0.25','0.3','Not Detected'].every(value => colorSection.textContent.includes(value));
                  renderResultsDashboard([{...sample,track_id:99}], {source:'live'});
                  output.sourceIsolation = resultsSource === 'upload' && resultsEvents.length === 2 && !resultsEvents.some(event => event.track_id === 99);
                  const changed = {...sample, quality:'Class C',analysis:{...sample.analysis,final_grade:'Class C',final_score:0.54,geometric_support:{original_grade:'Class B',original_support:0.54,width_changed_classification:true,class_c_points:8,applied_score_shift:0.08}}};
                  renderResultsDashboard([changed,missing], {source:'upload',scope:'photo:smoke',complete:true});
                  output.regrouped = resultsEvents.length === 2 && !elements.resultsGroups.querySelector('[data-grade="Class A"]') && elements.resultsGroups.querySelector('[data-grade="Class C"]')?.textContent.includes('1');
                  const cleared = {...missing,id:7,track_id:7};
                  renderResultsDashboard([cleared,missing], {source:'upload',scope:'photo:smoke',complete:true});
                  const updated = resultsEvents.find(event => event.track_id === 7);
                  output.coherentSnapshot = updated.parts.length === 0 && updated.analysis.body_width.body_width_px == null && updated.analysis.body_width.relative_width_proxy == null && !!updated._previous_measurement_evidence;
                  const fallback = Object.fromEntries(bodyWidthRows({bbox:[0,0,200,50],parts:sample.parts}));
                  output.pixelFallback = fallback['Whole-fish bounding box'] === '200 x 50 px' && fallback['Body bounding box'] === '110 x 40 px' && fallback['Relative width proxy'] === 'Unavailable';
                  resultsFilter='Rejected'; renderResultsDashboard(null,{renderOnly:true});
                  output.emptyFilter = elements.resultsGroups.querySelector('[data-grade="Rejected"]')?.textContent.includes('0') && elements.resultsGroups.textContent.includes('No fish match');
                  resultsFilter='All'; renderResultsDashboard([sample,missing],{source:'upload',scope:'photo:smoke',complete:true});
                  const before = resultsEvents; toggleUpload(false);
                  output.singleMount = !elements.uploadWorkspace.contains(elements.resultsDashboard) && document.querySelectorAll('#recent-inspections').length === 1 && resultsEvents === before;
                  const report = resultReportHtml();
                  output.completeReport = ['A. Grading Evidence','B. Body Width and Geometric Analysis','C. Image Features and Measurements','D. Final Grading Explanation','calibration_validated','Class distribution','specular_ratio_proxy'].every(value => report.includes(value)) && !report.includes('Complete structured evidence');
                  output.noInferenceOnExpansion = performance.getEntriesByType('resource').filter(item => item.name.includes('/api/analyze-image')).length === 0;
                  return output;
                })()""")
                assert all(result.values()), result
                call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
                assert evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "Mobile page overflows"
                report = evaluate("resultReportHtml([window.__widthSample, {...window.__widthSample, track_id: 8}, {...window.__widthSample, track_id: 9}])")
                frame = call("Page.getFrameTree")["frameTree"]["frame"]["id"]
                call("Page.setDocumentContent", {"frameId": frame, "html": report})
                pdf = base64.b64decode(call("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True})["data"])
                assert pdf.startswith(b"%PDF-")
                pages = len(re.findall(rb"/Type\s*/Page\b", pdf))
                assert pages >= 3, f"Multi-fish report did not paginate: {pages} pages"
                print(f"Unified cards, identity updates, lazy sections, source isolation, mobile layout and {pages}-page PDF passed in headless Chrome")
        finally:
            if browser is not None:
                browser.terminate()
                browser.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
