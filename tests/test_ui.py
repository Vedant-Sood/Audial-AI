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
    assert window.stack.count() == 12
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
