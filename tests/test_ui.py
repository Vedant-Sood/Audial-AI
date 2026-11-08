from types import SimpleNamespace

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.storage.transcript import Session, Caption
from PySide6.QtWidgets import QMessageBox


def test_all_pages_start_and_navigate():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    for index, title in enumerate(window.TITLES):
        window.nav.setCurrentRow(index)
        app.processEvents()
        assert window.heading.text() == title
    assert window.stack.count() == 13
    assert not window.engine.running
    window.close()


def test_open_session_survives_saving_and_list_refresh(monkeypatch):
    app = QApplication.instance() or QApplication([])
    target = Session(title="Saved target")
    target.add(Caption(0, 1, "Source transcript"))
    target.save()
    window = MainWindow()
    window.refresh_sessions()
    window.sessions_list.setCurrentRow(0)
    window.session = Session(title="Unsaved current")
    window.session.add(Caption(0, 1, "Current transcript"))
    window.session_dirty = True
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    def save_and_refresh():
        window.session.save()
        window.session_dirty = False
        window.refresh_sessions()
        return True
    monkeypatch.setattr(window, "save_session", save_and_refresh)
    window.open_session()
    assert window.session.id == target.id
    assert window.session.captions[0].text == "Source transcript"
    window.close()


class FakeKandha:
    """Stands in for KandhaWindow: close() hides it at once and starts stopping its page; stopped()
    is the page having stopped, when the real window emits closed."""

    def __init__(self, window, url=None, **options):
        self.window, self.closes, self.closing, self.shown = window, 0, False, 0
        self.closed = SimpleNamespace(connect=lambda slot: None)

    def close(self):
        self.closes += 1
        self.closing = True
        return True

    def stopped(self):
        self.window.kandha_closed()

    def show(self):
        self.shown += 1

    def raise_(self):
        pass


def test_closing_audial_ai_closes_kandha_first(monkeypatch):
    """Kandha's window closes with Audial-AI's (its page stops listening first), so the program can exit."""
    import app.ui.main_window as main_window
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    retries = []
    # the retry runs here rather than on a timer: spinning the event loop in this process is unsafe
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda *args: retries.append(args[-1]))
    kandha = window.kandha_window = FakeKandha(window)
    assert not window.close()
    assert window.isVisible() and kandha.closes == 1 and retries == [window.close]
    # Kandha's page is still stopping: Audial-AI (and the companion Kandha talks to) waits
    assert not retries[-1]() and window.isVisible() and window.kandha_window is kandha
    kandha.stopped()
    assert window.kandha_window is None
    assert retries[-1]()
    assert not window.isVisible()


def test_cancelling_save_transcript_leaves_kandha_open(monkeypatch):
    """The Save transcript question comes before Kandha closes, so Cancel keeps Kandha's page as it was."""
    import app.ui.main_window as main_window
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[1]) or QMessageBox.Cancel)
    kandha = window.kandha_window = FakeKandha(window)
    window.session_dirty = True
    assert not window.close()
    assert asked == ["Save transcript"] and kandha.closes == 0 and window.kandha_window is kandha and window.isVisible()
    # answered No: Kandha closes first; the answer holds once it has, without asking again
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[1]) or QMessageBox.No)
    retries = []
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda *args: retries.append(args[-1]))
    assert not window.close() and kandha.closes == 1 and len(asked) == 2
    kandha.stopped()
    assert retries[-1]() and len(asked) == 2 and not window.isVisible()


def test_open_kandha_while_the_last_one_closes_opens_a_new_one(monkeypatch):
    """Open Kandha while the last Kandha window still stops its page: a new window follows it."""
    import app.ui.kandha_window as kandha_window
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "")
    window = MainWindow()
    made = []
    monkeypatch.setattr(kandha_window, "KandhaWindow", lambda url, **options: made.append(FakeKandha(window)) or made[-1])
    window.browser_service = SimpleNamespace(url="http://127.0.0.1:9")
    old = window.kandha_window = FakeKandha(window)
    old.close()
    window.open_kandha()
    assert window.kandha_window is old and made == [] and old.shown == 0
    old.stopped()
    assert len(made) == 1 and window.kandha_window is made[0] and made[0].shown == 1
    window.kandha_window = window.browser_service = None
    window.close()
