"""Isolate real browser tab discard from Audial's capture/native integration."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import tempfile
import threading

from scripts.package_extension import extension_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "platform": platform.platform(),
        "scope": "Real Chrome tabs API with a minimal tabs-only extension; no Audial product JS, native host, capture, audio or inference",
    }

    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<!doctype html><title>Discard isolation fixture</title><p>Static page</p>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="audial-discard-isolation-") as temporary:
            directory = Path(temporary)
            extension = directory / "extension"
            extension.mkdir()
            key = json.loads((Path(__file__).resolve().parents[1] / "browser-extension/manifest.json").read_text())["key"]
            manifest = {"manifest_version": 3, "name": "Discard API isolation", "version": "1.0", "key": key, "permissions": ["tabs"]}
            (extension / "manifest.json").write_text(json.dumps(manifest))
            (extension / "controller.html").write_text("<!doctype html><title>Discard isolation controller</title>")
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(directory / "profile"), executable_path=args.browser,
                    headless=False, ignore_default_args=["--disable-extensions"],
                    args=["--disable-gpu", "--disable-extensions-except=" + str(extension), "--load-extension=" + str(extension)],
                )
                report["browser_version"] = context.browser.version
                setup = context.new_page()
                setup.goto("chrome://extensions/")
                toggle = setup.locator("#devMode")
                toggle.wait_for(state="visible")
                if not toggle.evaluate("element=>element.checked"):
                    toggle.click()
                assert toggle.evaluate("element=>element.checked")
                setup.close()
                controller = context.new_page()
                controller.goto("chrome-extension://" + extension_id(manifest) + "/controller.html")
                page = context.new_page()
                page.goto("http://127.0.0.1:" + str(server.server_port))
                tab = controller.evaluate("chrome.tabs.query({}).then(items=>items.find(tab=>tab.title==='Discard isolation fixture'))")
                controller.evaluate("id=>chrome.tabs.update(id,{active:true})", controller.evaluate("chrome.tabs.getCurrent().then(tab=>tab.id)"))
                report["discard_result"] = controller.evaluate("id=>chrome.tabs.discard(id)", tab["id"])
                assert report["discard_result"]["discarded"]
                controller.wait_for_timeout(1500)
                assert context.browser.is_connected()
                report["discard_observed"] = controller.evaluate("id=>chrome.tabs.get(id)", tab["id"])
                assert report["discard_observed"]["discarded"]
                controller.evaluate("id=>chrome.tabs.update(id,{active:true})", tab["id"])
                controller.wait_for_timeout(1500)
                report["restore_observed"] = controller.evaluate("id=>chrome.tabs.get(id)", tab["id"])
                assert not report["restore_observed"]["discarded"]
                report["minimal_discard_restore"] = "PASS"
                context.close()
    except Exception as error:
        report["minimal_discard_restore"] = "FAIL"
        report["failure"] = str(error)
        raise
    finally:
        server.shutdown()
        server.server_close()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
