"""Opt-in read-only browser QA for the finished cleaned/legacy dataset import.

Run explicitly after the normal application is already listening on port 8001:
``python -B tests/annotation_library_dataset_browser.py --run``.
This runner never starts a server, edits labels, invokes inference, or contacts
port 8000. Browser writes are blocked except JSON-only saved-data exports.
Only ignored screenshots, downloads, and a compact QA report are produced.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import traceback
from urllib.parse import quote, urlparse

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent / "tmp" / "annotation_qa_deps"))

ORIGIN = "http://127.0.0.1:8001"
API = ORIGIN + "/api/annotation-library"
PRIMARY = "fish-annotations-cleaned-dbf50ab47c1d"
LEGACY = "v2-coco-v7"
OUTPUT = PROJECT / "results" / "qa" / "annotation_library"
REPORT_PATH = OUTPUT / "primary-dataset-browser.json"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def mask_digest(rle: dict) -> tuple[str, int]:
    """Decode COCO column-major runs independently of the frontend renderer."""
    height, width = rle["size"]
    encoded = rle["counts"]
    if isinstance(encoded, list):
        counts = encoded
    else:
        counts, position = [], 0
        while position < len(encoded):
            value, shift = 0, 0
            while True:
                token = ord(encoded[position]) - 48
                position += 1
                assert 0 <= token <= 63
                value |= (token & 31) << shift
                shift += 5
                if not token & 32:
                    if token & 16:
                        value -= 1 << shift
                    break
            if len(counts) > 2:
                value += counts[-2]
            counts.append(value)
    assert all(isinstance(count, int) and count >= 0 for count in counts)
    assert sum(counts) == width * height
    # Browser ImageData uses row-major pixels, so explicitly transpose runs.
    mask, position, foreground = bytearray(width * height), 0, 0
    for index, count in enumerate(counts):
        if index % 2:
            foreground += count
            for pixel in range(position, position + count):
                column, row = divmod(pixel, height)
                mask[row * width + column] = 1
        position += count
    assert foreground > 0
    return sha(mask), foreground


def native_snapshot(database: Path, image_id: str) -> dict:
    """Read exact saved JSON and revisions without opening a write connection."""
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        document = connection.execute("SELECT document FROM images WHERE id=?", (image_id,)).fetchone()
        assert document is not None
        revisions = connection.execute("SELECT revision,document FROM revisions WHERE image_id=? ORDER BY revision", (image_id,)).fetchall()
    return {"document": document[0], "revisions": revisions}


def run() -> dict:
    from playwright.sync_api import sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"origin": ORIGIN, "read_only": True, "primary_dataset_id": PRIMARY,
              "legacy_dataset_id": LEGACY, "checks": [], "page_errors": [],
              "blocked_requests": [], "allowed_export_requests": [], "screenshots": []}
    selected_id, before_native, before_api, database = None, None, None, None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        context.set_default_timeout(30000)
        page = context.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        downloads = []
        page.on("download", lambda item: downloads.append(item.suggested_filename))

        def guard(route):
            request = route.request
            parsed = urlparse(request.url)
            if parsed.scheme not in {"http", "https"}:
                route.continue_()
                return
            accepted = parsed.scheme == "http" and parsed.netloc == "127.0.0.1:8001" and request.method in {"GET", "HEAD", "OPTIONS"}
            if request.method == "POST" and parsed.scheme == "http" and parsed.netloc == "127.0.0.1:8001" and parsed.path == "/api/annotation-library/export":
                payload = request.post_data_json
                accepted = isinstance(payload, dict) and payload.get("package") is False and payload.get("scope") in {"all", "current", "selected", "approved"}
                if accepted:
                    report["allowed_export_requests"].append(payload)
            if accepted:
                route.continue_()
            else:
                report["blocked_requests"].append({"method": request.method, "url": request.url})
                route.abort()

        context.route("**/*", guard)

        def get(path):
            assert path.startswith("/") and not path.startswith("//")
            response = context.request.get(API + path, timeout=60000)
            assert response.ok, f"GET {path}: HTTP {response.status}"
            return response.json()

        def screenshot(name):
            target = OUTPUT / name
            page.screenshot(path=str(target), full_page=True)
            report["screenshots"].append(str(target.relative_to(PROJECT)))

        def check(name, action):
            try:
                detail = action()
                report["checks"].append({"name": name, "passed": True, "detail": detail})
                print("PASS " + name, flush=True)
                return detail
            except Exception as error:
                report["checks"].append({"name": name, "passed": False, "error": str(error), "traceback": traceback.format_exc()})
                print("FAIL " + name + ": " + str(error), flush=True)
                try:
                    screenshot("primary-" + name.replace(" ", "-") + "-failure.png")
                except Exception:
                    pass
                return None

        def wait_gallery(total, dataset_id):
            page.wait_for_function("([total,id]) => document.querySelector('#dataset-select').value === id && document.querySelector('#gallery').getAttribute('aria-busy') === 'false' && document.querySelectorAll('.image-card').length === Math.min(24,total) && Number(document.querySelector('#summary-cards strong')?.textContent.replaceAll(',','')) === total", arg=[total, dataset_id])

        def assert_summary(dataset_id, images, annotations):
            summary = get("/summary" + ("?dataset_id=" + dataset_id if dataset_id else ""))
            assert summary["total_images"] == images, summary
            assert summary["total_annotated_objects"] == annotations, summary
            assert summary["dataset_id"] == (dataset_id or None)
            values = [int(value.replace(",", "")) for value in page.locator("#summary-cards strong").all_inner_texts()]
            assert values == [summary[key] for key in ("total_images", "completed_annotations", "pending_annotations", "approved_annotations", "needs_correction", "rejected_images", "saved_datasets", "total_annotated_objects")]
            assert page.locator(".image-card").count() == 24
            assert str(images) in page.locator("#page-caption").inner_text().replace(",", "")
            assert page.locator("#next-page").is_enabled()
            return summary

        def default_primary():
            registry = get("/datasets")
            assert registry["primary_dataset_id"] == PRIMARY, registry
            primary = next(item for item in registry["datasets"] if item["id"] == PRIMARY)
            assert primary["status"] == "ready", primary
            assert primary["image_count"] == 345
            page.goto(ORIGIN + "/annotations?readonly-dataset-qa=" + str(time.time_ns()), wait_until="domcontentloaded", timeout=60000)
            wait_gallery(345, PRIMARY)
            assert "Primary" in page.locator("#dataset-select option:checked").inner_text()
            summary = assert_summary(PRIMARY, 345, 4867)
            assert summary["completed_annotations"] == 345 and summary["pending_annotations"] == 0
            page.wait_for_function("document.querySelector('.thumbnail-button img').complete && document.querySelector('.thumbnail-button img').naturalWidth>0")
            screenshot("primary-dashboard.png")
            return {"primary_name": primary["name"], "summary": summary, "cards": 24}

        def complete_and_search():
            page.locator('[data-view="completed"]').click()
            page.wait_for_function("document.querySelector('#page-title').textContent === 'Completed annotations'")
            wait_gallery(345, PRIMARY)
            completed = get("/images?dataset_id=" + PRIMARY + "&completed=true&page_size=24")
            assert completed["total"] == 345 and len(completed["images"]) == 24
            first = completed["images"][0]
            term = first["file_name"]
            page.locator("#search-input").fill(term)
            expected = get("/images?dataset_id=" + PRIMARY + "&completed=true&page_size=24&search=" + quote(term))
            page.wait_for_function("expected => document.querySelector('#gallery').getAttribute('aria-busy') === 'false' && document.querySelectorAll('.image-card').length === expected && !document.querySelector('#page-caption').textContent.includes('345 images')", arg=len(expected["images"]))
            assert expected["total"] >= 1
            assert all(term.casefold() in text.casefold() for text in page.locator(".file-button").all_inner_texts())
            screenshot("primary-source-filename-search.png")
            page.locator("#search-input").fill("")
            wait_gallery(345, PRIMARY)
            return {"completed": completed["total"], "source_filename": term, "matches": expected["total"]}

        def workspace_masks():
            nonlocal selected_id, before_native, before_api, database
            selected_id = page.locator("[data-open]").first.get_attribute("data-open")
            before_api = get("/images/" + selected_id)
            assert before_api["dataset_id"] == PRIMARY
            summary = get("/summary?dataset_id=" + PRIMARY)
            database = Path(summary["storage_path"]).resolve()
            assert database == (PROJECT / "dataset/annotation_workspace/annotations.sqlite3").resolve()
            before_native = native_snapshot(database, selected_id)
            page.locator("[data-open]").first.click()
            page.wait_for_selector("#workspace:not(.hidden)")
            page.wait_for_function("document.querySelector('#viewer-loading').classList.contains('hidden')")
            annotations = before_api["annotations"]
            assert annotations and all(isinstance(ann["segmentation"], dict) for ann in annotations)
            width, height = before_api["width"], before_api["height"]
            assert int(page.locator("#annotation-total").inner_text()) == len(annotations)
            assert page.locator("[data-annotation]").count() == len(annotations)
            assert page.locator("#annotation-svg image").count() == len(annotations) + 1
            assert f"{width} × {height} px" in page.locator("#image-details").inner_text()
            assert page.locator('#annotation-svg image[data-original]').get_attribute("width") == str(width)
            assert page.locator('#annotation-svg image[data-original]').get_attribute("height") == str(height)
            assert page.locator("#annotation-svg").get_attribute("viewBox") == f"0 0 {width} {height}"
            labels = page.evaluate("""() => {
              const rectangles=[...document.querySelectorAll('#annotation-svg .annotation-label-background')];
              const boxes=rectangles.map(rect=>{const text=rect.parentNode.querySelector('.annotation-label'),r=rect.getBBox(),t=text.getBBox();return {text:text.textContent,background:{x:r.x,y:r.y,width:r.width,height:r.height},text_bounds:{x:t.x,y:t.y,width:t.width,height:t.height},within:t.x>=r.x-.05&&t.y>=r.y-.05&&t.x+t.width<=r.x+r.width+.05&&t.y+t.height<=r.y+r.height+.05,noninteractive:rect.parentNode.parentNode.getAttribute('pointer-events')==='none'};});
              const overlaps=[];
              for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i].background,b=boxes[j].background;if(a.x<b.x+b.width-.05&&a.x+a.width>b.x+.05&&a.y<b.y+b.height-.05&&a.y+a.height>b.y+.05)overlaps.push([i,j]);}
              return {count:boxes.length,overlaps,boxes};
            }""")
            assert labels["count"] == len(annotations), labels
            assert not labels["overlaps"], labels
            assert all(label["within"] and label["noninteractive"] for label in labels["boxes"]), labels
            checks = []
            for ann in annotations:
                assert ann["segmentation"]["size"] == [height, width]
                expected_hash, expected_area = mask_digest(ann["segmentation"])
                actual = page.evaluate("""async ({id,width,height}) => {
                  const group=[...document.querySelectorAll('#annotation-svg [data-ann]')].find(node=>node.dataset.ann===id);
                  const overlay=group?.querySelector('image'); if(!overlay)throw new Error('Missing RLE overlay '+id);
                  const img=new Image(); img.src=overlay.getAttribute('href'); await img.decode();
                  const canvas=document.createElement('canvas'); canvas.width=width; canvas.height=height;
                  const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0);
                  const pixels=ctx.getImageData(0,0,width,height).data, mask=new Uint8Array(width*height); let area=0;
                  for(let i=0;i<mask.length;i++){mask[i]=pixels[i*4+3]>0?1:0;area+=mask[i];}
                  const digest=await crypto.subtle.digest('SHA-256',mask);
                  return {sha256:[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join(''),area,natural_width:img.naturalWidth,natural_height:img.naturalHeight};
                }""", {"id": ann["annotation_id"], "width": width, "height": height})
                assert actual["sha256"] == expected_hash and actual["area"] == expected_area
                assert [actual["natural_height"], actual["natural_width"]] == [height, width]
                checks.append({"annotation_id": ann["annotation_id"], "class_name": ann["class_name"], "mask_sha256": expected_hash, "foreground_pixels": expected_area})
                row = page.locator('[data-annotation="' + ann["annotation_id"] + '"]')
                assert ann["class_name"] in row.inner_text()
            page.locator("[data-annotation]").first.click()
            assert page.locator("#class-editor").input_value() == str(annotations[0]["class_id"])
            assert annotations[0]["class_name"] in page.locator("#class-editor option:checked").inner_text()
            assert page.locator("#polygon-editor").get_attribute("readonly") is not None
            assert "RLE mask preserved" in page.locator("#editor-feedback").inner_text()
            original_href = page.locator("#original-link").get_attribute("href")
            assert original_href.startswith("/api/annotation-library/images/")
            original = context.request.get(ORIGIN + original_href)
            assert original.status == 200 and original.headers.get("content-type", "").startswith("image/")
            original_dimensions = page.evaluate("""async url=>{const img=new Image();img.src=url;await img.decode();return [img.naturalWidth,img.naturalHeight]}""", original_href)
            assert original_dimensions == [width, height]
            screenshot("primary-canonical-rle-workspace.png")
            page.locator("#zoom-in").click()
            assert page.locator("#zoom-label").inner_text() == "130%"
            page.locator("#fit-image").click()
            page.locator("#show-masks").uncheck()
            assert page.locator("#annotation-svg image").count() == 1
            page.locator("#show-masks").check()
            assert page.locator("#annotation-svg image").count() == len(annotations) + 1
            return {"image_id": selected_id, "source_filename": before_api["file_name"], "dimensions": [width, height], "canonical_masks": checks, "original_http_status": 200, "sidebar_classes": True, "display_controls": True,
                    "overlay_labels": {"count": labels["count"], "backgrounds_pairwise_nonoverlapping": True, "text_within_backing_bounds": True, "pointer_events_none": True}}

        def download(button):
            with page.expect_download(timeout=180000) as pending:
                page.locator(button).click()
            target = OUTPUT / ("primary-" + pending.value.suggested_filename)
            pending.value.save_as(str(target))
            assert target.stat().st_size > 0
            return target, json.loads(target.read_text(encoding="utf-8"))

        def exports():
            _, current = download("#export-current")
            assert len(current["images"]) == 1 and current["images"][0] == before_api
            page.locator("#back-library").click()
            wait_gallery(345, PRIMARY)
            page.locator('[data-select="' + selected_id + '"]').check()
            _, selected = download("#export-selected")
            assert len(selected["images"]) == 1 and selected["images"][0] == before_api
            page.locator('[data-view="export"]').click()
            wait_gallery(345, PRIMARY)
            page.locator("#export-scope").select_option("all")
            assert not page.locator("#export-package").is_checked()
            target, exported = download("#download-export")
            assert exported["dataset"]["dataset_id"] == PRIMARY
            assert exported["dataset"]["image_count"] == len(exported["images"]) == 345
            assert exported["dataset"]["annotation_count"] == sum(len(image["annotations"]) for image in exported["images"]) == 4867
            source_category_count = set()
            for image in exported["images"]:
                assert image["dataset_id"] == PRIMARY
                source_categories = image["metadata"]["source_dataset_metadata"]["categories"]
                assert source_categories
                categories = {item["id"]: item for item in source_categories}
                for annotation in image["annotations"]:
                    assert isinstance(annotation["segmentation"], dict) and annotation["segmentation"]["counts"]
                    assert annotation["segmentation"]["size"] == [image["height"], image["width"]]
                    metadata = annotation["metadata"]
                    original = metadata["workspace_fields"]["original_annotation"]
                    source_category = metadata["workspace_fields"]["source_category"]
                    assert source_category == categories[original["category_id"]]
                    source_category_count.add(original["category_id"])
            summary = get("/summary?dataset_id=" + PRIMARY)
            assert summary["approved_annotations"] == 0
            before_downloads = len(downloads)
            page.locator("#export-scope").select_option("approved")
            with page.expect_response(lambda response: response.url == API + "/export" and response.request.method == "POST", timeout=60000) as pending:
                page.locator("#download-export").click()
            assert pending.value.status == 422
            page.wait_for_function("document.querySelector('#export-feedback').textContent.startsWith('Export failed:') && !document.querySelector('#download-export').disabled")
            assert "No saved annotations match" in page.locator("#export-feedback").inner_text()
            assert len(downloads) == before_downloads
            screenshot("primary-empty-approved-export-feedback.png")
            return {"current_images": 1, "selected_images": 1, "all_primary_images": 345, "all_primary_annotations": 4867, "all_json_path": str(target.relative_to(PROJECT)), "source_category_ids_preserved": sorted(source_category_count), "empty_approved_status": 422, "empty_approved_downloaded": False}

        def dataset_switches():
            details = {}
            for dataset_id, total, objects, name in [(LEGACY, 910, 9723, "legacy"), ("", 1255, 14590, "all"), (PRIMARY, 345, 4867, "primary_restored")]:
                page.locator("#dataset-select").select_option(dataset_id)
                wait_gallery(total, dataset_id)
                summary = assert_summary(dataset_id, total, objects)
                rows = get("/images?page_size=24" + ("&dataset_id=" + dataset_id if dataset_id else ""))
                assert rows["total"] == total and len(rows["images"]) == 24
                if dataset_id:
                    assert all(image["dataset_id"] == dataset_id for image in rows["images"])
                details[name] = {key: summary[key] for key in ("total_images", "total_annotated_objects", "completed_annotations", "pending_annotations")}
                screenshot("primary-scope-" + name + ".png")
            page.locator('[data-view="dashboard"]').click()
            wait_gallery(345, PRIMARY)
            page.locator("#next-page").click()
            page.wait_for_function("document.querySelector('#gallery').getAttribute('aria-busy') === 'false' && document.querySelector('#page-caption').textContent.startsWith('Page 2 of 15')")
            assert page.locator(".image-card").count() == 24
            details["primary_second_page_cards"] = 24
            return details

        try:
            if check("default primary dashboard", default_primary) is not None:
                check("completed source filename search", complete_and_search)
                if check("canonical RLE photo sidebar", workspace_masks) is not None:
                    check("scoped JSON exports and empty approved failure", exports)
                check("legacy all primary switching and pagination", dataset_switches)
        finally:
            if selected_id and before_native is not None:
                def saved_unchanged():
                    after_api = get("/images/" + selected_id)
                    after_native = native_snapshot(database, selected_id)
                    assert after_api == before_api
                    assert after_native == before_native
                    return {"image_id": selected_id, "api_document_exactly_unchanged": True, "native_document_exactly_unchanged": True, "all_saved_revisions_exactly_unchanged": True, "native_document_sha256": sha(before_native["document"].encode()), "saved_revisions": len(before_native["revisions"])}
                check("saved document and revisions unchanged", saved_unchanged)
            report["no_mutating_requests"] = not report["blocked_requests"]
            report["passed"] = len(report["checks"]) == 6 and all(check["passed"] for check in report["checks"]) and not report["page_errors"] and report["no_mutating_requests"]
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            context.close()
            browser.close()
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly run against the already running app on port 8001.")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required; start the normal application separately after its primary import is ready.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = run()
    print(json.dumps({"passed": result["passed"], "report": str(REPORT_PATH), "checks": len(result["checks"]), "page_errors": result["page_errors"], "blocked_requests": result["blocked_requests"]}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result["passed"] else 1)
