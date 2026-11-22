# 0023 · Phone captions use on-device ASR and a phone-side microphone; the stole link stays audio-free

**Status.** Approved 22 Nov 2026; was proposed. The microphone choice is decided by measured WER.

**Decision.**
- **ASR:** whisper.cpp with a multilingual model and the psychology vocabulary prompt.
  `createOnDeviceSpeechRecognizer` is the fallback.
- **Audio** lives only in an in-memory ring buffer.
- **Microphones:** compare (1) the phone's own mic, (2) a Bluetooth headset or lapel mic on
  the phone, and (3) a wired or USB-C wireless lapel mic. Use WER on consented Indian English
  and Hindi speech, and caption delay.
- **Pod audio over the stole's BLE link is rejected.**

**Why.** It keeps the published promise and needs no portfolio change. On the phone,
whisper.cpp keeps the same model family as the laptop.

**Open.** Q15: whether a Bluetooth mic conflicts with the sentence "Bluetooth carries no
audio or words".

**Decided (22 Nov 2026).** **Q15.** The claim is reworded to "**the stole's Bluetooth link
carries no audio or words**". Bluetooth microphones on the phone come later and are off by
default.
