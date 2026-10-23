"""The Kandha window: a QWebEngineView over the loopback companion's /kandha/ page.

Microphone permission is granted programmatically to the companion's own origin only (Qt 6.8
QWebEnginePermission, with the older featurePermissionRequested kept as a fallback), so the
page can open the microphone without a browser prompt and name the microphones before Start,
and the view never leaves that origin.
Review exports are saved to the user's Downloads folder. The web view keeps nothing on disk; the
page's own settings are kept in one file under the app's data root (see STORAGE_JS). Closing the
window hides it at once, stops the page (listening, its stream and the microphone) and then frees
it. Everything else is the HTML/JS app.
"""
import functools
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.utils.paths import atomic_json, data_root, project_root

# Ends listening the page's own way (as its Pause button does: final words uploaded, the caption
# session and the microphone stopped) and says whether that is still finishing.
STOP_PAGE_JS = """(() => {
  const K = window.Kandha;
  if (!K || !K.S) return 'stopped';
  if (K.S.running) {
    if (typeof K.stopListening === 'function') K.stopListening();
    else { const button = document.getElementById('startBtn'); if (button) button.click(); }
  }
  const captions = K.captions;
  return (K.S.running || (captions && captions.stopping)) ? 'stopping' : 'stopped';
})()"""
PAGE_BUSY_JS = "(() => { const K = window.Kandha; return !!(K && K.S && (K.S.running || K.S.demo || K.S.lines.length)); })()"
STOP_WAIT_S = 3.0

# The page keeps its settings in localStorage, which Chromium files under the page's origin, and the
# origin includes the companion's port, which is a new free port on most launches. So the web view
# keeps no storage of its own: this script, run before the page's own scripts, fills the page's
# storage from page_settings_path() and reports every later change as a console message, which the
# window saves there. The settings then come back however Kandha is opened and on whatever port.
STORAGE_MARKER = "kandha-page-storage:"
STORAGE_JS = """(() => {
  if (location.origin !== __ORIGIN__) return;
  const saved = __SAVED__;
  try {
    for (const key of Object.keys(saved)) if (localStorage.getItem(key) === null) localStorage.setItem(key, saved[key]);
  } catch (e) { return; /* storage unavailable */ }
  const report = () => {
    const all = {};
    for (let i = 0; i < localStorage.length; i++) { const key = localStorage.key(i); all[key] = localStorage.getItem(key); }
    console.debug(__MARKER__ + JSON.stringify(all));
  };
  for (const name of ['setItem', 'removeItem', 'clear']) {
    const original = Storage.prototype[name];
    Storage.prototype[name] = function () {
      const result = original.apply(this, arguments);
      if (this === window.localStorage) { try { report(); } catch (e) { /* storage unavailable */ } }
      return result;
    };
  }
})()"""
PAGE_STORAGE_LIMIT = 1_000_000   # characters; the page's settings are about one thousand


def prepare_chromium_flags(extra=""):
    """Chromium flags for the embedded page. Set before QApplication exists."""
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    wanted = ["--autoplay-policy=no-user-gesture-required"]
    if extra:
        wanted.append(extra)
    for flag in wanted:
        if flag not in flags:
            flags = (flags + " " + flag).strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    return flags


def same_origin(url, origin):
    """True when url (a blob: URL counts as its creator's) has exactly origin's scheme, host and port."""
    if url.scheme() == "blob":
        url = QUrl(url.path())
    return (url.scheme(), url.host(), url.port()) == (origin.scheme(), origin.host(), origin.port())


def page_settings_path():
    """The Kandha page's settings (its localStorage): one file, however Kandha was opened. It lives
    under the app's data root, so removing that folder (the uninstaller's data purge) removes it too."""
    return data_root() / "kandha" / "page-settings.json"


def valid_page_settings(value):
    """value when it is what localStorage can hold (text keys and values) and small, else None."""
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return None
    if sum(len(k) + len(v) for k, v in value.items()) > PAGE_STORAGE_LIMIT:
        return None
    return value


def load_page_settings():
    try:
        value = json.loads(page_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return valid_page_settings(value) or {}


def unique_path(folder, name, taken=()):
    """folder/name, or 'name (2)', 'name (3)' … when that file exists or another save took it."""
    name = Path(name).name or "kandha-export"
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, number = Path(folder) / name, 2
    while candidate.exists() or str(candidate) in taken:
        candidate = Path(folder) / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def theme_stylesheet():
    theme = project_root() / "assets" / "theme.qss"
    if not theme.is_file():
        return ""
    return theme.read_text(encoding="utf-8").replace("@ASSETS@", (project_root() / "assets").as_posix())


def downloads_folder():
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return Path(folder) if folder else Path.home()


@functools.cache
def _page_class():
    from PySide6.QtWebEngineCore import QWebEnginePage

    class KandhaPage(QWebEnginePage):
        """Stays on the companion origin: any other address is refused, never handed to another
        program (a script-driven navigation looks like a clicked link and could carry page data out)."""

        def __init__(self, profile, origin, parent=None):
            super().__init__(profile, parent)
            self.origin = origin
            self.on_storage = None

        def acceptNavigationRequest(self, url, kind, main_frame):
            return same_origin(url, self.origin)

        def javaScriptConsoleMessage(self, level, message, line, source):
            if message.startswith(STORAGE_MARKER):
                # STORAGE_JS reporting the page's settings; only the companion page's own count
                if self.on_storage is not None and same_origin(self.url(), self.origin):
                    self.on_storage(message[len(STORAGE_MARKER):])
                return
            super().javaScriptConsoleMessage(level, message, line, source)

    return KandhaPage


class KandhaWindow(QMainWindow):
    """service: the BrowserService behind base_url, used to tell whether the caption model is
    installed. open_setup: shows Audial-AI's own Setup & models (the Audial-AI window passes it,
    with setup, that page's ModelSetup, so Kandha can show its download is running); without it
    the Kandha window runs the same setup in a dialog of its own.

    closed is emitted once the window has closed and its page has stopped and been freed."""

    closed = Signal()

    def __init__(self, base_url, parent=None, path="/kandha/", service=None, open_setup=None, setup=None):
        super().__init__(parent)
        # an application-wide Python event filter must be gone before the web view exists
        from app.ui.style import prepare_for_web_view
        prepare_for_web_view()
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.setWindowTitle("Kandha")
        self.resize(1280, 760)
        self.setMinimumSize(1024, 640)
        icon = project_root() / "assets" / "icon.svg"
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.base_url = base_url.rstrip("/")
        self.origin = QUrl(self.base_url)
        self.service = service
        self.open_setup = open_setup
        self.shared_setup = setup
        self.setup_dialog = self.model_setup = None
        self._reload_offered = False
        self._stop_started = self._page_stopped = False
        self._stop_deadline = 0.0
        self.downloads = {}
        # off the record: the web view writes nothing to disk (no history, cache or storage of its
        # own, and nothing two running copies could fight over); the page's settings are kept by
        # this window instead, in page_settings_path()
        self.profile = QWebEngineProfile(self)
        if hasattr(self.profile, "setPersistentPermissionsPolicy"):
            # each microphone request is decided by _on_permission, never by a remembered grant
            self.profile.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
        self.profile.setDownloadPath(str(downloads_folder()))
        self.profile.downloadRequested.connect(self._on_download)
        self.page = _page_class()(self.profile, self.origin, self)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        self.page_storage = load_page_settings()
        self._storage_script = None
        self._install_storage_script()
        self.page.on_storage = self._save_page_storage
        self.granted = []
        self._wire_permissions()
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_setup_bar())
        self.view = QWebEngineView(central)
        self.view.setPage(self.page)
        self.view.setAccessibleName("Kandha")
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)
        # Qt deletes a window's children in order and a page must go before its profile, so the
        # profile becomes the last child (release() also frees them in that order when Kandha closes)
        self.profile.setParent(None)
        self.profile.setParent(self)
        self.view.load(QUrl(self.base_url + path))
        self.setup_timer = QTimer(self)
        self.setup_timer.setInterval(2000)
        self.setup_timer.timeout.connect(self.refresh_setup_bar)
        self.refresh_setup_bar()

    # ------------------------------------------------------------------ caption model setup
    def _build_setup_bar(self):
        bar = QFrame()
        bar.setObjectName("notice")
        bar.setAccessibleName("Caption model")
        bar.setStyleSheet(theme_stylesheet())
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        # no accessible name of its own: a label's text is what screen readers read for it
        self.setup_text = QLabel()
        self.setup_text.setWordWrap(True)
        row.addWidget(self.setup_text, 1)
        self.setup_button = QPushButton("Get the caption model")
        self.setup_button.setObjectName("primary")
        self.setup_button.clicked.connect(self.setup_action)
        row.addWidget(self.setup_button)
        bar.hide()
        self.setup_bar = bar
        return bar

    def caption_model(self):
        """(model id, installed) for the caption model the companion uses, or None without a service."""
        if self.service is None:
            return None
        from app.utils.config import PRESETS
        model = PRESETS[self.service.settings.preset]["asr"]
        return model, self.service.engine.manager.installed(model)

    def setup_running(self):
        """True while a model setup runs: this window's own, or Audial-AI's Setup & models."""
        return any(setup is not None and setup.process is not None for setup in (self.model_setup, self.shared_setup))

    def show_setup_text(self, text, button):
        self.setup_button.setText(button)
        if self.setup_text.text() == text:
            return
        self.setup_text.setText(text)
        # read the new message out to screen readers as well (Qt 6.8 announcements)
        try:
            from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
            QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self.setup_text, text))
        except (ImportError, AttributeError, TypeError):
            pass

    def refresh_setup_bar(self):
        status = self.caption_model()
        if status is None or self._reload_offered:
            return
        model, installed = status
        if installed:
            self.setup_timer.stop()
            if self.setup_bar.isVisible():
                # the model arrived while Kandha was open: load it now unless that would clear a session
                self.run_js(PAGE_BUSY_JS, self._model_ready)
            return
        if self.setup_running():
            self.show_setup_text(f"Downloading the caption model ({model}) to this computer. "
                                 "Voices and stole taps work meanwhile.", "Show progress")
        else:
            self.show_setup_text(f"Captions need the Whisper caption model ({model}), downloaded once to this computer "
                                 "by Audial-AI's Setup & models. Voices and stole taps work now.", "Get the caption model")
        self.setup_bar.show()
        self.setup_timer.start()

    def _model_ready(self, busy):
        if busy:
            self._reload_offered = True
            self.show_setup_text("The caption model is ready. Reload Kandha to use it; "
                                 "reloading clears this screen, so pause and save first.", "Reload Kandha")
        else:
            self.reload_page()

    def reload_page(self):
        self._reload_offered = False
        self.setup_bar.hide()
        self.setup_timer.stop()
        if self.page is not None:
            self.view.reload()

    def setup_action(self):
        if self._reload_offered:
            self.reload_page()
        else:
            self.show_model_setup()

    def show_model_setup(self):
        """Start Audial-AI's model setup (the full catalogue, the caption model first) with visible progress."""
        if self.open_setup is not None:
            self.open_setup()
        elif self.service is not None:
            if self.setup_dialog is None:
                from PySide6.QtWidgets import QDialog, QDialogButtonBox
                from app.ui.model_setup import ModelSetup
                dialog = QDialog(self)
                dialog.setWindowTitle("Setup & models")
                dialog.resize(760, 640)
                dialog.setStyleSheet(theme_stylesheet())
                layout = QVBoxLayout(dialog)
                self.model_setup = ModelSetup(self.service.engine.manager, dialog)
                self.model_setup.failure.connect(self.warn)
                self.model_setup.changed.connect(self.refresh_setup_bar)
                layout.addWidget(self.model_setup, 1)
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                buttons.rejected.connect(dialog.hide)
                layout.addWidget(buttons)
                self.setup_dialog = dialog
            self.setup_dialog.show()
            self.setup_dialog.raise_()
            self.setup_dialog.activateWindow()
            self.model_setup.start()
        self.refresh_setup_bar()

    def warn(self, message):
        box = QMessageBox(QMessageBox.Icon.Warning, "Kandha", message, QMessageBox.StandardButton.Ok, self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        box.open()

    # ------------------------------------------------------------------ downloads
    def _on_download(self, download):
        """Save the page's own exports (Review: web page, text, VTT, SRT, JSON) to Downloads."""
        if download.page() is not self.page or download.isSavePageDownload() or not same_origin(download.url(), self.origin):
            download.cancel()
            return
        folder = downloads_folder()
        name = download.suggestedFileName() or download.downloadFileName()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            download.cancel()
            self._report_download(False, unique_path(folder, name), f"the folder could not be created ({error.strerror or error})")
            return
        target = unique_path(folder, name, taken={str(path) for path in self.downloads.values()})
        download.setDownloadDirectory(str(target.parent))
        download.setDownloadFileName(target.name)
        self.downloads[download] = target
        download.isFinishedChanged.connect(lambda: self._download_finished(download))
        download.accept()

    def _download_finished(self, download):
        from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
        target = self.downloads.pop(download, None)
        if target is None or not download.isFinished():
            return
        state = download.state()
        ok = state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted and target.is_file()
        if ok:
            error = ""
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            error = download.interruptReasonString() or "the download was interrupted"
        else:
            # Kandha offers no way to cancel a save, so a cancelled one could not be written
            # (Qt words that "canceled by the user", which would blame the user)
            error = "the file could not be written there"
        self._report_download(ok, target, error)

    def _report_download(self, ok, target, error=""):
        detail = {"ok": ok, "name": target.name, "folder": str(target.parent), "path": str(target), "error": error}
        # the page can show where the file really went (or that it failed)
        self.run_js(f"window.dispatchEvent(new CustomEvent('kandha-download', {{ detail: {json.dumps(detail)} }}))")
        if not ok:
            self.warn(f"Kandha could not save {target.name} to {target.parent}: {error}.")

    # ------------------------------------------------------------------ page settings
    def _install_storage_script(self):
        """(Re)place STORAGE_JS, holding the latest saved settings, for the page's next load."""
        from PySide6.QtWebEngineCore import QWebEngineScript
        scripts = self.page.scripts()
        if self._storage_script is not None:
            scripts.remove(self._storage_script)
        # the page's location.origin: scheme://host[:port]
        origin = f"{self.origin.scheme()}://{self.origin.host()}" + (f":{self.origin.port()}" if self.origin.port() >= 0 else "")
        source = (STORAGE_JS.replace("__ORIGIN__", json.dumps(origin)).replace("__MARKER__", json.dumps(STORAGE_MARKER))
                  .replace("__SAVED__", json.dumps(self.page_storage)))
        script = QWebEngineScript()
        script.setName("kandha-page-storage")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(source)
        scripts.insert(script)
        self._storage_script = script

    def _save_page_storage(self, text):
        try:
            value = valid_page_settings(json.loads(text))
        except ValueError:
            value = None
        if value is None or value == self.page_storage or self.page is None:
            return
        self.page_storage = value
        try:
            atomic_json(page_settings_path(), value)
        except OSError:
            pass   # not saved: the settings then last until Kandha closes
        self._install_storage_script()

    # ------------------------------------------------------------------ closing
    @property
    def closing(self):
        """True once the window was closed: its page is stopping or already freed."""
        return self._stop_started

    def closeEvent(self, event):
        """Closing hides the window at once and stops the page rather than keeping it: listening
        ends the page's own way (its last words and events reach the companion), then the page,
        its stream and the microphone are freed, `closed` is emitted and the window is deleted.
        The close itself is never refused, so it cannot hold up Audial-AI's or the program's quit."""
        if self.setup_dialog is not None:
            self.setup_dialog.hide()
        if not self._stop_started:
            self._stop_started = True
            self._stop_deadline = time.monotonic() + STOP_WAIT_S
            if self.page is None:
                QTimer.singleShot(0, self, self._finish_close)
            else:
                self._poll_page_stop()
                QTimer.singleShot(int(STOP_WAIT_S * 1000) + 500, self, self._finish_close)
        super().closeEvent(event)

    def _poll_page_stop(self):
        if self.page is not None and not self._page_stopped:
            self.run_js(STOP_PAGE_JS, self._on_page_stop)

    def _on_page_stop(self, state):
        # wait (at most STOP_WAIT_S) while listening finishes or an export is still being written
        if (state == "stopping" or self.downloads) and time.monotonic() < self._stop_deadline:
            QTimer.singleShot(150, self, self._poll_page_stop)
        else:
            QTimer.singleShot(0, self, self._finish_close)

    def _finish_close(self):
        if self._page_stopped:
            return
        self._page_stopped = True
        if self.model_setup is not None:
            self.model_setup.shutdown()
        self.setup_timer.stop()
        self.release()
        self.closed.emit()
        self.deleteLater()

    def release(self):
        """Free the view and the page (its stream and microphone with it), then their profile."""
        import shiboken6
        if self.page is None:
            return
        view, page, profile = self.view, self.page, self.profile
        self.view = self.page = self.profile = None
        for item in (view, page, profile):
            if shiboken6.isValid(item):
                shiboken6.delete(item)

    def _wire_permissions(self):
        page = self.page
        try:
            from PySide6.QtWebEngineCore import QWebEnginePermission
            page.permissionRequested.connect(self._on_permission)
            self.permission_api = "QWebEnginePermission"
            self._audio_types = {QWebEnginePermission.PermissionType.MediaAudioCapture}
            self._pregrant_microphone(QWebEnginePermission.PermissionType.MediaAudioCapture)
        except (ImportError, AttributeError):
            from PySide6.QtWebEngineCore import QWebEnginePage
            page.featurePermissionRequested.connect(self._on_feature_permission)
            self.permission_api = "featurePermissionRequested"
            self._audio_types = {QWebEnginePage.Feature.MediaAudioCapture}

    def _pregrant_microphone(self, kind):
        """Grant the microphone to the companion's exact origin up front as well, so the page can list
        the microphones by name (and show the one picked last time) before Start. Listing opens no
        device: the microphone opens only when Start asks for it, and that request still comes to
        _on_permission. Without this the names come only after the first Start of each launch."""
        if hasattr(self.profile, "queryPermission"):
            permission = self.profile.queryPermission(self.origin, kind)
            if permission.isValid():
                permission.grant()

    def _on_permission(self, permission):
        kind = permission.permissionType()
        origin = permission.origin()
        # the microphone, for the companion's exact origin (scheme, host and port) only
        if kind in self._audio_types and same_origin(origin, self.origin):
            permission.grant()
            self.granted.append(("microphone", origin.toString()))
        else:
            permission.deny()

    def _on_feature_permission(self, origin, feature):
        from PySide6.QtWebEngineCore import QWebEnginePage
        policy = QWebEnginePage.PermissionPolicy.PermissionGrantedByUser if (feature in self._audio_types and same_origin(origin, self.origin)) else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        self.page.setFeaturePermission(origin, feature, policy)
        if policy == QWebEnginePage.PermissionPolicy.PermissionGrantedByUser:
            self.granted.append(("microphone", origin.toString()))

    def run_js(self, script, callback=None):
        if self.page is not None:
            if callback is None:
                self.page.runJavaScript(script, 0)
            else:
                self.page.runJavaScript(script, 0, callback)


def launch(check=False, port=0, timeout_s=150):
    """`python -m app.main --kandha`: start the loopback companion and open the Kandha window.

    With check=True (`--kandha-check`), load the page, wait until it reports ready, print a
    JSON line and exit; used by CI and packaging checks.
    """
    prepare_chromium_flags()
    import shiboken6
    from PySide6.QtWidgets import QApplication
    from app.services.browser import BrowserService
    from app.ui.style import install_style
    from app.utils.config import Settings
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Kandha")
    app.setOrganizationName("Audial-AI")
    # the window hides as soon as it is closed; the program ends once its page has stopped
    app.setQuitOnLastWindowClosed(False)
    # the caption-model bar and Setup & models dialog get Audial-AI's keyboard focus ring
    install_style(app)
    try:
        settings = Settings.load()
    except ValueError:
        settings = Settings()
    service = BrowserService(settings=settings, port=port)
    url = service.start()
    page_url = url + "/kandha/"
    window = KandhaWindow(url, service=service)
    window.closed.connect(app.quit)
    window.show()
    result = {"ok": False}
    last = {"value": None, "started": time.monotonic()}

    def finish(code):
        try:
            service.stop()
        finally:
            app.exit(code)

    app.aboutToQuit.connect(lambda: service.stop())
    if check:
        def probe():
            window.run_js("JSON.stringify(window.Kandha ? window.Kandha.ready() : null)", on_probe)

        def on_probe(value):
            last["value"] = value
            try:
                data = json.loads(value) if value else None
            except (TypeError, ValueError):
                data = None
            if data and data.get("ready"):
                result.update(ok=True, page=data, permission_api=window.permission_api, companion=url, title=window.windowTitle(),
                              seconds_to_ready=round(time.monotonic() - last["started"], 1))
                print(json.dumps(result), flush=True)
                QTimer.singleShot(50, lambda: finish(0))
            else:
                QTimer.singleShot(300, probe)

        def give_up():
            if not result["ok"]:
                print(json.dumps({"ok": False, "error": f"The Kandha page did not report ready within {timeout_s} s.",
                                  "last_probe": last["value"], "url": page_url, "page_title": window.windowTitle(),
                                  "web_title": window.view.title()}), flush=True)
                finish(1)

        QTimer.singleShot(800, probe)
        QTimer.singleShot(int(timeout_s * 1000), give_up)
        result["seconds_to_ready"] = None
    code = app.exec()
    # the page and its profile are freed here, in that order, not at interpreter exit
    if shiboken6.isValid(window):
        window.release()
    return code
