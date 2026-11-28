# Kandha decision records

Short records of the real choices made while building Kandha. Each one says what was decided,
why, what was rejected and what would change the decision. New records get the next number.

| # | Decision |
|---|---|
| [0001](0001-web-view-ui.md) | The Kandha UI is HTML/JS in a QWebEngineView, not native Qt widgets |
| [0002](0002-scheduler-in-python.md) | The HapticScheduler lives in Python; intents are generated in the page |
| [0003](0003-motor-driver.md) | Motors are driven by logic-level MOSFETs and PWM, not DRV2605L drivers |
| [0004](0004-backchannel-threshold.md) | The back-channel hold is 0.6 s, measured on the LibriSpeech fixtures |
| [0005](0005-protocol-and-naming.md) | Protocol v1 UUIDs, `KandhaStole-XXXX`, pairing by remembered address |
| [0006](0006-seat-map-persistence.md) | Saved rooms store zone slot order, never voice identities |
| [0007](0007-translation.md) | English↔Hindi translation stays off in the Kandha window |
| [0008](0008-packaging.md) | One Audial payload; `Kandha.exe`, `Kandha-Setup-<version>.exe` and a portable ZIP |
| [0009](0009-event-transport.md) | Haptic commands return in the intent response; everything else arrives over SSE |
| [0010](0010-retire-band.md) | The Sanket wrist band is removed from code and UI |
| [0011](0011-prototype-without-hardware.md) | The prototype runs without hardware: a simulated stole is the default link |
| [0012](0012-own-voice.md) | A voice can be "me": the wearer's own speech never taps |
| [0013](0013-npn-motor-switch.md) | Bench stole: ESP32-S3-Zero, 2N2222A NPN switches (amends 0003) · approved |
| [0014](0014-pin-budget-shared-i2s-clock.md) | Pin budget: shared I2S clock, MPU-6050 on GPIO 43/44 · approved |
| [0015](0015-seat-map-bearings.md) | Seat map stores bearings, fills from a SeatSource; pads override · approved |
| [0016](0016-tap-language-v2.md) | Tap language v2: retired ids never reused; crosstalk and off the record · approved |
| [0017](0017-direction-on-the-stole.md) | Direction computed on the stole; DIRECTION characteristic (protocol v2) · approved |
| [0018](0018-caption-memory-and-no-transcripts.md) | One 5-minute caption memory; no transcript save or export · **no save or export built**; memory planned |
| [0019](0019-off-the-record-detection.md) | "Kandha, off the record" detected in caption text · approved |
| [0020](0020-notes-encrypted-at-rest.md) | Bookmarks encrypted with AES-GCM, key in the OS keystore · approved |
| [0021](0021-redaction-spec.md) | Redaction: one deterministic spec, shared fixtures, Python and Kotlin · approved |
| [0022](0022-android-host.md) | Android host: Kotlin + WebView, golden vectors for the scheduler · approved |
| [0023](0023-phone-asr-and-mics.md) | Phone ASR on device; the stole link stays audio-free · approved |
| [0024](0024-one-host-at-a-time.md) | One host at a time; explicit hand-off · approved |
| [0025](0025-recap.md) | Extractive, redacted recap, wiped with the memory · approved |
| [0026](0026-phone-as-website.md) | Demo: the phone is a website served by the desktop app; defers 0022 · proposed |
| [0027](0027-audio-source-modes.md) | Audio source modes; multichannel capture and direction in desktop Python · proposed |
| [0028](0028-distributed-devices.md) | Distributed devices: loudness only, no clock sync, no audio sent · proposed |
| [0029](0029-phone-mic-path.md) | Phone → laptop audio: off by default; conflicts with "audio never leaves the laptop" · proposed |
| [0030](0030-local-https-pairing.md) | Local HTTPS from a generated CA; one-time-code QR pairing · proposed |
| [0031](0031-linux-appimage.md) | Linux packaging is an AppImage · proposed |
