# Architecture and code map

## Native application

`launcher.py` starts `app/main.py`. The main entry supports desktop, local browser,
explicit model installation, training and a non-recording startup check. Desktop
startup failures are logged locally and reported to Windows users.

`app/ui/main_window.py` owns navigation, explicit audio/camera controls, playback,
settings and exports. Everyday modes remain visible; advanced tools are revealed
on demand. `app/ui/widgets.py` renders captions, objective voice measurements,
text-labeled emotion colors and hand/body poses. `app/utils/palette.py` validates
hex colors and chooses black/white text from sRGB contrast. `app/utils/config.py`
loads old settings with defaults for newly added fields and persists preferences.

## Audio, models and storage

`app/services/engine.py` prepares local models and coordinates capture, bounded
ASR work and UI events. SoundFile and PyAV decode local recordings; microphone,
system-loopback and browser capture are explicit sources in `app/audio/capture.py`.
The original chunking, transcription and word/timestamp reconciliation are kept.

`app/inference/emotion.py` loads the bundled or explicitly activated model and
abstains on unsuitable segment length. `accessibilityai_upgrade/audio.py` provides
shared acoustic features; `predict.py` calibrates classifier margins and abstains
for silence, clipping or insufficient confidence. Estimates never alter caption
text. Emotion model activation checks recorded model hashes before selecting a
local copy. Existing CREMA-D measurements remain historical.

`app/models/manager.py` handles explicit downloads and trained sign checkpoint
imports. Inference sets offline mode. `app/storage/transcript.py` stores completed
captions and optional voice metadata and exports independent transcript formats.
`app/utils/paths.py` separates resource paths from local user state.

## ISL and browser

`app/services/lexicon.py` validates source/license metadata and local media paths,
keeps Indic combining marks in aliases, and builds an ordered sign/text plan.
`app/services/isl.py` owns the fixed ISL language, selected local pack, bundled
pack extension, cache and common pose validation. `Settings.auto_sign` defaults
to true, and `Settings.sign_language` accepts ISL only; the independent speech
language controls Whisper. Desktop and browser share this vocabulary service.
`app/services/text_input.py` reads text, subtitles, transcript JSON, HTML, Word
and text PDF documents. It preserves numeric subtitle lines and rejects input
above the documented limits instead of truncating it.
Known signs use attributed poses or local videos. Text fallback is visible and
explicit, preserving unknown content without claiming it is translated ISL.

`app/ui/sign_lights.py` supplies an optional always-on-top display. The native
workspace also has a hand/body skeleton view. Neither representation supplies
full facial grammar. Camera recognition is isolated-sign classification and is
separate from phrase playback.

`app/services/browser.py` serves the companion only on loopback and checks Host
and Origin. Session IDs prevent one browser tab controlling another tab's capture.
`browser/capture.js` and `pcm-worklet.js` flush final audio packets.
`browser/emotion.js` renders labeled colors; `/api/palette` persists validated
preferences. The existing browser extension opens selected page text on explicit
user action.

`POST /api/signs` and `POST /api/document?filename=...` return all ordered pose,
video and text steps. Repeated poses share one serialized sequence. Dictionary
video URLs reference only validated pack entries and support byte-range playback.
`browser/isl-playback.js` manages text timing, pause, manual stepping and queue
order. It accepts only ISL plans. Native `QVideoSink` frames render in every sign
canvas; dictionary audio is silent. Unreadable media falls back to original text
and leaves subsequent signs usable.

## Training and packaging

`scripts/train_indian_emotion.py` validates real labeled data and divides it by
speaker before fitting. Validation, probability fitting, policy selection and
final testing remain separate. `scripts/activate_emotion.py` selects a verified,
trusted trained result. `training/` retains the uploaded sign/prosody experiments.

`scripts/package_project.py` builds and verifies a source ZIP manifest.
`scripts/package_windows_portable.py` obtains official Windows Python with a
pinned SHA512, resolves Windows wheels and verifies their RECORD contents before
assembling a portable desktop. `packaging/AccessibilityAI.spec` builds native
executables on Windows; `.github/workflows/windows-release.yml` gates native
release publication on its Windows tests. Packaging never implies a new model
accuracy result or a successful test on the user's hardware.


## 0.5.0 setup, native browser bridge and scheduling

The PySide6/Python-worker architecture is retained. First launch invokes
`CatalogueInstaller` through a console worker. It resolves revision-pinned model
assets, verifies authoritative hashes into resumable staging, and atomically
promotes complete directories. CLI/developer installs use the same path and file
lock. Receipts and user state stay outside the application directory. Only an
active inference feature loads a model.

MV3 `chrome.tabs` supplies real metadata; toolbar/activeTab plus tabCapture and an
offscreen audio worklet supply explicitly granted PCM. The native console worker
exchanges bounded length-framed JSON and forwards it to a private authenticated
loopback bridge. Capture ownership is a per-session capability; ordinary companion
pages see public metadata but cannot impersonate the native audio source. Native
disconnect, closed/restricted/discarded tabs and expired heartbeats release the
owner. Metadata is resent after desktop or extension restarts.

`ExpressionWorker` owns the lazy emotion encoder on one thread. Latest-only live
updates and eight optional caption jobs prevent model races and bound backlog;
caption text/prosody publish independently. Natural file completion drains final
caption estimates. Explicit stop cancels optional backlog and releases resources.
Desktop/browser transcript views render a 500-row window; full session objects
remain exportable. Rendering and real model benchmarks are separate reports.
