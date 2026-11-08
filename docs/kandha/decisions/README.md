# Kandha decision records

Short records of the real choices made while building Kandha. Each one says what was decided,
why, what was rejected and what would change the decision. New records get the next number.

| # | Decision |
|---|---|
| [0001](0001-web-view-ui.md) | The Kandha UI is HTML/JS in a QWebEngineView, not native Qt widgets |
| [0002](0002-scheduler-in-python.md) | The HapticScheduler lives in Python; intents are generated in the page |
| [0003](0003-motor-driver.md) | Motors are driven by logic-level MOSFETs and PWM, not DRV2605L drivers |
| [0004](0004-backchannel-threshold.md) | The back-channel hold is 0.6 s, measured on the LibriSpeech fixtures |
| [0005](0005-protocol-and-naming.md) | Protocol v1 UUIDs, `Kandha-XXXX` (the brief's name), pairing by remembered address |
| [0006](0006-seat-map-persistence.md) | Saved rooms store zone slot order, never voice identities |
| [0007](0007-translation.md) | English↔Hindi translation stays off in the Kandha window |
| [0008](0008-packaging.md) | One Audial payload; `Kandha.exe`, `Kandha-Setup-<version>.exe` and a portable ZIP |
| [0009](0009-event-transport.md) | Haptic commands return in the intent response; everything else arrives over SSE |
| [0010](0010-retire-band.md) | The Sanket wrist band is removed from code and UI |
| [0011](0011-prototype-without-hardware.md) | The prototype runs without hardware: a simulated stole is the default link |
| [0012](0012-own-voice.md) | A voice can be "me": the wearer's own speech never taps |
