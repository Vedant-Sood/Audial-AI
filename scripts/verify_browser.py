"""Exercise actual Chromium extension discovery/capture through native messaging.

Uses two generated tone tabs to verify source identity and PCM transport, not ASR
accuracy. No physical microphone is opened. Linux headful capture needs DISPLAY
and xdotool. Windows uses --native-host <installed AccessibilityAIWorker.exe>.
"""

import argparse
import base64
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
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
from scripts.browser_lifecycle import (
    BrowserClosed, browser_call, browser_cleanup, browser_is_open,
    launch_browser_context,
)
from scripts.package_extension import build
from scripts.browser_discard import detached_discard_restore


def wait_until(predicate, timeout=20, pump=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        if pump is None:
            time.sleep(0.1)
        else:
            # Playwright's synchronous API dispatches browser events only
            # while an API call runs. Keep newly attached MV3 targets moving
            # while the native host independently updates desktop state.
            pump(100)
    raise AssertionError("Browser acceptance condition timed out")


class ToolbarPopup:
    """Drive the real toolbar target when Playwright omits it from pages."""

    def __init__(self, cdp, target, pump):
        self.cdp, self.target, self.pump = cdp, target, pump
        self.responses = {}
        self.counter = 0
        self.session = cdp.send("Target.attachToTarget", {"targetId": target, "flatten": False})["sessionId"]
        def receive(event):
            if event.get("sessionId") == self.session:
                message = json.loads(event["message"])
                if "id" in message:
                    self.responses[message["id"]] = message
        cdp.on("Target.receivedMessageFromTarget", receive)

    def send(self, method, params=None):
        self.counter += 1
        number = self.counter
        self.cdp.send("Target.sendMessageToTarget", {
            "sessionId": self.session,
            "message": json.dumps({"id": number, "method": method, "params": params or {}}),
        })
        deadline = time.monotonic() + 10
        while number not in self.responses:
            if time.monotonic() > deadline:
                raise AssertionError("Toolbar target timed out: " + method)
            self.pump(25)
        response = self.responses.pop(number)
        if "error" in response:
            raise AssertionError("Toolbar target: " + str(response["error"]))
        return response.get("result", {})

    def evaluate(self, expression):
        response = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if response.get("exceptionDetails"):
            raise AssertionError("Toolbar script failed: " + str(response["exceptionDetails"]))
        return response.get("result", {}).get("value")

    def click(self, selector):
        deadline = time.monotonic() + 10
        while True:
            rectangle = self.evaluate("""(() => {
              const element = document.querySelector(""" + json.dumps(selector) + """);
              const connected = document.querySelector('#connection')?.textContent.startsWith('Connected');
              if (!connected || !element || element.disabled) return null;
              const r = element.getBoundingClientRect();
              return {x:r.x+r.width/2,y:r.y+r.height/2};
            })()""")
            if rectangle:
                break
            if time.monotonic() > deadline:
                raise AssertionError("Toolbar control is unavailable: " + selector + "; " + str(self.evaluate("document.body.innerText")))
            self.pump(50)
        # Actual browser input dispatch preserves trusted click behavior. The
        # OS toolbar invocation above already granted activeTab for this source.
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", **rectangle})
        for kind in ["mousePressed", "mouseReleased"]:
            self.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, **rectangle})

    def screenshot(self, path):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        Path(path).write_bytes(base64.b64decode(result["data"]))

    def close(self):
        try:
            self.cdp.send("Target.closeTarget", {"targetId": self.target})
        finally:
            self.cdp.detach()


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
        # A normal extension document supplies Chrome's real tabs API without
        # pinning a short-lived MV3 worker object. Capture still requires the
        # separate OS toolbar invocation and real popup below.
        controller_name = "acceptance-control.html"
        (Path(extension["path"]) / controller_name).write_text(
            "<!doctype html><title>Audial browser acceptance controller</title>"
        )
        controller_url = "chrome-extension://" + extension["id"] + "/" + controller_name
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
        failures = []
        try:
            with (
                sync_playwright() as playwright,
                launch_browser_context(
                    playwright, args.browser, profile_path, extension["path"],
                    args.output / "browser-process.txt",
                ) as context,
            ):
                report["lifecycle_events"] = []
                stage = "initialization"
                def record_lifecycle(event):
                    report["lifecycle_events"].append({"event": event, "stage": stage})
                context.on("close", lambda: record_lifecycle("context closed"))
                context.browser.on("disconnected", lambda: record_lifecycle("browser disconnected"))
                report["browser_version"] = (
                    context.browser.version if context.browser else args.browser
                )
                # Use the real supported Developer mode control in this
                # disposable browser profile. Managed restrictions still win.
                setup = context.new_page()
                setup.set_viewport_size({"width": 1200, "height": 800})
                setup.goto("edge://extensions/" if "msedge" in args.browser.lower() else "chrome://extensions/")
                developer_mode = setup.get_by_label(re.compile("developer mode", re.I)).filter(visible=True).first
                try:
                    developer_mode.wait_for(state="visible", timeout=10000)
                except Exception:
                    report["extension_setup_page"] = setup.locator("body").inner_text()[:4000]
                    setup.screenshot(path=str(args.output / "extension-setup-failure.png"))
                    raise
                enabled = "element => element.checked === true || element.checked === 'true' || element.getAttribute('aria-checked') === 'true' || element.getAttribute('aria-pressed') === 'true'"
                if not developer_mode.evaluate(enabled):
                    if developer_mode.evaluate("element => element.disabled || element.getAttribute('aria-disabled') === 'true'"):
                        raise AssertionError("Developer mode is unavailable under browser policy")
                    developer_mode.click()
                wait_until(
                    lambda: developer_mode.evaluate(enabled),
                    pump=setup.wait_for_timeout,
                )
                report["developer_mode"] = "PASS; enabled through the real browser extension setup UI"
                setup.close()
                first = context.new_page()
                first.on("close", lambda: record_lifecycle("first tab closed"))
                first.goto(base + "/first")
                first.locator("#play").click()
                def wait(predicate, timeout=20):
                    def pump(milliseconds):
                        return browser_call(context, first, "acceptance wait", lambda: first.wait_for_timeout(milliseconds))
                    def observe():
                        return browser_call(context, first, "acceptance observation", predicate)
                    return wait_until(observe, timeout, pump)
                background_url = "chrome-extension://" + extension["id"] + "/service-worker.js"
                initial_background = next((item for item in context.service_workers if item.url == background_url), None)
                if initial_background is None:
                    initial_background = context.wait_for_event("serviceworker", predicate=lambda item: item.url == background_url)
                report["initial_background"] = initial_background.url
                worker = context.new_page()
                worker.goto(controller_url)
                with context.expect_page() as opened:
                    worker.evaluate(
                        "url => chrome.windows.create({url})", base + "/second"
                    )
                second = opened.value
                second.wait_for_load_state()
                second.locator("#play").click()
                wait(
                    lambda: any(
                        len(profile["tabs"]) >= 2
                        for profile in service.bridge.snapshot()["profiles"]
                    )
                )
                def tabs():
                    return [
                        tab
                        for profile in service.bridge.snapshot()["profiles"]
                        for tab in profile["tabs"]
                    ]
                wait(lambda: len({tab["window_id"] for tab in tabs()}) >= 2)
                report["real_tab_discovery"] = "PASS across two actual browser windows"
                def tab_id(page):
                    return worker.evaluate(
                        "url => chrome.tabs.query({}).then(items => items.find(tab => tab.url === url).id)",
                        page.url,
                    )
                second_id = tab_id(second)
                second.reload()
                second.locator("#play").click()
                assert tab_id(second) == second_id
                second.goto(base + "/navigated")
                second.goto(base + "/second")
                second.locator("#play").click()
                assert tab_id(second) == second_id
                report["reload_and_navigation_identity"] = (
                    "PASS; actual tab ID retained"
                )
                restricted = context.new_page()
                restricted.goto("chrome://settings/")
                restricted_id = tab_id(restricted)
                wait(
                    lambda: any(
                        tab["id"] == restricted_id and not tab["supported"]
                        for tab in tabs()
                    )
                )
                restricted.close()
                report["restricted_pages"] = "PASS using actual browser APIs"
                viewer = context.new_page()
                viewer.goto(service.url)
                viewer.locator("#browser-tabs option").nth(1).wait_for(state="attached")
                viewer.screenshot(
                    path=str(args.output / "browser-with-real-tabs.png"), full_page=True
                )

                def invoke(page):
                    page.bring_to_front()
                    if sys.platform == "win32":
                        # Renderer events do not grant activeTab; invoke the
                        # real toolbar action through the OS shortcut.
                        import ctypes
                        from ctypes import wintypes

                        user32 = ctypes.windll.user32
                        user32.GetForegroundWindow.restype = wintypes.HWND
                        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
                        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                        user32.IsWindowVisible.argtypes = [wintypes.HWND]
                        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                        user32.IsIconic.argtypes = [wintypes.HWND]
                        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                        matches = []
                        desired = page.title()
                        def title(handle):
                            text = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(handle) + 1)
                            user32.GetWindowTextW(handle, text, len(text))
                            return text.value
                        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                        @callback
                        def visit(handle, parameter):
                            if user32.IsWindowVisible(handle) and desired in title(handle):
                                matches.append(handle)
                            return True
                        user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
                        user32.EnumWindows(visit, 0)
                        if not matches:
                            raise AssertionError("No visible browser window for " + desired)
                        handle = matches[-1]
                        if user32.IsIconic(handle):
                            user32.ShowWindow(handle, 9)
                        user32.SetForegroundWindow(handle)
                        page.wait_for_timeout(250)
                        foreground = user32.GetForegroundWindow()
                        report.setdefault("window_focus", []).append({"requested": desired, "foreground": title(foreground), "matched": foreground == handle})
                        if foreground != handle:
                            raise AssertionError("Windows did not focus the actual browser window")
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
                    cdp = context.browser.new_browser_cdp_session()
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        for candidate in context.pages:
                            if candidate.url.endswith("/popup.html"):
                                candidate.wait_for_selector("#capture-current")
                                cdp.detach()
                                return candidate
                        targets = cdp.send("Target.getTargets")["targetInfos"]
                        popup_target = next((target for target in targets if target["url"] == "chrome-extension://" + extension["id"] + "/popup.html"), None)
                        if popup_target:
                            return ToolbarPopup(cdp, popup_target["targetId"], page.wait_for_timeout)
                        page.wait_for_timeout(100)
                    report["targets_after_toolbar_action"] = [
                        {key: target[key] for key in ["type", "url", "title"]}
                        for target in cdp.send("Target.getTargets")["targetInfos"]
                    ]
                    cdp.detach()
                    raise AssertionError(
                        "Browser toolbar action did not open its real popup"
                    )

                report["toolbar_commands"] = worker.evaluate("chrome.commands.getAll()")
                observed = []
                report["source_capture_and_switching"] = observed
                for source, expected in [(first, 440), (second, 1000)]:
                    popup = invoke(source)
                    popup.click("#capture-current")
                    expected_tab = tab_id(source)
                    wait(
                        lambda: service.bridge.owner is not None
                        and service.bridge.owner["tab_id"] == expected_tab,
                        timeout=25,
                    )
                    # A click starts an asynchronous source switch. Discard
                    # packets only after the desktop owns the requested tab.
                    packets.clear()
                    wait(lambda: any(np.max(np.abs(packet)) > 0.01 for packet in tuple(packets)), timeout=25)
                    pcm = [packet for packet in tuple(packets) if np.max(np.abs(packet)) > 0.01][-1]
                    spectrum = np.abs(np.fft.rfft(pcm))
                    frequency = float(np.argmax(spectrum) * 16000 / len(pcm))
                    observed.append(
                        {
                            "expected_hz": expected,
                            "received_hz": frequency,
                            "samples": len(pcm),
                            "expected_tab_id": expected_tab,
                            "actual_tab_id": service.bridge.owner["tab_id"],
                        }
                    )
                    assert abs(frequency - expected) < 10, (expected, frequency)
                    popup.screenshot(
                        path=str(args.output / f"extension-capturing-{expected}.png")
                    )
                    if expected == 1000:
                        popup.click("#stop-capture")
                        wait(lambda: service.bridge.owner is None)
                        assert not service.engine.running
                    popup.close()
                report["source_capture_and_switching"] = observed
                report["stop_and_release"] = "PASS"
                second.close()
                wait(
                    lambda: not any(
                        tab["id"] == second_id
                        for profile in service.bridge.snapshot()["profiles"]
                        for tab in profile["tabs"]
                    )
                )
                report["closed_tab_removal"] = "PASS"
                old_backgrounds = set(context.service_workers)
                old_controller = worker
                stage = "extension reload"
                try:
                    worker.evaluate("chrome.runtime.reload()")
                except Exception as error:
                    if not any(term in str(error).lower() for term in ["closed", "destroyed", "context invalidated"]):
                        raise
                worker = context.new_page()
                # Reload temporarily unregisters extension URLs and shortcuts.
                # Wait for the real document to become available before an OS
                # action; a key sent during that interval is simply lost.
                deadline = time.monotonic() + 15
                while True:
                    try:
                        worker.goto(controller_url)
                        worker.evaluate("chrome.runtime.id")
                        break
                    except Exception as error:
                        if time.monotonic() > deadline or not any(term in str(error) for term in ["ERR_BLOCKED_BY_CLIENT", "ERR_ABORTED", "context was destroyed"]):
                            try:
                                inspector = context.new_page()
                                inspector.goto("chrome://extensions/")
                                report["browser_extension_diagnostics"] = inspector.evaluate(
                                    """chrome.developerPrivate.getExtensionsInfo({includeDisabled:true,includeTerminated:true})
                                    .then(items=>items.map(({id,state,disableReasons,installWarnings,runtimeErrors,manifestErrors})=>
                                      ({id,state,disableReasons,installWarnings,runtimeErrors,manifestErrors})))"""
                                )
                            except Exception as diagnostic_error:
                                report["extension_diagnostic_error"] = str(diagnostic_error)
                            raise
                        first.wait_for_timeout(150)
                if not old_controller.is_closed():
                    old_controller.close()
                # A reloaded lazy worker may wait for an event. Opening the
                # actual toolbar is the supported user action that wakes it.
                popup = invoke(first)
                deadline = time.monotonic() + 20
                while not any(item not in old_backgrounds and item.url == background_url for item in context.service_workers):
                    if time.monotonic() > deadline:
                        raise AssertionError("Extension reload did not create a fresh background worker")
                    first.wait_for_timeout(100)
                wait(lambda: any(tab["id"] == tab_id(first) for tab in tabs()))
                report["extension_background_restart"] = (
                    "PASS; real extension reloaded and metadata restored"
                )
                popup.click("#capture-current")
                packets.clear()
                wait(lambda: packets, timeout=25)
                popup.close()
                service.stop()
                deadline = time.monotonic() + 20
                while worker.evaluate(
                    "chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']}).then(items=>items.length)"
                ):
                    if time.monotonic() > deadline:
                        raise AssertionError(
                            "Desktop disconnect did not release tab audio"
                        )
                    first.wait_for_timeout(100)
                report["desktop_disconnect_releases_audio"] = (
                    "PASS; actual tab stream and offscreen document stopped"
                )
                service = BrowserService(settings=Settings(device="cpu"))
                service.engine.manager.installed = lambda _: True
                service.engine.start = start
                service.engine.stop = stop
                service.start()
                wait(
                    lambda: any(tab["id"] == tab_id(first) for tab in tabs()),
                    timeout=25,
                )
                report["desktop_service_reconnection"] = (
                    "PASS; fresh bridge token/port, tab list restored automatically"
                )
                stage = "suspended tab creation"
                suspended = context.new_page()
                suspended.on("close", lambda: record_lifecycle("suspended tab target closed"))
                suspended.goto(base + "/suspended")
                suspended_id = tab_id(suspended)
                wait(lambda: any(tab["id"] == suspended_id for tab in tabs()))
                try:
                    stage = "discard"
                    if hasattr(context, "audial_browser_process"):
                        stage = "detach automation before discard"
                        detached_discard_restore(context, worker, suspended_id, report, tabs)
                        report["suspend_restore"] = "PASS using actual browser APIs and native bridge with CDP detached"
                    else:
                        verify_attached_discard(context, worker, suspended_id, report, wait, tabs)
                        suspended_id = report["discard_identity"]["after"]
                        report["suspend_restore"] = "PASS using actual browser APIs"
                except Exception as error:
                    failures.append("Tab suspension: " + str(error))
                    report["suspend_restore"] = {"status": "FAIL", "error": str(error)}
                    if isinstance(error, BrowserClosed):
                        report["browser_teardown"] = {"status": "FAIL", "stage": stage}
                    report["bridge_at_suspension_failure"] = service.bridge.snapshot()
                    if browser_is_open(context, worker):
                        try:
                            report["actual_tab_at_suspension_failure"] = browser_call(
                                context, worker, "suspended tab lookup",
                                lambda: worker.evaluate("id => chrome.tabs.get(id)", suspended_id),
                            )
                        except Exception as diagnostic_error:
                            report["suspension_diagnostic_error"] = str(diagnostic_error)
                finally:
                    if not browser_cleanup(
                        context, worker, "remove suspended tab",
                        lambda: worker.evaluate("id => chrome.tabs.remove(id)", report.get("discard_identity", {}).get("after", suspended_id)),
                        report,
                    ):
                        failures.append("Suspended-tab cleanup failed; see cleanup_errors")
                stage = "normal cleanup"
                if not browser_cleanup(context, None, "close browser context", context.close, report):
                    failures.append("Browser cleanup failed; see cleanup_errors")
                if failures:
                    raise AssertionError("; ".join(failures))
        except Exception as error:
            report["failure"] = str(error)
            raise
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


def verify_attached_discard(context, worker, suspended_id, report, wait, tabs):
    # A tab remains active in its own window even when another
    # window is focused. Discard requires a different active tab
    # in this exact window.
    discarded = browser_call(context, worker, "discard tab", lambda: worker.evaluate(
        """async id => {
          const tab = await chrome.tabs.get(id);
          const other = (await chrome.tabs.query({windowId:tab.windowId})).find(item=>item.id!==id)
            || await chrome.tabs.create({windowId:tab.windowId,url:'about:blank',active:false});
          await chrome.tabs.update(other.id,{active:true});
          return chrome.tabs.discard(id);
        }""",
        suspended_id,
    ))
    report["discard_result"] = {
        key: discarded.get(key) for key in ["id", "active", "discarded", "windowId", "status"]
    } if discarded else None
    assert discarded and discarded["discarded"], (
        "Browser declined the real discard request", discarded
    )
    # Chromium replaces the tab's WebContents when discarding;
    # the supported API can return a new tab ID. Observe that
    # actual identity and require removal of the superseded ID.
    previous_id, suspended_id = suspended_id, discarded["id"]
    report["discard_identity"] = {"before": previous_id, "after": suspended_id}
    wait(
        lambda: any(
            tab["id"] == suspended_id and tab["discarded"] for tab in tabs()
        ) and (previous_id == suspended_id or not any(tab["id"] == previous_id for tab in tabs()))
    )
    browser_call(context, worker, "restore discarded tab", lambda: worker.evaluate(
        "id => chrome.tabs.update(id,{active:true})", suspended_id
    ))
    wait(
        lambda: any(
            tab["id"] == suspended_id and not tab["discarded"]
            for tab in tabs()
        )
    )


if __name__ == "__main__":
    main()
