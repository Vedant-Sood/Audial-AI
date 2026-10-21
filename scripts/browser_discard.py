"""Check real tab discard without keeping a debugger attached to the victim."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time

from scripts.browser_lifecycle import BrowserClosed, browser_call


def detached_discard_restore(context, controller, tab_id, report, snapshot=None):
    """Require actual Chrome API results and, optionally, native bridge updates.

    Older Chromium/Edge versions crash when a debugged WebContents is discarded.
    Schedule the real extension API exercise, detach the CDP client, and receive
    its observations through a private loopback endpoint. No browser assertion
    is skipped, and a missing callback or exited browser remains a failure.
    """
    token = secrets.token_urlsafe(32)
    finished = threading.Event()
    errors = []
    phases = []
    origin = "chrome-extension://" + browser_call(
        context, controller, "observe extension identity",
        lambda: controller.evaluate("chrome.runtime.id"),
    )

    class Observer(BaseHTTPRequestHandler):
        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(200, {})

        def do_POST(self):
            if self.path != "/" + token or self.headers.get("Origin") != origin:
                self.reply(403, {"ok": False})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                assert 0 < length <= 16384, "Invalid observation size"
                observation = json.loads(self.rfile.read(length))
                phase = observation["phase"]
                if phase == "failure":
                    raise AssertionError(observation["error"])
                if phase == "discarded":
                    assert not phases, "Discard must be the first observation"
                    tab = observation["tab"]
                    assert tab["discarded"] is True and not tab["active"], tab
                    assert observation["previous_id"] == tab_id
                    report["discard_result"] = tab
                    report["discard_identity"] = {"before": tab_id, "after": tab["id"]}
                    report["discard_observed"] = observation["observed"]
                    assert observation["observed"]["id"] == tab["id"]
                    assert observation["observed"]["discarded"] is True
                elif phase == "restored":
                    assert phases == ["discarded"], "Restore must follow discard"
                    tab = observation["tab"]
                    assert tab["id"] == report["discard_identity"]["after"]
                    assert tab["discarded"] is False and tab["active"], tab
                    report["restore_observed"] = tab
                elif phase == "complete":
                    assert phases == ["discarded", "restored"]
                    assert observation["removed"] is True
                else:
                    raise AssertionError("Unknown discard observation")

                if snapshot is not None and phase != "complete":
                    deadline = time.monotonic() + 20
                    while True:
                        tabs = snapshot()
                        current = next((item for item in tabs if item["id"] == tab["id"]), None)
                        superseded = tab_id != tab["id"] and any(item["id"] == tab_id for item in tabs)
                        if current and current["discarded"] == tab["discarded"] and not superseded:
                            report.setdefault("bridge_discard_observations", {})[phase] = current
                            break
                        if time.monotonic() >= deadline:
                            raise AssertionError("Native bridge did not observe " + phase + " tab identity/state")
                        time.sleep(0.05)
                phases.append(phase)
                self.reply(200, {"ok": True})
                if phase == "complete":
                    finished.set()
            except Exception as error:
                errors.append(str(error))
                self.reply(400, {"ok": False, "error": str(error)})
                finished.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Observer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/{token}"
    try:
        browser_call(context, controller, "schedule real discard/restore", lambda: controller.evaluate(
            """({id, endpoint}) => {
              const send = async data => {
                const response = await fetch(endpoint, {method:'POST', body:JSON.stringify(data)});
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || 'Observation rejected');
              };
              setTimeout(async () => {
                try {
                  const source = await chrome.tabs.get(id);
                  const other = (await chrome.tabs.query({windowId:source.windowId})).find(tab=>tab.id!==id)
                    || await chrome.tabs.create({windowId:source.windowId,url:'about:blank',active:false});
                  await chrome.tabs.update(other.id, {active:true});
                  const tab = await chrome.tabs.discard(source.id);
                  const observed = await chrome.tabs.get(tab.id);
                  await send({phase:'discarded', previous_id:id, tab, observed});
                  await chrome.tabs.update(tab.id, {active:true});
                  let restored;
                  for (let i=0; i<100; i++) {
                    restored = await chrome.tabs.get(tab.id);
                    if (!restored.discarded) break;
                    await new Promise(resolve => setTimeout(resolve, 100));
                  }
                  await send({phase:'restored', tab:restored});
                  await chrome.tabs.remove(tab.id);
                  let removed = false;
                  try { await chrome.tabs.get(tab.id); } catch { removed = true; }
                  await send({phase:'complete', removed});
                } catch (error) {
                  await send({phase:'failure', error:String(error)}).catch(()=>{});
                }
              }, 1500);
            }""", {"id": tab_id, "endpoint": endpoint},
        ))
        report["discard_automation"] = "CDP detached before real extension discard/restore; private loopback observations"
        browser_call(context, controller, "detach automation before discard", context.browser.close)
        deadline = time.monotonic() + 55
        while not finished.wait(0.1):
            process = context.audial_browser_process
            if process.poll() is not None:
                raise BrowserClosed(f"Edge exited during uninstrumented discard: {process.returncode}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Real browser discard/restore observations were not completed")
        if errors:
            raise AssertionError("; ".join(errors))
        assert phases == ["discarded", "restored", "complete"], phases
        assert context.audial_browser_process.poll() is None, "Edge exited after discard/restore"
    finally:
        server.shutdown()
        server.server_close()
