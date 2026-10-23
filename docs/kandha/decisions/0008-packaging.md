# 0008 · One Audial payload; `Kandha.exe`, `Kandha-Setup-<version>.exe` and a portable ZIP

**Decision.**
- `packaging/AccessibilityAI.spec` gains a third executable, `Kandha.exe`, built from the same
  analysis; `launcher.py` adds `--kandha` when the executable name starts with `Kandha`.
  QtWebEngine resources, `bleak` with its WinRT backend, the fonts, the pattern table, the tone
  model, the user guide rendered as HTML and the firmware sources (with the generated header
  and the flashing guide) are included. `bleak` is pinned in `requirements.txt`, and the build
  stops with a message if `bleak` or its platform backend is missing, instead of leaving the
  Bluetooth link out; `packaging/kandha_bluetooth.py --payload` checks a built payload.
- `packaging/kandha-installer.iss` produces `Kandha-Setup-<version>.exe`: AppName "Kandha",
  the same AppId as Audial-AI so one install upgrades the other, Start-menu entries "Kandha",
  "Audial-AI workspace", "Kandha user guide" (the HTML page, which stock Windows opens in the
  browser) and "Uninstall Kandha", and the same uninstall data choice.
- `scripts/package_kandha_portable.py` zips the PyInstaller folder as
  `Kandha-<version>-windows.zip` and writes a SHA-256 file beside it. Run on Linux it can
  write `Kandha-<version>-linux.tar.gz` the same way, but no CI job builds or publishes a
  Linux payload.
- Tagging `kandha-v<version>` publishes, after the existing Windows acceptance checks pass,
  `Kandha-Setup-<version>.exe` (and `Kandha-Setup-<version>-NVIDIA.exe` when that runtime is
  built), `Kandha-<version>-windows.zip` and `kandha-stole-firmware-<version>.zip` (the
  CI-built firmware binaries with their own `SHA256SUMS.txt`), each with a `.sha256` beside it,
  plus one `SHA256SUMS.txt` for all of them. The firmware binary is this separate download, not
  part of the installer.

**Why.** The existing workflow already proves fresh install, offline inference, upgrade and
uninstall for the Audial payload. Kandha reuses that proof instead of a second, untested
installer lineage. A separate AppId would install two copies of a 500 MB runtime.

**Rejected.** A Kandha-only PyInstaller build without the ISL and emotion pages: smaller, but
it would need its own acceptance suite and would break the "Kandha" entry in the Audial
navigation.
