# 0020 · Bookmarks are AES-256-GCM records keyed by the OS keystore; no keystore, no bookmarks

**Status.** Approved 22 Nov 2026; was proposed.

**Decision.**
- Each bookmark is redacted text plus the minute it was saved and the mode. Nothing else.
- It is encrypted with AES-256-GCM (`cryptography`).
- The data key is held by DPAPI, the Keychain or Secret Service (`keyring`), or by the
  Android Keystore on the phone.
- With no keystore, bookmarks are refused, never written in plain text.
- Practicum disables bookmarks entirely.

**Why.** The summary says saved notes are "stored encrypted". A key held by the OS keystore
needs no password typed in class, which keeps Vikram's eyes on faces.

**Rejected.**
- A passphrase: it has to be typed.
- A key file next to the notes: that is not encryption at rest in any useful sense.
