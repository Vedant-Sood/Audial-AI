# 0001 · The Kandha UI is HTML/JS in a QWebEngineView

**Decision.** The Kandha window is a `QMainWindow` holding one `QWebEngineView` that loads
`http://127.0.0.1:<port>/kandha/` from the existing loopback `BrowserService`. The UI is the
Sanket app evolved (`browser/kandha/`), served under the same CSP rules as `/sanket/` was.

**Why.**
- Sanket's voice engine, tone estimator and caption assembler are JavaScript with tests and a
  training pipeline that reads the same files. Running them in the page keeps one engine and
  one clock (audio time from the AudioWorklet tap), and the whole Sanket UI (captions,
  vocabulary, review, demos) comes with it.
- QtWebEngine (PySide6-Addons 6.8.3, Chromium 122) supports `getUserMedia`, `AudioWorklet`,
  `<dialog>`, CSS `color-mix` and everything the page uses. Microphone permission is granted
  programmatically with the Qt 6.8 `QWebEnginePermission` API (with the deprecated
  `featurePermissionRequested` kept as a fallback), scoped to the loopback origin.
- People who prefer a browser tab keep `/kandha/` in Chrome or Edge; `/sanket/` redirects there.

**Cost.** QtWebEngine adds roughly 150–200 MB to the Windows installer. The build already
ships Torch and Qt, so this is accepted (see 0008).

**Rejected.** Native Qt widgets would need the engine ported to Python (or a JS runtime in
Python), losing the tests and the training parity, and still need a web view for the review
export. Web Bluetooth was never an option: QtWebEngine does not expose it, and even in Chrome
it ties the device to one tab.

**Would change it.** A requirement to run without Chromium (for example on a very small
machine) would justify a Python port of `engine.js`.
