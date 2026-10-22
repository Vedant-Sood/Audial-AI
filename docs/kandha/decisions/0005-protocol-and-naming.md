# 0005 · Protocol v1 UUIDs, `KandhaStole-XXXX`, pairing by remembered address

**Decision.**
- Service UUID `2ad2fdad-b9e2-4025-af4d-b35e6f13c100`, generated with `uuid.uuid4()` on
  2026-10-22; characteristics use the same base with the last byte 01–05. The retired band's
  `a7c2f3e0-5b1d-4c8e-9f3a-53414e4b0001` family is never reused.
- The device advertises `KandhaStole-XXXX` (last four hex digits of its address) and the
  service UUID.
- Pairing is application-level: a user-initiated scan filtered by the service UUID or the name
  prefix, the chosen address saved in `<data>/kandha/stole.json`, reconnects only to that
  address, and `INPUT` notifications from any other address ignored. The firmware enables
  LE Secure Connections "Just Works" bonding so the OS link is encrypted; Kandha does not
  depend on it because bonding behaviour differs across Windows, macOS and Linux stacks.
- Little-endian for every multi-byte value; the only ones are `on_ms`/`off_ms` in PATTERNS.
- The product is **Kandha**, the hardware the **Kandha Stole**; the app flag is `--kandha`,
  the page `/kandha/`, the docs `docs/kandha/`, the Start-menu entry "Kandha".

**Why.** A fresh random UUID avoids any chance of a leftover band firmware answering a Kandha
scan. Remembering the address is the only pairing model that behaves the same on all three
desktop Bluetooth stacks through `bleak`.

**Rejected.** A 16-bit vendor UUID (needs Bluetooth SIG registration). Pairing by PIN (no
display on the stole).
