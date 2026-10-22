# 0008 · One Audial payload; `Kandha.exe`, `Kandha-Setup-<version>.exe` and a portable ZIP

**Decision.**
- `packaging/AccessibilityAI.spec` gains a third executable, `Kandha.exe`, built from the same
  analysis; `launcher.py` adds `--kandha` when the executable name starts with `Kandha`.
  QtWebEngine resources, `bleak` with its WinRT backend, the fonts, the pattern table, the tone
  model and the firmware (source, generated header, flashing guide and the CI-built binary when
  present) are included.
- `packaging/kandha-installer.iss` produces `Kandha-Setup-<version>.exe`: AppName "Kandha",
  the same AppId as Audial-AI so one install upgrades the other, Start-menu entries "Kandha"
  and "Audial-AI", and the same uninstall data choice.
- `scripts/package_kandha_portable.py` zips the PyInstaller folder as
  `Kandha-<version>-windows.zip` (and `Kandha-<version>-linux.tar.gz` on Linux) and writes
  SHA-256 files beside everything.
- Tagging `kandha-v<version>` publishes the installer, the ZIP, the firmware binary and the
  checksums as release assets after the existing Windows acceptance checks pass.

**Why.** The existing workflow already proves fresh install, offline inference, upgrade and
uninstall for the Audial payload. Kandha reuses that proof instead of a second, untested
installer lineage. A separate AppId would install two copies of a 500 MB runtime.

**Rejected.** A Kandha-only PyInstaller build without the ISL and emotion pages: smaller, but
it would need its own acceptance suite and would break the "Kandha" entry in the Audial
navigation.
