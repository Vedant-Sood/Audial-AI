# Troubleshooting

Normal Windows installations use Setup.exe and include their runtime. Python,
Git, Node and build tools are unnecessary for end users. The source-only setup
commands below apply to developers and older source distributions.

**No CUDA / DLL error:** the NVIDIA installer includes matching Torch/Torchaudio
2.8.0 CUDA 12.6 libraries; a compatible NVIDIA driver is still required. Update
that driver through its supported installer and inspect Diagnostics. Select CPU
and FAST in Settings if acceleration is unavailable. The presence of nvidia-smi
alone does not prove that PyTorch or ASR acceleration works. Source developers
can use `setup.bat --cpu` for a matched CPU environment.

**Microphone fails:** allow desktop apps under Windows privacy settings; close another app holding exclusive capture; inspect indexes in Diagnostics and save the desired index in Settings. The input path requests 16-kHz mono. Some devices/host APIs need a compatible Windows recording format or another device. Hardware validation failure is recorded, not hidden.

**Webcam fails:** allow camera access for desktop apps, close conflicting camera applications, then try another camera index. Pose assets must be installed first. The webcam starts only after its button is clicked.

**No captions:** open **Setup & models** and check the chosen preset's readiness;
automatic setup prepares every supported asset. Retry failed downloads, or
select a ready preset. Speaker information needs its backend's assets; leave
that setting off for simple captions. Noise/very quiet input may fail VAD. Set
the speech language in Settings. Raw ASR scores and a speaker colour do not
guarantee correctness.

**Caption queue warnings:** choose FAST, disable partial updates, or use a faster device. Dropped input keeps timestamp gaps. A queue-full warning means some speech was not captioned; no artificial transcript is generated to fill it.

**Download interrupted / model not installed:** use **Retry** on **Setup & models**.
Incomplete files remain resumable and are not treated as installed. Gated
Community-1 requires upstream acceptance and **Save access token**; Windows
Credential Manager holds that credential. Public models need no token.

**Wrong sign / uncertain label:** the bundled model knows only four isolated signs. Show both hands and upper body, record a complete sign, and review/edit the result before speaking. Collect signer-independent validation data before expanding its role.

**TTS cannot speak:** install a Windows local speech voice and ensure a valid output device. SAPI5 is used on Windows. Linux eSpeak/voice configuration was not validated as a Windows proxy. Audio capture pauses during playback to reduce feedback.

**Training fails:** dataset NPZ needs a real-data provenance JSON with matching schema beside it and nonempty train/val/test partitions. On CUDA OOM reduce batch, increase accumulation and resume latest.pt. Stop live capture before training. For a new dataset/config create a new output directory.

**Signing:** installers are unsigned; acceptance records `NotSigned`. Check the
adjacent SHA256 file against the downloaded installer. SHA256 identifies the
bytes and does not establish a signed publisher identity.

**Cloud MediaPipe GLES error:** a normal Linux machine needs libgles2/libegl1. During this cloud run the missing libgles2 package was extracted into a scoped dependency directory and provided through LD_LIBRARY_PATH. No such adjustment is required for the Windows wheel.

## Audial-AI 0.5.0 setup and browser recovery

Use **Setup & models**, which is always visible in navigation. Failed downloads
stay incomplete; **Pause downloads** retains resumable parts and **Retry** checks
and reuses valid files. A full corrupt file is rejected and fetched again. Free
storage when the message reports insufficient disk space; no marker is promoted
until integrity verification completes. Each model's installed receipt records
source revision, license and hashes. Reading a receipt is not proof of successful
inference. Advanced `--verify-inference` and `--verify-live-inference` commands
check real file and software-fed streaming pipelines with sockets blocked;
neither opens a physical microphone.

For Community-1, accept the upstream model terms and use **Save access token**.
The native Windows distribution stores it in Credential Manager, not settings or
logs. **Forget token** removes that credential without deleting model files.
Public Whisper, ECAPA and pose downloads do not need that gated-model token.
If a corporate proxy denies a public host, correct the allowed network policy;
do not supply an unnecessary token or disable TLS verification.

Routine warnings appear as nonmodal pop-ups. Failures stay above the workspace
with **Open setup**, **Open settings**, **Reconnect browser**, or diagnostics.
**Notifications** retains local history and duplicate counts. Earlier errors
remain in the unresolved summary until dismissed/acknowledged. A worker startup
or missing audio device now reaches this same interface. GPU failures explicitly
fall back to CPU; choose FAST for lower CPU latency.

For browser discovery, start the desktop, enable **Developer mode** on
`chrome://extensions` or `edge://extensions`, use **Load unpacked** to select the
bundled extension folder, then pin it and open its toolbar popup. Developer mode
must stay enabled for Chrome's unpacked reloads. The installer registers only the
native host; ordinary webpages cannot enumerate other tabs. The popup's connection
status distinguishes a missing bridge from a missing ASR model. Open a regular
web tab and invoke its toolbar action before **Capture this tab**. Focusing a tab
from the companion cannot grant capture rights. Browser settings and extension
store pages are restricted. Suspended tabs must be restored first.

The LIVE badge identifies the active tab. Invoke the toolbar in another tab to
switch sources. **Stop** releases tracks and audio context. Closing a tab or
losing the desktop connection ends ownership; extension reconnection refreshes
real tab metadata. A restarted desktop may use a new loopback port; use **Open
companion** in the connected extension or reopen it from the desktop. A managed
browser blocking unpacked extensions requires its administrator's approved
installation route. Manual **Share tab / app audio** is still a supported picker;
it never substitutes the microphone silently.

Chrome for Testing 156 and Edge Stable 155.0.4283.62 passed the full transport
lifecycle on hosted Windows on October 21, including suspend/restore. Edge 155
crashes with 0xC0000005 when a tab is discarded while Playwright's debugger is
attached; the same happens with an independent minimal tabs-only extension, so
the check now detaches the debugger before discarding. See the
[historical evidence](validation-0.5.0/windows-browser-edge.json) and the
standalone reproduction in `scripts/diagnose_browser_discard.py`. On `main`, the
installer workflow's Edge capture check now fails on Edge 156; that is open.
Behavior on a physical laptop is unverified.

**Source development: Python not found:** install Python 3.11 or 3.12 x64 with
its launcher and rerun `setup.bat`. The project uses its own `.venv` and leaves
global Python unchanged. See the current validation report for actual Windows
build status and limitations.
