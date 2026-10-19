"""Measure settled caption rendering against an explicit Git baseline.

python -m scripts.benchmark_ui --baseline-ref 65f6bc0 --output artifacts/caption-benchmark.json
Each variant runs in a fresh process, with the same visible panel and workload.
The full transcript is retained. The result includes the bounded display count.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def measure(module_path=None):
    import psutil
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app.storage.transcript import Caption, Session

    if module_path:
        spec = importlib.util.spec_from_file_location(
            "benchmark_baseline_widgets", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        panel_type = module.CaptionPanel
    else:
        from app.ui.widgets import CaptionPanel

        panel_type = CaptionPanel
    app = QApplication([])
    panel = panel_type()
    panel.resize(760, 480)
    panel.show()
    app.processEvents()
    process = psutil.Process()
    session = Session()
    batches = []
    memory = []
    for batch in range(5):
        started = time.perf_counter()
        for i in range(500):
            n = batch * 500 + i
            caption = Caption(
                n,
                n + 0.8,
                "Representative caption for sustained rendering",
                "Speaker 1",
                0.8,
            )
            session.add(caption)
            panel.append_caption(session, caption)
        # Complete all batched layouts, paint and deferred scrolling. The final
        # visualItemRect forces geometry even if a platform delays a layout.
        for _ in range(20):
            app.processEvents()
        panel.lines.visualItemRect(panel.lines.item(panel.lines.count() - 1))
        QTest.qWait(5)
        batches.append(time.perf_counter() - started)
        memory.append(process.memory_info().rss)
    result = {
        "batch_seconds": batches,
        "rss_bytes": memory,
        "rendered_rows": panel.lines.count(),
        "retained_captions": len(session.captions),
    }
    assert len(session.captions) == 2500
    panel.close()
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--module-path")
    args = parser.parse_args()
    if args.measure:
        measure(args.module_path)
        return
    result = {
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "workload": "5 batches of 500 captions on a visible 760x480 panel; settle layout and paint after each batch",
    }
    with tempfile.TemporaryDirectory() as directory:
        variants = [("after", None)]
        if args.baseline_ref:
            baseline = Path(directory) / "baseline_widgets.py"
            code = subprocess.check_output(
                ["git", "show", args.baseline_ref + ":app/ui/widgets.py"]
            )
            baseline.write_bytes(code)
            variants.insert(0, ("before", str(baseline)))
            result["baseline_commit"] = subprocess.check_output(
                ["git", "rev-parse", args.baseline_ref], text=True
            ).strip()
        for name, path in variants:
            command = [sys.executable, "-m", "scripts.benchmark_ui", "--measure"]
            if path:
                command += ["--module-path", path]
            completed = subprocess.run(
                command, check=True, text=True, capture_output=True
            )
            result[name] = json.loads(completed.stdout.strip().splitlines()[-1])
            print(name, json.dumps(result[name]), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
