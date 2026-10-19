"""Inject OS device failures through real workers and assert visible recovery."""

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def test_microphone_permission_failure_releases_stream_and_reaches_the_interface(
    monkeypatch,
):
    import sounddevice

    closed = []

    class DeniedStream:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise PermissionError(
                "Microphone permission denied by Windows privacy settings"
            )

        def stop(self):
            raise RuntimeError("Stream did not start")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sounddevice, "InputStream", DeniedStream)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.settings.auto_sign = False
    try:
        window.engine.start("tone")
        window.engine.threads[0].join(10)
        window.poll()
        app.processEvents()
        assert closed == [True]
        assert not window.engine.running and window.engine.capture is None
        failures = [
            item
            for item in window.notifications.history.snapshot()
            if item["severity"] == "error"
        ]
        assert any(
            "Microphone permission denied" in item["message"]
            and item["action"] == "settings"
            for item in failures
        )
        assert window.notifications.cards
    finally:
        window.close()


def test_camera_unavailable_releases_pose_and_device_and_reaches_the_interface(
    monkeypatch,
):
    import cv2
    import app.video.pose

    released, closed = [], []

    class Pose:
        def __init__(self, *args):
            pass

        def close(self):
            closed.append(True)

    class Camera:
        def isOpened(self):
            return False

        def release(self):
            released.append(True)

    monkeypatch.setattr(app.video.pose, "PoseExtractor", Pose)
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: Camera())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    monkeypatch.setattr(
        window.manager, "installed", lambda name: name in {"hand-pose", "body-pose"}
    )
    try:
        window.camera.start()
        window.camera.thread.join(5)
        window.poll()
        app.processEvents()
        assert released == closed == [True]
        assert not window.camera.thread.is_alive()
        assert any(
            "Cannot open camera" in item["message"] and item["action"] == "settings"
            for item in window.notifications.history.snapshot()
        )
        assert window.notifications.cards
    finally:
        window.close()
