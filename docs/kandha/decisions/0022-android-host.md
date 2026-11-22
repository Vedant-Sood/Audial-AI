# 0022 · Android host: Kotlin app, the Kandha page in a WebView, a Kotlin scheduler proven by golden vectors

**Status.** Approved 22 Nov 2026; was proposed (planned work, after the portfolio).

**Decision.**
- **Kotlin:**
  - BLE central (v1 + v2);
  - scheduler, seat map, redaction and notes;
  - Android Keystore;
  - a foreground service.
- **WebView:** `browser/kandha/` and the unchanged `engine.js` and `kandha-intents.js`, talking
  over a JS bridge instead of loopback HTTP.
- **Golden vectors:** generated from the Python scheduler and seat map, versioned. Kotlin CI
  must reproduce the exact HAPTIC bytes and drop reasons.

**Why.**
- The voice engine is 900+ lines of tested JS. Running it unchanged keeps one engine.
- BLE and the keystore must be native.
- Golden vectors keep decision 0002's "one scheduler" true in behaviour.

**Rejected.**
- Flutter: it adds a third language and no benefit over Kotlin + WebView.
- Chaquopy (Python on Android), which would literally run `scheduler.py`: it is a large
  runtime, and the prompt asks for Kotlin first. It is still a fallback if the golden vectors
  keep drifting.
- Porting `engine.js` to Kotlin: two voice engines would drift.
