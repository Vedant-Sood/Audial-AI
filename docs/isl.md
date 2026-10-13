# Indian Sign Language across inputs

ISL is the fixed sign-language default. The speech language setting affects
transcription; it never selects ASL or another sign language. The global **ISL
with captions** preference starts enabled and is persisted for desktop/browser.
Manual text and document requests remain explicit playback actions.

| Input | Local processing |
|---|---|
| Typed text, clipboard, browser page selection | Unicode text → shared ISL vocabulary → ordered signs/text |
| TXT, Markdown, CSV, HTML | UTF-8 text extraction → the same vocabulary |
| DOCX, text PDF | Document text extraction → the same vocabulary |
| SRT, VTT, transcript JSON | Completed caption text → the same vocabulary |
| Microphone, system audio, shared tab audio | Installed multilingual Whisper → completed captions → the same vocabulary |
| WAV, FLAC, OGG, MP3, M4A, MP4, WebM, MKV | Local audio-track decoding → installed Whisper → the same vocabulary |

The default pack contains **four phrases**: good evening, good night, pleased,
and thank you. English/Hindi aliases are included. This is local vocabulary
playback in input order, not a learned sentence translation system. Arbitrary
words, names and unsupported languages remain readable as text; they are not
automatically fingerspelled or converted to invented gestures. Pose-only signs
omit facial cues. The camera model recognizes four isolated labels independently
of any added playback pack.

The native and browser queues preserve every step within a valid request. Unknown
passages appear between their surrounding signs. Pause, speed and manual stepping
apply to that sequence. If a media file cannot be read, its original text replaces
that step and later signs remain usable. Local videos show the source signer;
the browser may reject codecs it cannot decode.

Use up to **20,000 characters per request** and **2 MB per document**. Larger inputs
are explicitly rejected; select an extract. Text PDFs may contain at most 100
pages and must be unencrypted. Scans, pictures and video without an audio track
need text extraction or another applicable input method. Speech captions require
the selected Whisper model to be installed. Partial ASR drafts are not signed,
which prevents duplicate playback when a draft is revised.

## Extend the local vocabulary

Choose **Add an ISL vocabulary** and select its JSON. Keep all media inside the
same folder or its subfolders. The pack must declare `ISL`, a source URL and a
license for every sign. Adding a pack extends the bundled signs; a matching gloss
replaces its media while retaining existing aliases. Aliases cannot refer to two
different signs. **Use bundled vocabulary** resets the selection in both displays.

For example, copy the existing `thank_you.npy` into a new pack folder and create:

```json
{
  "language": "ISL",
  "entries": [
    {
      "gloss": "thank you",
      "aliases": ["thanks", "धन्यवाद"],
      "path": "thank_you.npy",
      "fps": 15,
      "source_url": "https://zenodo.org/records/4010759",
      "license": "CC-BY-4.0",
      "attribution": "INCLUDE dataset authors; preserve original notices."
    }
  ]
}
```

Supported media: raw NPY `[frames,49,4]` pose arrays and local MP4/MOV/WebM videos.
Pose arrays need 1–1,500 finite frames and at most one minute at the declared rate.
The 49 landmarks are nose/shoulders/elbows/wrists (7), left hand (21), and right
hand (21), with x/y/z/visibility channels in camera coordinates. Training tensors
are a different representation and cannot be used as replay poses.

Imported metadata is validated for structure, media location and source/license
presence. It does not establish linguistic correctness; source labels and
translations should be reviewed by an ISL signer. Expanding the playback pack
does not retrain the recognition model or add ISL sentence grammar.

## Validation and data availability

Tests cover mixed scripts, Hindi aliases, punctuation, retained unknown symbols,
document extraction, shared selection, long queues, real video byte ranges and
bad-media recovery. Native video was exercised on Linux using the supplied
640×360 thank-you clip, which rendered in all four main sign displays without
opening a microphone or camera. Windows readiness is reported separately.

No extra sign dataset was downloaded for 0.3.1. The official INCLUDE dataset
access on Zenodo was blocked by this cloud's current network policy; the required
destination is in the saved environment configuration draft. Public repositories
without a clear media reuse license were not bundled. Four restored phrases
remain the measured shipped coverage, as recorded in the current validation report.
