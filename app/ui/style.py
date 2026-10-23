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


WATCHED = "audialFocusWatched"


def _in_web_view(widget):
    while widget is not None:
        if widget.inherits("QWebEngineView"):
            return True
        widget = widget.parentWidget()
    return False


class FocusTracker(QObject):
    """Distinguish keyboard focus from pointer focus without removing either.

    It starts as an application-wide event filter. A Python filter on the whole application
    crashes PySide once a QtWebEngine view (the Kandha window) runs in the same process, because
    the view's internal QtQuick objects then pass through Python; so before a web view is created,
    watch_widgets_only() swaps it for filters on the application's own widgets. Web views keep
    their own focus styling and are never watched.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyboard_mode = False
        self.application_wide = False

    def watch_widgets_only(self, application):
        if not self.application_wide:
            return
        application.removeEventFilter(self)
        self.application_wide = False
        for widget in application.topLevelWidgets():
            self.watch(widget)
        application.focusChanged.connect(self.focus_changed)

    def watch(self, widget):
        """Watch a widget and every child widget, now and as children are added."""
        if widget.inherits("QWebEngineView"):
            return
        widget.installEventFilter(self)
        if not widget.property(WATCHED):
            widget.setProperty(WATCHED, True)
        for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            self.watch(child)

    def focus_changed(self, old, new):
        # A window this tracker has not seen yet (a dialog or a new top-level window) is
        # watched when it first takes focus; its later focus changes then come through eventFilter.
        if new is None or new.property(WATCHED) or _in_web_view(new):
            return
        window = new.window()
        self.watch(window)
        # Qt flags the window when this focus change came from Tab or a shortcut
        if window.testAttribute(Qt.WA_KeyboardFocusChange):
            self.keyboard_mode = True
        self.mark(new, self.keyboard_mode)

    def mark(self, target, focused):
        if target.property("keyboardFocus") != focused:
            target.setProperty("keyboardFocus", focused)
            target.style().unpolish(target)
            target.style().polish(target)
            QWidget.update(target)

    def eventFilter(self, target, event):
        if not isinstance(target, QWidget):
            return False
        if event.type() == QEvent.ChildPolished:
            # a child widget is about to be shown for the first time: watch it too
            child = event.child()
            if not self.application_wide and isinstance(child, QWidget):
                self.watch(child)
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
        if focused is not None:
            self.mark(target, focused)
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
    tracker.application_wide = True
    application._audial_focus_tracker = tracker


def prepare_for_web_view(application=None):
    """Call before creating a QtWebEngine view: keyboard focus styling then stops using an
    application-wide Python event filter, which would crash with the view (see FocusTracker)."""
    application = application or QApplication.instance()
    tracker = getattr(application, "_audial_focus_tracker", None) if application is not None else None
    if tracker is not None:
        tracker.watch_widgets_only(application)
