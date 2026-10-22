# Sanket voice view

> **Sanket has become [Kandha](kandha/DESIGN.md).** The full app now lives at `/kandha/` and in
> the Kandha window (`python -m app.main --kandha`), paired with the Kandha Stole, a haptic
> scarf (prototype: virtual and simulated stoles, no hardware needed). The wrist band is
> retired. This page describes the voice engine and the companion's voice view, which Kandha
> reuses unchanged. User guide: [kandha/USER_GUIDE.md](kandha/USER_GUIDE.md).

Sanket (संकेत, "signal") was built for Hackcessible India 2026 (Vikram's challenge: a deaf
psychology student who lip-reads). It adds four things to Audial-AI's browser capture:

- **Who is speaking.** Each voice gets a colour and an arrow ("Voice 1", "Voice 2", …) as soon
  as it starts, so the reader can look at the right face. Voices are session-only slots, not
  identities.
- **Tone cues.** *Voice rose*, *voice softened*, *hesitation* and *long silence*, shown on the
  live panel. In Kandha they are felt at the collarbone of the Kandha Stole.
- **Tone compared with each person's usual voice** (experimental). For example *more intense
  than usual* or *softer, sad-sounding*. An emotion is named only when Sanket is at least 80%
  sure, after it has heard that person at least four times.
- **A queue light.** *I want to speak* (or **Q**) lights a strip across the live panel. It
  floats with the panel and can be held up in a seminar. The stole's queue pad toggles it too.

The full app (lecture, seminar and practicum modes, review timeline, Hindi captions, demos,
seats and the stole) is Kandha, served at `http://127.0.0.1:<port>/kandha/`; `/sanket/`
redirects there. It takes captions from Audial's local Whisper model.

## Where it runs

Sanket's voice engine (`browser/sanket/engine.js`, `tone.js`) is plain JavaScript. It runs on
the same PCM that browser capture already uploads, through a ~64 ms low-latency tap on
`pcm-worklet.js`. The tap is opt-in; the 2 s upload packets and their sample clock are
unchanged.

| Capture | Where the engine runs | How events reach the app |
|---|---|---|
| Companion page: Share tab audio / microphone | the companion page (`browser/voice-session.js`) | `POST /api/voice-events` with the session ID |
| Extension tab capture | the extension's offscreen document | `voice` bridge message from the owning capture |
| Kandha at `/kandha/` (window or tab) | the Kandha page | local captions use `/api/start`, `/api/audio`, `/api/events`; taps go to `/api/kandha/intents` |
| Desktop microphone / system audio / files | not available yet (the engine is JavaScript) | — |

The app validates every batch (`app/services/voice_view.py`): known kinds, finite times, voice
numbers 1–64, at most 200 events per batch and 20,000 per session, and named estimates only
at confidence ≥ 0.8. Only the capture that owns the session can add events. The app stores
the events with the session and republishes them as `voice` events, so every open page draws
the same view. Event times are audio seconds since the first captured sample, the same clock
captions use. That is how captions are matched to the voice heard longest during them.

Preferences live in `Settings` (`voice_colors` on, `voice_cues` and `voice_tone` off):
`POST /api/voice-view/settings`, also reported by `/api/status` and handed to extension
captures when they start. Vibration is a per-device choice stored in the page.

## Exports

- **JSON**: `voice_view.events` holds every stored event. Each caption gets
  `voice_view: {voice, tone}`. Loading the JSON back restores the events.
- **TXT**: captions show the voice name when diarization left them *Unattributed*, plus a
  `[tone: …]` note. Cues are listed in time order.
- **VTT / SRT**: *Unattributed* captions use the voice name (`Voice 2: …`). Diarized names and
  overlap labels are never replaced.

## Security

The companion keeps `script-src 'self'`. `browser/kandha/index.html` loads its scripts as
same-origin files (`tests/test_sanket_integration.py` checks that the page has no inline
scripts or handlers). Pages under `/kandha/` alone add `style-src 'unsafe-inline'` and
`font-src 'self'`, because Kandha colours voices with inline custom properties and bundles its
font. The companion page uses the CSS object model only.

`browser/sanket/package.json` and `browser/kandha/package.json` mark these UMD files as
CommonJS for Node. The server never serves them: `/sanket/` and `/kandha/` are explicit
allowlists. The tone model is served from
`models/sanket/tone_model.json` only while its SHA-256 matches `models/sanket/provenance.json`.

While the voice view is on, the page's microphone capture turns the browser's noise
suppression off. With it on, one reader was split into two colours in our browser check.
Echo cancellation is unchanged.

## How accurate it is

Measured on CREMA-D's 10 test actors. This is the same actor-disjoint split as Audial's
emotion models (`models/emotion/splits.json`); the actors were never seen in training. Full
records are in `models/sanket/evaluation.json`.

| | Result |
|---|---|
| Best guess among six acted categories (chance 17%) | 56% |
| Named estimates (≥ 80% confident): right / how often | 98% / 4% of sentences |
| Calm ↔ intense separation (angry, happy, fear vs sad, neutral), AUC | 0.91 |
| "Voice rose" on angry/happy/fear · false on neutral (earlier rules → model) | 41% → 50% · 12% → 1.5% |
| "Voice softened" on sad · wrong on angry/happy/fear | 28% → 43% · 12% → 6% |
| Natural calm reading, 3 LibriSpeech readers, 3.8 min | 1 emotion named in 55 stretches; 0 rose/softened cues (earlier rules: 7) |
| Speaker colours, stitched 4-person seminar | right person 98% of the time; 10 changes for 10 turns |

This is a lightweight browser model trained on Sanket's own 48 acoustic features. It is not a
substitute for Audial's WavLM model (80.8% on the same test, 1.3 GB). Its jobs are low-latency
cues and person-relative tone with no download.

The first version, which judged absolute loudness and microphone, called calm audiobook
readers "angry" at 95% confidence. That is why estimates are always relative to the person,
and why none are made for a voice heard fewer than four times.

**Limits.** The emotions are acted and the actors are American. There has been no testing on
Indian English or Hindi speakers, or on labelled natural conversation. Treat every estimate as
a reason to look again, never as a fact about feelings, intent or health. Voice colours are
approximate: similar voices can share a colour, and an expressive speaker can briefly get a
second one.

## Tests and retraining

- `npm test` (`tests/sanket.test.js`):
  - browser inference reproduces the training report;
  - estimates after a realistic calm warm-up are right and never overclaim;
  - natural calm reading stays quiet;
  - turn taking works, including a reader who comes back;
  - the voice-session batching, the worklet tap clock, caption attribution and local captions behave.
- `pytest tests/test_sanket_integration.py`:
  - CSP and the static allowlist;
  - the model hash check;
  - event ownership and validation, including from the extension bridge;
  - exports, preferences, and the session-only Hindi caption language.
- `python -m scripts.verify_sanket --browser <chromium> --output <dir>` (companion voice view)
  and `python -m scripts.verify_kandha` (the Kandha page with the mock stole):
  - real Chromium with a fake microphone playing two readers;
  - checks the companion voice view, the queue light and Q key, stored events, VTT names, and
    Kandha's taps, latency and queue on local captions;
  - Whisper is stubbed, so they say nothing about ASR accuracy.

Retraining needs CREMA-D's `AudioWAV` folder. Run:

```text
node training/sanket/extract_crema.mjs <AudioWAV> models/emotion/splits.json crema.jsonl
python training/sanket/train_tone.py crema.jsonl tone_model.json tone_report.json
node training/sanket/eval_cues.mjs <AudioWAV> models/emotion/splits.json tone_model.json cue_report.json
```

Copy the new model into `models/sanket/`, update `sha256` in `provenance.json`, and run the
tests above. If cue thresholds change, update `TUNING` in `browser/sanket/engine.js`.

`scripts/sync_sanket.py` copies a newer engine source tree into `browser/sanket/`; the app itself is developed in `browser/kandha/`.

Credits: CREMA-D (Cao et al., 2014; ODbL-1.0 / DbCL-1.0). LibriSpeech test fixtures (Panayotov
et al., 2015; CC BY 4.0). Speaker splits and evaluation approach from Audial-AI (Vedant Sood).
