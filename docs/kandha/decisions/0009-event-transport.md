# 0009 · Haptic commands return in the intent response; everything else arrives over SSE

**Decision.** `POST /api/kandha/intents` returns the commands the scheduler played for that
batch, so the page can pulse the virtual stole and record the tap without waiting for a poll.
Deferred commands (a cue released after a speaker tap, queue reminders, low battery), pad
presses, stole status and seat-map changes are pushed over `GET /api/kandha/stream`
(Server-Sent Events) with a heartbeat every 10 s. The existing `/api/events` poll is unchanged
for captions.

**Why.** The 300 ms caption poll is too slow for "the screen pulses exactly when the shoulder
does" and for the queue strip to light within a pad press. SSE is same-origin (`connect-src
'self'`), works in QtWebEngine and Chrome, and `ThreadingHTTPServer` already gives each
connection its own thread.

**Rejected.** WebSockets (not in `http.server`), polling faster (wasteful), QWebChannel (ties
the page to the Qt window; the Chrome tab would need a second path).
