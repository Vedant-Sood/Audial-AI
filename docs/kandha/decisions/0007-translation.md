# 0007 · English↔Hindi translation stays off in the Kandha window

**Decision.** In the Kandha window (QtWebEngine) the caption language equals the speech
language. The language switch sets Whisper's language (English or हिन्दी). Translation is
shown as "not available in this window" with the reason. In a Chrome 138+ tab, the page keeps
using the browser's built-in on-device translator when Chrome reports it available, as Sanket
did; audio and text still never leave the computer.

**Why.** The brief allows translation only if it runs on the device. QtWebEngine has no
built-in translator. Audial's runtime already includes CTranslate2 and SentencePiece, so an
`opus-mt-en-hi` / `hi-en` model (≈ 300 MB each) could be added to the model catalogue, but
that is a model-provenance, download and evaluation task of its own and nothing has been
validated for classroom psychology vocabulary. Rather than ship an unvalidated translator,
Kandha says why it is off.

**Would change it.** Adding the Marian models to `app/models/catalogue.py` with hashes and a
small evaluation on psychology sentences; the page already has the hook (`translator.js`).
