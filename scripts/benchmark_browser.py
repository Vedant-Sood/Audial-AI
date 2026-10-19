"""Compare the real page's transcript renderer, then sustain the updated view.

Uses generated caption text only. Measures DOM/layout/paint and browser memory,
not ASR accuracy or audio capture. No dataset or microphone is required.
"""

import argparse
import json
from pathlib import Path
import platform
import subprocess
import time
from urllib.parse import urlsplit

from app.services.browser import BrowserService
from app.utils.config import Settings


def run(browser_path, baseline, output, sustained_seconds):
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[1]
    service = BrowserService(settings=Settings())
    service.start()
    report = {
        "scope": "Actual page DOM/layout/paint with generated captions; not ASR, tab capture or inference",
        "platform": platform.platform(),
        "baseline_commit": baseline,
        "batches": 5,
        "captions_per_batch": 500,
    }
    sources = {}
    for name in [
        "index.html",
        "app.js",
        "styles.css",
        "light-box.js",
        "capture.js",
        "emotion.js",
        "isl-playback.js",
        "pcm-worklet.js",
    ]:
        sources[name] = subprocess.check_output(
            ["git", "show", f"{baseline}:browser/{name}"], cwd=root
        )
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            for label in ["before", "after"]:
                browser = playwright.chromium.launch(
                    executable_path=browser_path, headless=True, args=["--no-sandbox"]
                )
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(request):
                    name = (
                        urlsplit(request.request.url).path.rsplit("/", 1)[-1]
                        or "index.html"
                    )
                    if label == "before" and name in sources:
                        body = sources[name]
                    elif name == "app.js":
                        body = (root / "browser/app.js").read_bytes()
                    else:
                        request.continue_()
                        return
                    if name == "app.js":
                        body += (
                            b"\nglobalThis.__audialBenchmarkAppend = appendCaption;\n"
                        )
                    content_type = (
                        "text/javascript"
                        if name.endswith(".js")
                        else "text/css"
                        if name.endswith(".css")
                        else "text/html"
                    )
                    request.fulfill(status=200, body=body, content_type=content_type)

                page.route(service.url + "/**", route)
                page.goto(service.url)
                page.wait_for_function("typeof __audialBenchmarkAppend === 'function'")
                page.locator("#auto-sign").uncheck()
                page.wait_for_timeout(300)
                session = context.new_cdp_session(page)
                session.send("Performance.enable")

                def sample():
                    session.send("HeapProfiler.collectGarbage")
                    metrics = {
                        m["name"]: m["value"]
                        for m in session.send("Performance.getMetrics")["metrics"]
                    }
                    return {
                        "js_heap_used_bytes": metrics["JSHeapUsedSize"],
                        **session.send("Memory.getDOMCounters"),
                        "visible_rows": page.locator("#transcript > li").count(),
                    }

                start = sample()

                def batch(index):
                    return page.evaluate(
                        """async index => {
                        await new Promise(requestAnimationFrame);
                        const started = performance.now();
                        for (let i=0;i<500;i++) __audialBenchmarkAppend({start:index*500+i,end:index*500+i+1,
                            speaker:'Speaker 1',text:'Generated rendering workload caption '+(index*500+i)+'. The complete words remain readable.'});
                        await new Promise(requestAnimationFrame);
                        document.querySelector('#transcript').getBoundingClientRect();
                        await new Promise(requestAnimationFrame);
                        return (performance.now()-started)/1000;
                    }""",
                        index,
                    )

                timings = [batch(i) for i in range(5)]
                measured = {
                    "browser_version": browser.version,
                    "batch_seconds": timings,
                    "before": start,
                    "after": sample(),
                    "page_errors": errors,
                }
                if label == "after":
                    sustained = []
                    began = time.monotonic()
                    index = 5
                    while time.monotonic() - began < sustained_seconds:
                        seconds = batch(index)
                        if index % 10 == 5:
                            sustained.append(
                                {
                                    "elapsed_seconds": time.monotonic() - began,
                                    "captions_sent": (index + 1) * 500,
                                    "batch_seconds": seconds,
                                    **sample(),
                                }
                            )
                            print(json.dumps(sustained[-1]), flush=True)
                        index += 1
                        page.wait_for_timeout(1000)
                    measured["sustained"] = {
                        "duration_seconds": time.monotonic() - began,
                        "captions_sent": index * 500,
                        "samples": sustained,
                        "final": sample(),
                    }
                    page.screenshot(
                        path=str(output / "browser-sustained.png"), full_page=True
                    )
                if errors:
                    raise AssertionError(errors)
                report[label] = measured
                browser.close()
    finally:
        service.stop()
    (output / "browser-performance.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument(
        "--baseline", default="65f6bc0609b4e7dfde31873ed5d18d8ea3e46368"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sustained-seconds", type=int, default=180)
    args = parser.parse_args()
    run(args.browser, args.baseline, args.output, args.sustained_seconds)


if __name__ == "__main__":
    main()
