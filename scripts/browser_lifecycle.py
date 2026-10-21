"""Keep browser acceptance failures distinct from best-effort cleanup."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import time


class BrowserClosed(RuntimeError):
    """A required acceptance operation lost its browser or controller page."""


def browser_is_open(context, page=None):
    browser = context.browser
    return bool(
        browser
        and browser.is_connected()
        and (page is None or not page.is_closed())
    )


def browser_call(context, page, label, operation):
    """Require a live browser, including a disconnect racing the operation.

    Required checks raise on teardown. Returning a default here would let a
    crashed browser skip acceptance assertions and incorrectly pass CI.
    """
    if not browser_is_open(context, page):
        raise BrowserClosed(f"{label}: browser or controller page is closed")
    try:
        return operation()
    except Exception as error:
        if not browser_is_open(context, page) or (
            "Target page, context or browser has been closed" in str(error)
        ):
            raise BrowserClosed(f"{label}: browser closed during the operation") from error
        raise


def browser_cleanup(context, page, label, operation, report):
    """Skip unavailable targets without hiding a failure on a live browser."""
    try:
        browser_call(context, page, label, operation)
    except BrowserClosed as error:
        report.setdefault("cleanup_skipped", []).append(
            {"operation": label, "reason": str(error)}
        )
    except Exception as error:
        report.setdefault("cleanup_errors", []).append(
            {"operation": label, "error": str(error)}
        )
        return False
    return True


def browser_launch_args(extension_path):
    return [
        "--disable-dev-shm-usage",
        "--disable-extensions-except=" + str(extension_path),
        "--load-extension=" + str(extension_path),
        "--autoplay-policy=no-user-gesture-required",
        "--disable-background-networking",
        "--disable-features=OptimizationGuideModelDownloading,OptimizationHints,msForceBrowserSignIn,msEdgeUpdateLaunchServicesPreferredVersion",
    ]


@contextmanager
def launch_browser_context(playwright, executable, profile, extension, log_path):
    """Use a normal Edge process and its supported CDP connection on Windows."""
    if sys.platform != "win32" or Path(executable).name.lower() != "msedge.exe":
        context = playwright.chromium.launch_persistent_context(
            str(profile), executable_path=executable, headless=False,
            chromium_sandbox=sys.platform == "win32", timeout=20000,
            ignore_default_args=["--disable-extensions"],
            viewport={"width": 1200, "height": 800},
            args=browser_launch_args(extension),
        )
        try:
            yield context
        finally:
            if browser_is_open(context):
                context.close()
        return

    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    browser = None
    with Path(log_path).open("wb") as log:
        process = subprocess.Popen(
            [str(executable), "--user-data-dir=" + str(profile),
             "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
             "--no-first-run", "--no-default-browser-check", "--window-size=1200,800",
             "--edge-skip-compat-layer-relaunch", "--disable-edgeupdater",
             *browser_launch_args(extension), "about:blank"],
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            endpoint_file = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise BrowserClosed(f"Edge exited during startup: {process.returncode}")
                if endpoint_file.exists():
                    endpoint = endpoint_file.read_text().splitlines()
                    if len(endpoint) >= 2:
                        break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Edge did not publish its local CDP endpoint")
                time.sleep(0.1)
            browser = playwright.chromium.connect_over_cdp(
                "ws://127.0.0.1:" + endpoint[0] + endpoint[1],
                timeout=20000,
            )
            context = browser.contexts[0]
            context.audial_browser_process = process
            yield context
        finally:
            if browser is not None and browser.is_connected():
                browser.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
