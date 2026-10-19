"""Native UI interaction and screenshot review without starting capture."""

import argparse
import json
from pathlib import Path
import platform
import tempfile
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audial-ui-") as directory:
        os.environ["ACCESSIBILITY_AI_HOME"] = directory
        from PySide6.QtWidgets import QApplication, QPushButton
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from app.ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow(auto_setup=False)
        window.show()
        report = {
            "platform": platform.platform(),
            "qt_platform": app.platformName(),
            "capture_started": False,
            "views": [],
        }
        try:
            for width, height in [(1160, 800), (900, 640)]:
                window.resize(width, height)
                for row in [0, 1, 3, 4, 5, 7]:
                    window.nav.setCurrentRow(row)
                    QTest.qWait(80)
                    app.processEvents()
                    name = f"desktop-{width}-{row}.png"
                    assert window.grab().save(str(args.output / name))
                    report["views"].append(
                        {
                            "image": name,
                            "page": window.TITLES[row],
                            "size": [window.width(), window.height()],
                        }
                    )
            window.nav.setCurrentRow(0)
            window.resize(1160, 800)
            primary = next(
                button
                for button in window.stack.currentWidget().findChildren(QPushButton)
                if button.text() == "Open conversation"
            )
            QTest.mousePress(primary, Qt.LeftButton)
            app.processEvents()
            assert not primary.property("keyboardFocus")
            window.grab().save(str(args.output / "desktop-pointer-pressed.png"))
            QTest.mouseRelease(primary, Qt.LeftButton)
            window.nav.setCurrentRow(0)
            primary.setFocus(Qt.TabFocusReason)
            QTest.keyClick(primary, Qt.Key_Tab)
            app.processEvents()
            assert app.focusWidget().property("keyboardFocus")
            window.grab().save(str(args.output / "desktop-keyboard-focus.png"))
            for message in [
                "Model setup failed. Open Setup & models to Retry.",
                "Microphone permission denied. Review Windows privacy settings.",
                "Camera unavailable. Select an available camera in Settings.",
                "Browser extension disconnected. Reconnect its toolbar action.",
            ]:
                window.engine.emit("error", message)
            window.poll()
            app.processEvents()
            assert len(window.notifications.cards) == 3
            assert window.notifications.overflow.isVisible()
            window.grab().save(str(args.output / "desktop-persistent-errors.png"))
            window.notifications.show_history()
            window.notifications.history_window.grab().save(
                str(args.output / "desktop-notification-history.png")
            )
            window.notifications.history_window.close()
            report["pointer_pressed_and_keyboard_focus"] = (
                "PASS; screenshots require visual review"
            )
            report["persistent_alerts_and_history"] = (
                "PASS; four injected worker errors, no physical-device validation claim"
            )
            assert not window.engine.running
        finally:
            window.close()
            app.processEvents()
        (args.output / "ui-acceptance.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
