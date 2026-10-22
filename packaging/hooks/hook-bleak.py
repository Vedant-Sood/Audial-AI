# PyInstaller hook: bleak and its platform backends (WinRT on Windows, CoreBluetooth on macOS, BlueZ/dbus on Linux).
from PyInstaller.compat import is_darwin, is_win
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = collect_all('bleak')
if is_win:
    for name in ('winrt', 'bleak_winrt'):
        try:
            hiddenimports += collect_submodules(name)
        except Exception:
            pass
elif is_darwin:
    hiddenimports += ['objc', 'CoreBluetooth', 'Foundation', 'libdispatch']
else:
    hiddenimports += ['dbus_fast', 'dbus_fast.aio', 'dbus_fast.auth']
