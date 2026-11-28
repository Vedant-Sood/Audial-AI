# 0026 · For the demo, the phone is a website served by the desktop app; the native app (0022) is deferred

**Status.** Proposed, 28 Nov 2026 (demo build). **Defers 0022; doesn't replace it.**

**Decision.**
- The desktop app serves a phone page (`/phone/`) on the local network.
- On the iPhone the page is a **companion**: captions, the live stole display, the pad
  buttons, and optionally a mic. The laptop stays the stole's host.
- An Android "this phone drives the stole" mode over Web Bluetooth is optional. It's only
  allowed if the page's scheduler is proven against `scheduler.py` with golden vectors, as
  0022 requires.

**Why.**
- A demo is due soon. A web page reaches both phones (a recent iPhone, an old Motorola)
  without app-store signing or two native builds.
- iPhone Safari has no Web Bluetooth, so no iPhone web page can drive the stole anyway.

**Checked on the real phones (to record in VALIDATION):**
- Safari's mic access over local HTTPS;
- Chrome's Web Bluetooth on the Motorola (Android and Chrome versions);
- reconnect after Wi-Fi drops.

**Rejected for now.** A native Kotlin app (0022) and Flutter: too slow for the demo.

**Would change it.** If the web route can't give the iPhone a working mic or a stable link,
go back to 0022.
