# 0030 · Local HTTPS from a generated CA, and pairing by a one-time code in a QR

**Status.** Proposed, 28 Nov 2026 (demo build).

**Decision.**
- **Certificates.** On first use, the desktop app generates a private **local CA** and a
  server certificate for its LAN IP addresses (`cryptography`). The CA key never leaves the
  laptop, and the certificate is reissued when the IP changes.
- **Pairing.** The app shows a QR code with `https://<lan-ip>:<port>/phone/#pair=<one-time
  code>`.
  - The code works once, expires after 2 minutes, and becomes a per-phone session token
    held in the page's memory only. That means re-pairing after the tab closes, which is
    deliberate: nothing is stored.
  - Connected phones are listed, each with a Disconnect button.
- **Transport.** fetch + Server-Sent Events only; no WebSockets.
- **Trust, once per phone:**
  - **iOS:** download the CA profile from the app's QR page, install it, then turn it on
    under Settings → General → About → Certificate Trust Settings.
  - **Android:** Settings → Security → Install a certificate → CA certificate.
  - **Simpler route to test first:** tap through Safari's "not private" warning for this one
    site. If the mic and SSE work that way, the profile step is optional. To verify on the
    iPhone.

**Why.**
- Safari only gives the microphone to secure pages.
- Plain HTTP would put captions and the pairing token on the Wi-Fi unencrypted.

**Rejected.**
- A public certificate through a tunnel or a cloud relay: that breaks "no cloud".
- Plain HTTP: no mic on iOS, and readable traffic.
