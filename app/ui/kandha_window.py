"""The Kandha window: a QWebEngineView over the loopback companion's /kandha/ page.

Microphone permission is granted programmatically for the loopback origin only (Qt 6.8
QWebEnginePermission, with the older featurePermissionRequested kept as a fallback), so the
page can open the microphone without a browser prompt. Everything else is the HTML/JS app.
"""
import json
import os
import sys

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow

from app.utils.paths import project_root

LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


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


def _is_loopback(url):
    return url.host() in LOOPBACK_HOSTS


class KandhaWindow(QMainWindow):
    def __init__(self, base_url, parent=None, path="/kandha/"):
        super().__init__(parent)
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.setWindowTitle("Kandha")
        self.resize(1280, 760)
        self.setMinimumSize(1024, 640)
        icon = project_root() / "assets" / "icon.svg"
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
        self.base_url = base_url.rstrip("/")
        self.profile = QWebEngineProfile("kandha", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = QWebEnginePage(self.profile, self)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        self.granted = []
        self._wire_permissions()
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self.view.setAccessibleName("Kandha")
        self.setCentralWidget(self.view)
        self.view.load(QUrl(self.base_url + path))

    def _wire_permissions(self):
        page = self.page
        try:
            from PySide6.QtWebEngineCore import QWebEnginePermission
            page.permissionRequested.connect(self._on_permission)
            self.permission_api = "QWebEnginePermission"
            self._audio_types = {QWebEnginePermission.PermissionType.MediaAudioCapture}
        except (ImportError, AttributeError):
            from PySide6.QtWebEngineCore import QWebEnginePage
            page.featurePermissionRequested.connect(self._on_feature_permission)
            self.permission_api = "featurePermissionRequested"
            self._audio_types = {QWebEnginePage.Feature.MediaAudioCapture}

    def _on_permission(self, permission):
        kind = permission.permissionType()
        origin = permission.origin()
        if kind in self._audio_types and _is_loopback(origin):
            permission.grant()
            self.granted.append(("microphone", origin.toString()))
        else:
            permission.deny()

    def _on_feature_permission(self, origin, feature):
        from PySide6.QtWebEngineCore import QWebEnginePage
        policy = QWebEnginePage.PermissionPolicy.PermissionGrantedByUser if (feature in self._audio_types and _is_loopback(origin)) else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        self.page.setFeaturePermission(origin, feature, policy)
        if policy == QWebEnginePage.PermissionPolicy.PermissionGrantedByUser:
            self.granted.append(("microphone", origin.toString()))

    def run_js(self, script, callback):
        self.page.runJavaScript(script, 0, callback)


def launch(check=False, port=0, timeout_s=40):
    """`python -m app.main --kandha`: start the loopback companion and open the Kandha window.

    With check=True (`--kandha-check`), load the page, wait until it reports ready, print a
    JSON line and exit; used by CI and packaging checks.
    """
    prepare_chromium_flags()
    from PySide6.QtWidgets import QApplication
    from app.services.browser import BrowserService
    from app.utils.config import Settings
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Kandha")
    app.setOrganizationName("Audial-AI")
    try:
        settings = Settings.load()
    except ValueError:
        settings = Settings()
    service = BrowserService(settings=settings, port=port)
    url = service.start()
    window = KandhaWindow(url)
    window.show()
    result = {"ok": False}

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
            try:
                data = json.loads(value) if value else None
            except (TypeError, ValueError):
                data = None
            if data and data.get("ready"):
                result.update(ok=True, page=data, permission_api=window.permission_api, companion=url, title=window.windowTitle())
                print(json.dumps(result), flush=True)
                QTimer.singleShot(50, lambda: finish(0))
            else:
                QTimer.singleShot(300, probe)

        def give_up():
            if not result["ok"]:
                print(json.dumps({"ok": False, "error": "The Kandha page did not report ready in time."}), flush=True)
                finish(1)

        QTimer.singleShot(800, probe)
        QTimer.singleShot(timeout_s * 1000, give_up)
    return app.exec()
