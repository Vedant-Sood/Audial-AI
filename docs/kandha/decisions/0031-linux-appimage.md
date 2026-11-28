# 0031 · Linux packaging is an AppImage

**Status.** Proposed, 28 Nov 2026 (demo build).

**Decision.**
- Build the PyInstaller one-folder bundle on Linux, then wrap it with `appimagetool` into
  `Kandha-<version>-x86_64.AppImage`.
- It embeds a `.desktop` entry and an icon, and opens with a double click on Arch: no
  terminal, no venv.
- The Whisper model downloads on first run, with a progress screen.

**Why.**
- AppImage is one file, needs no root, and runs on Arch and most distributions.

**Rejected.**
- **Flatpak:** sandboxed Bluetooth (BlueZ D-Bus) and microphone portals add setup that the
  demo doesn't need.
- **An AUR package:** Arch-only, and needs a maintainer.
- **A plain tarball:** not double-clickable.

**To measure.** AppImage size with and without torch: Kandha's captions use CTranslate2. And
whether BlueZ and PipeWire work from inside the AppImage on Arch.
