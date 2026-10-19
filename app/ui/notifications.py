"""Visible, nonmodal warnings and persistent failures with recovery actions."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.notifications import NoticeHistory


class NoticeCard(QFrame):
    dismissed = Signal()
    actionRequested = Signal(str)

    def __init__(self, notice, parent=None):
        super().__init__(parent)
        self.setObjectName("notice")
        self.setProperty("severity", notice.severity)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        text = QLabel(notice.message)
        text.setTextFormat(Qt.PlainText)
        text.setWordWrap(True)
        text.setAccessibleName(notice.severity.capitalize() + ": " + notice.message)
        layout.addWidget(text, 1)
        if notice.action:
            label = {
                "models": "Open setup",
                "settings": "Open settings",
                "diagnostics": "View diagnostics",
                "browser": "Reconnect browser",
            }.get(notice.action, "Resolve")
            action = QPushButton(label)
            action.clicked.connect(lambda: self.actionRequested.emit(notice.action))
            layout.addWidget(action)
        close = QPushButton("Dismiss")
        close.setAccessibleName("Dismiss " + notice.severity)
        close.clicked.connect(self.dismissed.emit)
        layout.addWidget(close)


class Notifications(QWidget):
    actionRequested = Signal(str)

    def __init__(self, parent=None, history=None):
        super().__init__(parent)
        self.history = history or NoticeHistory()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)
        self.cards = []
        self.unresolved = []
        self.overflow = QPushButton()
        self.overflow.clicked.connect(self.show_history)
        self.overflow.setVisible(False)
        self.layout.addWidget(self.overflow)
        self.toasts = []
        self.setVisible(False)
        self.history_window = None

    def publish(self, message, severity="warning", code=None, action=None):
        notice, fresh = self.history.publish(message, severity, code, action)
        if not fresh:
            return notice
        if severity == "error":
            self.unresolved.append(notice)
            self.unresolved = self.unresolved[-200:]
            card = NoticeCard(notice, self)
            card.notice = notice
            card.actionRequested.connect(self.actionRequested.emit)
            self.cards.append(card)
            self.layout.addWidget(card)
            card.dismissed.connect(lambda: self.remove_card(card))
            while len(self.cards) > 3:
                self.remove_card(self.cards[0], dismiss=False)
            self.update_overflow()
            self.setVisible(True)
        else:
            # A tool window is nonmodal and never steals keyboard focus.
            toast = QFrame(self.window(), Qt.ToolTip | Qt.FramelessWindowHint)
            toast.setObjectName("toast")
            toast.setAttribute(Qt.WA_ShowWithoutActivating)
            toast.setMaximumWidth(460)
            layout = QVBoxLayout(toast)
            card = NoticeCard(notice, toast)
            card.actionRequested.connect(self.actionRequested.emit)
            layout.addWidget(card)
            self.toasts.append(toast)

            def dismiss():
                if toast in self.toasts:
                    self.toasts.remove(toast)
                    toast.close()
                    toast.deleteLater()

            card.dismissed.connect(dismiss)
            while len(self.toasts) > 2:
                old = self.toasts.pop(0)
                old.close()
                old.deleteLater()
            toast.adjustSize()
            owner = self.window()
            point = owner.mapToGlobal(owner.rect().topRight())
            toast.move(point.x() - toast.width() - 24, point.y() + 72)
            toast.show()
            QTimer.singleShot(7000, self, dismiss)
        if self.history_window and self.history_window.isVisible():
            self.update_history()
        return notice

    def remove_card(self, card, dismiss=True):
        if dismiss and card.notice in self.unresolved:
            self.unresolved.remove(card.notice)
        if card in self.cards:
            self.cards.remove(card)
            self.layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.update_overflow()

    def update_overflow(self):
        remaining = max(0, len(self.unresolved) - len(self.cards))
        self.overflow.setText(f"{remaining} earlier unresolved failure(s) · view notification history")
        self.overflow.setVisible(remaining > 0)
        self.setVisible(bool(self.unresolved))

    def show_history(self):
        if self.history_window is None:
            self.history_window = QDialog(self.window())
            self.history_window.setWindowTitle("Audial-AI · notification history")
            self.history_window.resize(700, 460)
            layout = QVBoxLayout(self.history_window)
            self.history_text = QPlainTextEdit()
            self.history_text.setReadOnly(True)
            self.history_text.setAccessibleName("Recent warnings and failures")
            layout.addWidget(self.history_text)
            acknowledge = QPushButton("Acknowledge all current alerts")
            acknowledge.clicked.connect(self.acknowledge)
            layout.addWidget(acknowledge)
        self.update_history()
        self.history_window.show()
        self.history_window.raise_()

    def acknowledge(self):
        self.unresolved.clear()
        for card in self.cards.copy():
            self.remove_card(card)
        self.update_overflow()

    def update_history(self):
        self.history_text.setPlainText(
            "\n\n".join(
                f"{item['created']}  {item['severity'].upper()} · {item['count']} occurrence(s)\n{item['message']}"
                for item in reversed(self.history.snapshot())
            )
            or "No warnings or failures in this session."
        )
