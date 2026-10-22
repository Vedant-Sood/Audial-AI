# 0010 · The Sanket wrist band is removed from code and UI

**Decision.** `browser/sanket/band.js`, its GATT service, the "Connect Sanket Band" buttons,
the band status rows, the Android vibration toggle in the Sanket app and the `band` option of
`VoiceView` are removed. The companion page's voice card now links to Kandha; its
`VoiceView` keeps the optional device vibration callback for phones. Git history is the record.

**Why.** The brief retires the band, the glasses lights and the table pointer. Keeping dead
Bluetooth code would confuse the pairing story (two services, two "connect" buttons).

**Rejected.** Keeping the band as a hidden fallback.
