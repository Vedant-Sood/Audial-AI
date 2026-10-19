"""Exercise actual Chromium extension discovery/capture through native messaging.

Uses two generated tone tabs to verify source identity and PCM transport, not ASR
accuracy. No physical microphone is opened. Linux headful capture needs DISPLAY
and xdotool. Windows uses --native-host <installed AccessibilityAIWorker.exe>.
"""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
from app.audio.capture import ExternalAudio
from app.services.browser import BrowserService
from app.utils.config import Settings
from scripts.package_extension import build


def wait_until(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Browser acceptance condition timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--native-host", type=Path)
    parser.add_argument("--xdotool", default="xdotool")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="audial-browser-") as temporary:
        directory = Path(temporary)
        os.environ["ACCESSIBILITY_AI_HOME"] = str(directory / "state")
        os.environ["XDG_CONFIG_HOME"] = str(directory / "config")
        extension = build(directory / "extension")
        profile_path = directory / "profile"
        if sys.platform == "win32":
            if args.native_host is None:
                raise ValueError(
                    "On Windows provide the installed native worker executable."
                )
            host_path = args.native_host.resolve()
        else:
            host_path = directory / "native-host"
            source = Path(__file__).resolve().parents[1] / "native_host.py"
            host_path.write_text(
                "#!/bin/sh\nexec "
                + shlex.quote(sys.executable)
                + " "
                + shlex.quote(str(source))
                + ' "$@"\n'
            )
            host_path.chmod(0o700)
        manifest = {
            "name": "org.audialai.bridge",
            "description": "Audial-AI acceptance test bridge",
            "path": str(host_path),
            "type": "stdio",
            "allowed_origins": ["chrome-extension://" + extension["id"] + "/"],
        }
        manifests = [
            profile_path / "NativeMessagingHosts",
            directory / "config/chromium/NativeMessagingHosts",
        ]
        for folder in manifests:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "org.audialai.bridge.json").write_text(json.dumps(manifest))
        registry_backup = []
        if sys.platform == "win32":
            import winreg

            for browser in ["Google\\Chrome", "Microsoft\\Edge"]:
                key_path = (
                    "Software\\"
                    + browser
                    + "\\NativeMessagingHosts\\org.audialai.bridge"
                )
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        previous = winreg.QueryValueEx(key, "")[0]
                except FileNotFoundError:
                    previous = None
                registry_backup.append((key_path, previous))
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(
                        key,
                        "",
                        0,
                        winreg.REG_SZ,
                        str(manifests[0] / "org.audialai.bridge.json"),
                    )
        packets = deque(maxlen=20)
        service = BrowserService(settings=Settings(device="cpu"))
        service.engine.manager.installed = lambda _: True

        def start(mode, source):
            assert source == "browser"
            service.engine.source = source
            service.engine.running = True
            service.engine.stop_requested.clear()
            capture = ExternalAudio()
            original = capture.feed

            def feed(audio, start_seconds=None):
                packets.append(audio.copy())
                return original(audio, start_seconds)

            capture.feed = feed
            service.engine.capture = capture

        def stop():
            service.engine.stop_requested.set()
            service.engine.running = False

        service.engine.start = start
        service.engine.stop = stop
        service.start()

        class TonePage(BaseHTTPRequestHandler):
            def do_GET(self):
                frequency = 440 if self.path == "/first" else 1000
                html = f"""<!doctype html><title>Audial source {frequency} Hz</title><button id="play">Play fixture tone</button><script>
document.querySelector('button').onclick=async()=>{{window.ctx=new AudioContext();window.osc=ctx.createOscillator();osc.frequency.value={frequency};osc.connect(ctx.destination);osc.start();await ctx.resume();}};
</script>""".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, *args):
                pass

        tone_server = ThreadingHTTPServer(("127.0.0.1", 0), TonePage)
        threading.Thread(target=tone_server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:" + str(tone_server.server_port)
        report = {
            "platform": platform.platform(),
            "scope": "Real extension/native-bridge PCM transport with generated tones; ASR model is replaced only for this transport test",
        }
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(profile_path),
                    executable_path=args.browser,
                    headless=False,
                    timeout=20000,
                    ignore_default_args=["--disable-extensions"],
                    viewport={"width": 1200, "height": 800},
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-extensions-except=" + extension["path"],
                        "--load-extension=" + extension["path"],
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-background-networking",
                    ],
                )
                report["browser_version"] = (
                    context.browser.version if context.browser else args.browser
                )
                first = context.new_page()
                first.goto(base + "/first")
                first.locator("#play").click()
                second = context.new_page()
                second.goto(base + "/second")
                second.locator("#play").click()
                wait_until(
                    lambda: any(
                        len(profile["tabs"]) >= 2
                        for profile in service.bridge.snapshot()["profiles"]
                    )
                )
                report["real_tab_discovery"] = "PASS"
                viewer = context.new_page()
                viewer.goto(service.url)
                viewer.wait_for_function(
                    "document.querySelector('#browser-tabs').options.length >= 2"
                )
                viewer.screenshot(
                    path=str(args.output / "browser-with-real-tabs.png"), full_page=True
                )

                def invoke(page):
                    page.bring_to_front()
                    if sys.platform == "win32":
                        # Renderer events do not grant activeTab; invoke the
                        # real toolbar action through the OS shortcut.
                        import ctypes

                        user32 = ctypes.windll.user32
                        for key in [0x11, 0x10, 0x59]:
                            user32.keybd_event(key, 0, 0, 0)
                        for key in [0x59, 0x10, 0x11]:
                            user32.keybd_event(key, 0, 2, 0)
                    else:
                        result = subprocess.run(
                            [
                                args.xdotool,
                                "search",
                                "--onlyvisible",
                                "--name",
                                page.title(),
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        window = result.stdout.splitlines()[-1]
                        subprocess.run(
                            [args.xdotool, "windowfocus", "--sync", window], check=True
                        )
                        subprocess.run(
                            [args.xdotool, "key", "--clearmodifiers", "ctrl+shift+y"],
                            check=True,
                        )
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        for candidate in context.pages:
                            if candidate.url.endswith("/popup.html"):
                                candidate.wait_for_selector("#capture-current")
                                return candidate
                        page.wait_for_timeout(100)
                    raise AssertionError(
                        "Browser toolbar action did not open its real popup"
                    )

                observed = []
                for source, expected in [(first, 440), (second, 1000)]:
                    packets.clear()
                    popup = invoke(source)
                    popup.locator("#capture-current").click()
                    wait_until(lambda: packets, timeout=25)
                    pcm = packets[-1]
                    spectrum = np.abs(np.fft.rfft(pcm))
                    frequency = float(np.argmax(spectrum) * 16000 / len(pcm))
                    assert abs(frequency - expected) < 10, (expected, frequency)
                    observed.append(
                        {
                            "expected_hz": expected,
                            "received_hz": frequency,
                            "samples": len(pcm),
                        }
                    )
                    popup.screenshot(
                        path=str(args.output / f"extension-capturing-{expected}.png")
                    )
                    popup.locator("#stop-capture").click()
                    wait_until(lambda: service.bridge.owner is None)
                    assert not service.engine.running
                    popup.close()
                report["source_capture_and_switching"] = observed
                report["stop_and_release"] = "PASS"
                second.close()
                wait_until(
                    lambda: not any(
                        "1000 Hz" in tab["title"]
                        for profile in service.bridge.snapshot()["profiles"]
                        for tab in profile["tabs"]
                    )
                )
                report["closed_tab_removal"] = "PASS"
                context.close()
        finally:
            service.stop()
            tone_server.shutdown()
            tone_server.server_close()
            if sys.platform == "win32":
                import winreg

                for key_path, previous in registry_backup:
                    if previous is None:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
                    else:
                        with winreg.CreateKey(
                            winreg.HKEY_CURRENT_USER, key_path
                        ) as key:
                            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous)
        (args.output / "extension-acceptance.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
