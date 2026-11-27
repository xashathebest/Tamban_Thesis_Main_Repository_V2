"""Opt-in real-browser acceptance against the disposable annotation QA server.

This script is deliberately not a pytest test. Start the fixture using
``python -B tests/annotation_library_fixture_server.py`` on 127.0.0.1:8766,
then run ``python -B tests/annotation_library_browser_smoke.py``. Install the
optional Playwright package and Chrome; ../tmp/annotation_qa_deps is also searched.
It
modifies only that synthetic three-image fixture. Pass --include-actual-library
to also inspect the running V2 library on port 8001, with all browser writes
blocked. The existing service on port 8000 is never accessed.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import traceback
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
DEPS = PROJECT.parent / "tmp" / "annotation_qa_deps"
sys.path.insert(0, str(DEPS))
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:8766"
OUTPUT = PROJECT / "results" / "qa" / "annotation_library"
OUTPUT.mkdir(parents=True, exist_ok=True)
REPORT = {"origin": ORIGIN, "fixture_only": True, "checks": [], "page_errors": []}


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
            headless=True,
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.on("pageerror", lambda error: REPORT["page_errors"].append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        fixture = context.request.get(ORIGIN + "/api/qa/documents").json()
        assert len(fixture) == 3 and {d["filename"] for d in fixture} == {
            "review_001.png", "review_002.png", "review_003.png"
        }, "Refusing to test a server that is not the synthetic QA fixture"
        image_id = next(d["id"] for d in fixture if d["filename"] == "review_001.png")
        second_id = next(d["id"] for d in fixture if d["filename"] == "review_002.png")
        REPORT["image_id"] = image_id

        def get_image():
            return context.request.get(ORIGIN + "/api/annotation-library/images/" + image_id).json()

        def check(name, action):
            try:
                detail = action()
                REPORT["checks"].append({"name": name, "passed": True, "detail": detail})
                print("PASS " + name, flush=True)
                return True
            except Exception as error:
                REPORT["checks"].append({"name": name, "passed": False, "error": str(error), "traceback": traceback.format_exc()})
                print("FAIL " + name + ": " + str(error).encode("ascii", "backslashreplace").decode(), flush=True)
                try:
                    page.screenshot(path=str(OUTPUT / (name.replace(" ", "_") + "-failure.png")), full_page=True)
                except Exception:
                    pass
                return False

        def saved():
            page.wait_for_function("document.getElementById('save-state').textContent.includes('Saved') && !document.getElementById('save-state').textContent.includes('historical')")
            assert page.locator("#save-error").is_hidden()

        def select(annotation_id):
            page.locator(f'[data-annotation="{annotation_id}"]').click()
            assert page.locator("#selected-id").inner_text() == "ID " + annotation_id

        def open_current():
            page.locator(f'[data-open="{image_id}"]').first.click()
            page.wait_for_selector("#workspace:not(.hidden)")
            page.wait_for_function("!document.getElementById('viewer-loading').classList.contains('hidden') === false")
            assert page.locator("#annotation-total").inner_text() == "4"

        def download(button, name):
            with page.expect_download(timeout=20000) as pending:
                page.locator(button).click()
            artifact = pending.value
            target = OUTPUT / name
            artifact.save_as(str(target))
            assert target.stat().st_size > 0
            return target

        def gallery():
            page.goto(ORIGIN + "/annotations?acceptance=" + str(time.time_ns()))
            page.wait_for_selector(".image-card")
            assert page.locator(".image-card").count() == 3
            assert page.locator("#summary-cards .summary-card").count() == 8
            assert page.locator(".thumbnail-badge").count() == 3
            page.locator("#search-input").fill("review_002")
            page.wait_for_function("document.querySelectorAll('.image-card').length===1")
            assert "review_002.png" in page.locator("#gallery").inner_text()
            page.locator("#search-input").fill("")
            page.wait_for_function("document.querySelectorAll('.image-card').length===3")
            page.locator("#status-filter").select_option("not_annotated")
            page.wait_for_function("document.querySelectorAll('.image-card').length===0")
            page.locator("#status-filter").select_option("")
            page.wait_for_function("document.querySelectorAll('.image-card').length===3")
            page.locator("#sort-order").select_option("filename_desc")
            page.wait_for_function("document.querySelector('.file-button').textContent==='review_003.png'")
            page.locator('[data-view="completed"]').click()
            page.wait_for_function("document.getElementById('page-title').textContent==='Completed annotations'")
            page.wait_for_function("document.querySelectorAll('.image-card').length===3")
            assert page.locator(".image-card").count() == 3
            page.screenshot(path=str(OUTPUT / "dashboard.png"), full_page=True)
            return {"images": 3, "summary_cards": 8, "completed": 3, "search_filter_sort": True}

        if not check("gallery dashboard completed search filter sort", gallery):
            browser.close()
            return

        def masks_selection():
            open_current()
            assert page.locator("svg image[data-original]").count() == 1
            assert page.locator("svg .mask-shape").count() == 4
            assert page.locator(".fish-group").count() == 2
            select("head-1")
            assert page.locator('[data-ann="fish-2"]').get_attribute("opacity") == "0.3"
            point = page.locator("#annotation-svg").evaluate("svg => {const p=new DOMPoint(440,250).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y}}")
            page.mouse.click(point["x"], point["y"])
            assert page.locator("#selected-id").inner_text() == "ID fish-2"
            assert page.locator('[data-annotation="fish-2"]').get_attribute("aria-pressed") == "true"
            before = page.locator("#annotation-svg").get_attribute("viewBox")
            page.locator("#zoom-in").click()
            assert page.locator("#zoom-label").inner_text() == "130%"
            assert before != page.locator("#annotation-svg").get_attribute("viewBox")
            page.locator("#fit-image").click()
            page.locator("#show-masks").uncheck()
            assert page.locator(".mask-shape").count() == 0
            assert page.locator("svg image[data-original]").count() == 1
            page.locator("#show-labels").uncheck()
            assert page.locator(".annotation-label").count() == 0
            page.locator("#show-boxes").check()
            assert page.locator(".annotation-box").count() == 4
            page.locator("#show-masks").check()
            page.locator("#show-labels").check()
            page.locator("#show-boxes").uncheck()
            point = page.locator("#annotation-svg").evaluate("svg => {const p=new DOMPoint(610,40).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y}}")
            fit_box = page.locator("#annotation-svg").get_attribute("viewBox")
            page.mouse.move(point["x"], point["y"])
            page.mouse.down(); page.mouse.move(point["x"] - 30, point["y"] + 20); page.mouse.up()
            assert page.locator("#annotation-svg").get_attribute("viewBox") != fit_box
            page.locator("#fit-image").click()
            page.screenshot(path=str(OUTPUT / "review-workspace.png"), full_page=True)
            return {"fish": 2, "masks": 4, "actual_mask_hit_test": True, "original_and_toggles": True, "actual_pointer_pan": True}
        check("actual masks independent fish selection zoom toggles", masks_selection)

        def class_autosave():
            select("head-1")
            page.locator("#class-editor").select_option("2")
            page.wait_for_function("document.getElementById('save-state').textContent.includes('Saved')")
            saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["class_id"] == 2
            page.reload()
            page.wait_for_selector(".image-card")
            open_current()
            select("head-1")
            assert page.locator("#class-editor").input_value() == "2"
            page.locator("#class-editor").select_option("1")
            page.locator("#save-button").click()
            saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["class_id"] == 1
            return {"browser_reload_persistence": True, "manual_save": True}
        check("class edit autosave manual save reload persistence", class_autosave)

        def fail_retry():
            select("head-1")
            route_glob = "**/api/annotation-library/images/" + image_id
            def fail_put(route):
                if route.request.method == "PUT":
                    route.fulfill(status=503, content_type="application/json", body='{"detail":"Synthetic temporary storage failure"}')
                    page.unroute(route_glob, fail_put)
                else:
                    route.continue_()
            page.route(route_glob, fail_put)
            page.locator("#class-editor").select_option("2")
            page.wait_for_function("document.getElementById('save-state').textContent==='Save Failed'")
            assert page.locator("#save-error").is_visible()
            assert "Synthetic temporary storage failure" in page.locator("#save-error-message").inner_text()
            assert page.evaluate("id => localStorage.getItem('sardinella.annotation.draft.'+id)!==null", image_id)
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["class_id"] == 1
            page.locator("#retry-save").click()
            saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["class_id"] == 2
            return {"failure_503": True, "recoverable_draft": True, "retry_persisted": True}
        check("failed save retained draft and retry", fail_retry)

        def stale_conflict():
            server = get_image()
            response = context.request.put(ORIGIN + "/api/annotation-library/images/" + image_id, data={"base_version": server["version"], "status": "needs_review", "review_status": "needs_correction", "annotations": server["annotations"]})
            assert response.status == 200, response.text()
            select("head-1")
            page.locator("#class-editor").select_option("1")
            page.wait_for_function("document.getElementById('save-state').textContent==='Save Failed'")
            assert "newer version" in page.locator("#save-error-message").inner_text()
            target = download("#download-unsaved", "conflict-recovery-draft.json")
            assert json.loads(target.read_text("utf-8"))["annotations"]
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["class_id"] == 2
            page.locator("#reload-image").click()
            page.wait_for_function("document.getElementById('save-state').textContent.includes('Saved')")
            assert page.locator("#draft-recovery").is_visible()
            assert page.locator("#restore-draft").is_disabled()
            page.locator("#discard-draft").click()
            return {"actual_revision_conflict": True, "server_not_overwritten": True, "draft_download": True}
        check("stale version conflict preserves server and draft", stale_conflict)

        def undo_redo_peer():
            select("head-2")
            if not page.locator("#approve-object").is_disabled():
                page.locator("#approve-object").click()
                page.wait_for_function("document.getElementById('selected-source').textContent.includes('Approved')")
            saved()
            peer = next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-2")
            assert peer["status"] == "approved", peer
            select("head-1")
            before = int(page.locator("#class-editor").input_value())
            after = 1 if before == 2 else 2
            page.locator("#class-editor").select_option(str(after))
            page.locator("#save-button").click(); saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-2") == peer
            page.locator("#undo-edit").click()
            assert page.locator("#class-editor").input_value() == str(before)
            page.locator("#save-button").click(); saved()
            page.locator("#redo-edit").click()
            assert page.locator("#class-editor").input_value() == str(after)
            page.locator("#save-button").click(); saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-2") == peer
            select("head-1")
            page.locator("#reject-object").click()
            page.wait_for_function("document.getElementById('selected-source').textContent.includes('Rejected')")
            saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-2") == peer
            page.locator("#approve-object").click()
            page.wait_for_function("document.getElementById('selected-source').textContent.includes('Approved')")
            saved()
            return {"approve_and_reject_selected": True, "approved_peer_exactly_preserved": True, "undo_redo_persisted": True}
        check("per object review peer preservation undo redo", undo_redo_peer)

        def polygon_add_delete():
            select("head-1")
            old_polygon = next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["segmentation"]
            handle = page.locator(".vertex-handle").first.bounding_box()
            page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
            page.mouse.down(); page.mouse.move(handle["x"] + handle["width"] / 2 + 3, handle["y"] + handle["height"] / 2 + 3); page.mouse.up()
            page.locator("#save-button").click(); saved()
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == "head-1")["segmentation"] != old_polygon
            page.locator("#new-class").select_option("3")
            page.locator("#add-polygon").click()
            for x, y in [(590, 310), (620, 310), (610, 335)]:
                point = page.locator("#annotation-svg").evaluate("(svg,xy) => {const p=new DOMPoint(...xy).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y}}", [x, y])
                page.mouse.click(point["x"], point["y"])
            page.locator("#finish-polygon").click()
            page.locator("#save-button").click(); saved()
            assert len(get_image()["annotations"]) == 5
            added_id = page.locator("#selected-id").inner_text().removeprefix("ID ")
            assert added_id not in {"fish-1", "fish-2", "head-1", "head-2"}
            assert next(a for a in get_image()["annotations"] if a["annotation_id"] == added_id)["segmentation"]
            page.locator("#delete-annotation").click()
            page.locator("#save-button").click(); saved()
            assert len(get_image()["annotations"]) == 4
            return {"actual_vertex_drag_correction_persisted": True, "actual_pointer_polygon": True, "added_and_deleted_saved": True}
        check("draw add and delete polygon", polygon_add_delete)

        def history():
            page.wait_for_function("document.querySelectorAll('#history-select option').length>3")
            options = page.locator("#history-select option").evaluate_all("nodes=>nodes.map(n=>n.value).filter(Boolean)")
            historical = next(value for value in options if value == "2")
            before = get_image()["version"]
            page.locator("#history-select").select_option(historical)
            page.wait_for_function("document.getElementById('save-state').textContent==='Saved historical version'")
            assert page.locator("#add-polygon").is_disabled()
            assert page.locator("#restore-version").is_visible()
            page.locator("#restore-version").click()
            saved()
            assert get_image()["version"] > before
            assert len(get_image()["annotations"]) == 4
            return {"preview_read_only": True, "restored_as_new_revision": True, "previous_versions_retained": True}
        check("history preview and restore new revision", history)

        def exports_review():
            current = download("#export-current", "current-annotations.json")
            payload = json.loads(current.read_text("utf-8"))
            assert len(payload["images"]) == 1
            assert len(payload["images"][0]["annotations"]) == 4
            assert all(a["segmentation"] and a["class_name"] for a in payload["images"][0]["annotations"])
            page.locator("#review-button").click(); saved()
            page.wait_for_function("!document.getElementById('approve-button').disabled")
            page.locator("#approve-button").click()
            page.wait_for_function("document.getElementById('image-status').textContent==='Approved'")
            assert get_image()["status"] == "approved"
            page.locator("#needs-correction").click(); saved()
            assert get_image()["review_status"] == "needs_correction"
            assert get_image()["status"] != "approved"
            page.locator("#review-button").click(); saved()
            page.wait_for_function("!document.getElementById('approve-button').disabled")
            page.locator("#approve-button").click()
            page.wait_for_function("document.getElementById('image-status').textContent==='Approved'")
            page.locator("#back-library").click()
            page.wait_for_selector(".image-card")
            page.locator(f'[data-select="{image_id}"]').check()
            page.locator(f'[data-select="{second_id}"]').check()
            selected = download("#export-selected", "selected-annotations.json")
            assert len(json.loads(selected.read_text("utf-8"))["images"]) == 2
            page.locator('[data-view="export"]').click()
            page.locator("#export-scope").select_option("approved")
            approved = download("#download-export", "approved-annotations.json")
            approved_json = json.loads(approved.read_text("utf-8"))
            assert len(approved_json["images"]) == 1
            assert all(i["status"] == "approved" for i in approved_json["images"])
            page.locator("#export-scope").select_option("all")
            page.locator("#export-package").check()
            package = download("#download-export", "complete-dataset.zip")
            with zipfile.ZipFile(package) as archive:
                assert any(name.endswith(".json") for name in archive.namelist())
                assert sum(name.startswith("images/") and name.endswith(".png") for name in archive.namelist()) == 3
            return {"current_json": 1, "selected_json": 2, "approved_json": 1, "dataset_images": 3, "segmentation_present": True, "needs_correction_demotes": True}
        check("review approve correction and actual JSON ZIP downloads", exports_review)

        def rle_preview():
            page.locator('[data-view="completed"]').click()
            page.wait_for_selector(".image-card")
            page.locator(f'[data-open="{second_id}"]').first.click()
            page.wait_for_selector("#workspace:not(.hidden)")
            page.wait_for_function("document.getElementById('viewer-loading').classList.contains('hidden')")
            assert page.locator("#annotation-svg image").count() == 2
            annotation_id = page.locator("[data-annotation]").first.get_attribute("data-annotation")
            point = page.locator("#annotation-svg").evaluate("svg => {const p=new DOMPoint(110,110).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y}}")
            page.mouse.click(point["x"], point["y"])
            assert page.locator("#selected-id").inner_text() == "ID " + annotation_id
            assert page.locator("#polygon-editor").get_attribute("readonly") is not None
            assert "RLE mask preserved" in page.locator("#editor-feedback").inner_text()
            page.screenshot(path=str(OUTPUT / "imported-rle-preview.png"), full_page=True)
            page.locator("#back-library").click()
            page.wait_for_selector(".image-card")
            return {"actual_imported_rle_raster_visible": True, "pixel_hit_test": True, "non_destructive_editor": True}
        check("imported exact RLE preview and pixel selection", rle_preview)

        def training_classes():
            page.locator("#annotation-training-panel summary").click()
            page.wait_for_function("typeof window.annotationLibrary==='object'")
            name = "Browser QA unused " + str(time.time_ns())
            page.locator("#training-new-class-name").fill(name)
            page.locator("#training-class-add").click()
            page.wait_for_function("name=>Array.from(document.getElementById('training-class-select').options).some(o=>o.textContent.startsWith(name))", arg=name)
            page.wait_for_load_state("networkidle")
            class_id = page.locator("#training-class-select option").evaluate_all("(nodes,name)=>nodes.find(n=>n.textContent.startsWith(name)).value", name)
            page.locator("#training-class-select").select_option(class_id)
            page.locator("#training-class-name").fill(name + " renamed")
            page.locator("#training-class-color").fill("#aa3344")
            page.locator("#training-class-save").click()
            page.wait_for_function("name=>document.querySelector('#training-class-select option:checked').textContent.startsWith(name)", arg=name + " renamed")
            page.wait_for_load_state("networkidle")
            page.locator("#training-class-remove").click()
            page.wait_for_function("id=>!Array.from(document.getElementById('training-class-select').options).some(o=>o.value===id)", arg=class_id)
            page.locator('[data-view="completed"]').click()
            page.wait_for_selector(".image-card")
            open_current()
            if not page.locator("#annotation-training-panel").evaluate("el=>el.open"):
                page.locator("#annotation-training-panel summary").click()
            page.locator("#training-scope").select_option("current")
            page.locator("#training-validate").click()
            page.wait_for_function("document.getElementById('training-result').textContent.startsWith('Validation')")
            assert "Validation passed" in page.locator("#training-result").inner_text(), page.locator("#training-result").inner_text()
            target = download("#training-download", "coco-training.zip")
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                assert any(".json" in name for name in names)
                assert any("masks/" in name and name.endswith(".png") for name in names), names
            return {"central_class_add_rename_color_remove": True, "current_validation": True, "real_coco_zip_masks": True, "validation_report": page.locator("#training-result").inner_text()}
        check("class manager canonical validation training ZIP", training_classes)

        def mobile():
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(100)
            widths = page.evaluate("({width:innerWidth, body:document.body.scrollWidth, html:document.documentElement.scrollWidth})")
            assert widths["body"] <= widths["width"] + 1 and widths["html"] <= widths["width"] + 1, widths
            page.screenshot(path=str(OUTPUT / "mobile-workspace.png"), full_page=True)
            return widths
        check("mobile viewport no horizontal overflow", mobile)

        def actual_library_readonly():
            actual_origin = "http://127.0.0.1:8001"
            actual_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            actual = actual_context.new_page()
            blocked = []
            def only_read(route):
                if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                    blocked.append({"method": route.request.method, "url": route.request.url})
                    route.abort()
                else:
                    route.continue_()
            actual.route("**/*", only_read)
            actual.on("pageerror", lambda error: REPORT["page_errors"].append("actual: " + str(error)))
            actual.goto(actual_origin + "/annotations?readonly-acceptance=" + str(time.time_ns()))
            actual.wait_for_function("document.querySelectorAll('.image-card').length===24")
            actual.wait_for_function("document.querySelectorAll('#summary-cards .summary-card').length===8")
            dataset_id = actual.evaluate("window.annotationLibrary?.getDataset?.() || ''")
            query = "?dataset_id=" + dataset_id if dataset_id else ""
            summary = actual_context.request.get(actual_origin + "/api/annotation-library/summary" + query).json()
            assert summary["total_images"] > 0 and summary["completed_annotations"] > 0
            assert summary["total_annotated_objects"] > 0
            cards = actual.locator("#summary-cards .summary-card strong").all_inner_texts()
            assert int(cards[0].replace(",", "")) == summary["total_images"]
            assert int(cards[1].replace(",", "")) == summary["completed_annotations"]
            assert int(cards[2].replace(",", "")) == summary["pending_annotations"]
            assert int(cards[7].replace(",", "")) == summary["total_annotated_objects"]
            # Off-screen thumbnails intentionally remain lazy; verify real pixels
            # for the visible first card without forcing all 24 requests at once.
            actual.wait_for_function("document.querySelector('.thumbnail-button img').complete && document.querySelector('.thumbnail-button img').naturalWidth>0")
            actual.screenshot(path=str(OUTPUT / "actual_library.png"), full_page=True)
            actual.locator('[data-view="completed"]').click()
            actual.wait_for_function("document.getElementById('page-title').textContent==='Completed annotations' && document.querySelectorAll('.image-card').length===24")
            actual.wait_for_function("document.getElementById('gallery').getAttribute('aria-busy')==='false'")
            actual_id = actual.locator("[data-open]").first.get_attribute("data-open")
            before = actual_context.request.get(actual_origin + "/api/annotation-library/images/" + actual_id).json()
            actual.locator("[data-open]").first.click()
            actual.wait_for_selector("#workspace:not(.hidden)")
            actual.wait_for_function("document.getElementById('viewer-loading').classList.contains('hidden')")
            assert int(actual.locator("#annotation-total").inner_text()) == len(before["annotations"]) > 0
            assert actual.locator("#annotation-svg image").count() == len(before["annotations"]) + 1
            actual.locator("[data-annotation]").first.click()
            assert actual.locator("#polygon-editor").get_attribute("readonly") is not None
            assert "RLE mask preserved" in actual.locator("#editor-feedback").inner_text()
            original = actual_context.request.get(actual_origin + actual.locator("#original-link").get_attribute("href"))
            assert original.status == 200 and original.headers.get("content-type", "").startswith("image/")
            actual.screenshot(path=str(OUTPUT / "actual_review.png"), full_page=True)
            after = actual_context.request.get(actual_origin + "/api/annotation-library/images/" + actual_id).json()
            assert after == before
            assert not blocked, blocked
            actual_context.close()
            return {"dataset_id": dataset_id, "total": summary["total_images"], "completed": summary["completed_annotations"], "pending": summary["pending_annotations"], "objects": summary["total_annotated_objects"], "paginated_thumbnail_cards": 24,
                    "inspected_image": before["file_name"], "visible_exact_rle_masks": len(before["annotations"]),
                    "original_image_200": True, "no_mutating_requests": True, "saved_document_exactly_unchanged": True}
        if "--include-actual-library" in sys.argv:
            check("actual V2 dataset readonly dashboard and mask workspace", actual_library_readonly)
        REPORT["page_errors_empty"] = not REPORT["page_errors"]
        REPORT["passed"] = all(c["passed"] for c in REPORT["checks"]) and not REPORT["page_errors"]
        REPORT["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        browser.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    finally:
        (OUTPUT / "browser-report.json").write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
    raise SystemExit(0 if REPORT.get("passed") else 1)
