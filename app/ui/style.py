"""Consistent native controls with an intentional keyboard focus indicator."""

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyle,
    QWidget,
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
)


class FocusTracker(QObject):
    """Distinguish keyboard focus from pointer focus without removing either."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyboard_mode = False

    def eventFilter(self, target, event):
        if not isinstance(target, QWidget):
            return False
        focused = None
        if event.type() == QEvent.FocusIn:
            if event.reason() in {
                Qt.TabFocusReason,
                Qt.BacktabFocusReason,
                Qt.ShortcutFocusReason,
            }:
                self.keyboard_mode = True
            elif event.reason() == Qt.MouseFocusReason:
                self.keyboard_mode = False
            focused = self.keyboard_mode
        elif event.type() in {QEvent.FocusOut, QEvent.MouseButtonPress}:
            if event.type() == QEvent.MouseButtonPress:
                self.keyboard_mode = False
            focused = False
        elif event.type() == QEvent.KeyPress:
            self.keyboard_mode = True
            if target.hasFocus():
                focused = True
        if focused is not None and target.property("keyboardFocus") != focused:
            target.setProperty("keyboardFocus", focused)
            target.style().unpolish(target)
            target.style().polish(target)
            QWidget.update(target)
        return False


class AudialStyle(QProxyStyle):
    """Replace platform dotted frames; keyboard focus remains a solid ring."""

    def __init__(self):
        super().__init__("Fusion")

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PE_FrameFocusRect:
            if isinstance(
                widget,
                (
                    QAbstractButton,
                    QAbstractItemView,
                    QAbstractSpinBox,
                    QComboBox,
                    QLineEdit,
                    QPlainTextEdit,
                ),
            ):
                # These controls already have the stylesheet's outer ring.
                return
            if widget is not None and widget.property("keyboardFocus"):
                painter.save()
                painter.setPen(QPen(QColor("#a75b00"), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 4, 4)
                painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


def install_style(application=None):
    application = application or QApplication.instance()
    if application is None or getattr(application, "_audial_focus_tracker", None):
        return
    application.setStyle(AudialStyle())
    tracker = FocusTracker(application)
    application.installEventFilter(tracker)
    application._audial_focus_tracker = tracker
