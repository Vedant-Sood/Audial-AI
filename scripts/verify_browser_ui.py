"""Actual Chromium page flows, notifications, layout and denied capture.

ASR readiness is overridden only to reach the browser permission failure. This
does not run ASR, fabricate a transcript or establish real microphone operation.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright, expect
    from app.services.browser import BrowserService
    from app.utils.config import Settings

    with tempfile.TemporaryDirectory(prefix="audial-page-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        service = BrowserService(settings=Settings(device="cpu"))
        service.start()
        report = {"platform": platform.platform(), "scope": __doc__, "page_errors": []}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=args.browser,
                    headless=True,
                    args=["--no-sandbox", "--use-fake-device-for-media-stream"],
                )
                report["browser_version"] = browser.version
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                page.on(
                    "pageerror", lambda error: report["page_errors"].append(str(error))
                )
                page.goto(service.url)
                page.locator("summary").filter(has_text="Text and documents").click()
                page.locator("#phrase").fill("धन्यवाद team")
                page.locator("#display-phrase").click()
                expect(page.locator("#caption")).to_have_text("धन्यवाद team")
                expect(page.locator("#sign-status")).not_to_contain_text("Waiting")
                report["real_text_to_isl"] = "PASS"
                page.locator("#document-file").set_input_files(
                    {
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                        "buffer": b"thank you team",
                    }
                )
                expect(page.locator("#caption")).to_have_text("thank you team")
                report["local_document_to_isl"] = "PASS"
                page.evaluate("""async () => {
                    const {BrowserNotices}=await import('/notifications.js');
                    const n=new BrowserNotices(document.querySelector('#error'),document.querySelector('#notification-history'));
                    n.publish('Persistent failure under review','error');
                    for(let i=0;i<20;i++) n.publish('Persistent failure under review','error');
                    n.publish('A routine warning','warning');
                    globalThis.__noticeCheck=n;
                }""")
                page.wait_for_timeout(7200)
                assert page.locator("#error").is_visible()
                assert "Persistent failure" in page.locator("#error").inner_text()
                assert "routine warning" not in page.locator("#error").inner_text()
                assert page.evaluate("__noticeCheck.items.length") == 2
                assert page.evaluate("__noticeCheck.items[0].count") == 21
                report["persistent_failures_survive_transient_warning"] = "PASS"
                page.locator("#error button").first.click()
                assert page.locator("#error").is_hidden()
                page.locator("#display-phrase").focus()
                page.keyboard.press("Tab")
                assert page.evaluate("document.activeElement.matches(':focus-visible')")
                page.screenshot(
                    path=str(args.output / "browser-desktop.png"), full_page=True
                )
                service.engine.manager.installed = lambda _: True
                context.grant_permissions([], origin=service.url)
                page.locator("#microphone").click()
                import re
                expect(page.locator("#error")).to_be_visible()
                expect(page.locator("#error")).to_contain_text(re.compile("denied|permission|notallowed", re.I))
                assert not service.engine.running and service.engine.capture is None
                report["browser_microphone_denied"] = (
                    "PASS; actual browser permission override, no audio device or ASR started"
                )
                for width, height in [(1280, 900), (390, 844)]:
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_timeout(100)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    page.screenshot(
                        path=str(args.output / f"browser-errors-{width}.png"),
                        full_page=True,
                    )
                report["responsive_layout_and_keyboard"] = (
                    "PASS; desktop and mobile widths, visible keyboard focus"
                )
                assert not report["page_errors"]
                browser.close()
        finally:
            service.stop()
        (args.output / "browser-ui-acceptance.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
