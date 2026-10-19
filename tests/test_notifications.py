from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from app.services.notifications import NoticeHistory
from app.ui.notifications import Notifications
from app.ui.style import install_style


def test_repeated_worker_failures_are_counted_without_alert_spam():
    now = [0.0]
    history = NoticeHistory(limit=3, clock=lambda: now[0], persist=False)
    first, fresh = history.publish("Microphone permission denied", "error", "microphone")
    assert fresh
    second, fresh = history.publish("Microphone permission denied", "error", "microphone")
    assert not fresh and first is second and second.count == 2
    now[0] = 21
    assert history.publish("Microphone permission denied", "error", "microphone")[1]
    for i in range(20):
        history.publish(f"Device failure {i}", "error")
    assert len(history.items) == len(history.recent) == 3


def test_disk_failure_does_not_swallow_the_visible_notification(monkeypatch):
    def disk_full(*args):
        raise OSError("No space left on device")
    monkeypatch.setattr("app.services.notifications.atomic_json", disk_full)
    history = NoticeHistory()
    notice, fresh = history.publish("Model download failed", "error", action="models")
    assert fresh and notice.message == "Model download failed"
    assert history.persistence_error == "No space left on device"


def test_failures_remain_visible_and_offer_a_recovery_action():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    notifications = Notifications(owner, NoticeHistory(persist=False))
    owner.show()
    actions = []
    notifications.actionRequested.connect(actions.append)
    notifications.publish("Caption model missing", "error", action="models")
    app.processEvents()
    assert notifications.isVisible() and len(notifications.cards) == 1
    card = notifications.cards[0]
    button = next(b for b in card.findChildren(QPushButton) if b.text() == "Open setup")
    QTest.mouseClick(button, Qt.LeftButton)
    assert actions == ["models"]
    notifications.publish("Caption model missing", "error", action="models")
    assert len(notifications.cards) == 1
    assert notifications.history.snapshot()[0]["count"] == 2
    notifications.show_history()
    assert "2 occurrence(s)" in notifications.history_text.toPlainText()
    notifications.history_window.close()
    owner.close()


def test_keyboard_focus_is_visible_without_pointer_focus_artifacts():
    app = QApplication.instance() or QApplication([])
    install_style(app)
    parent = QWidget()
    layout = QVBoxLayout(parent)
    first, second = QPushButton("First"), QPushButton("Second")
    layout.addWidget(first)
    layout.addWidget(second)
    parent.show()
    QTest.mouseClick(first, Qt.LeftButton)
    assert not first.property("keyboardFocus")
    QTest.keyClick(first, Qt.Key_Tab)
    app.processEvents()
    assert second.hasFocus() and second.property("keyboardFocus")
    QTest.mouseClick(second, Qt.LeftButton)
    assert not second.property("keyboardFocus")
    parent.close()
