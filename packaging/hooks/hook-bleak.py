# PyInstaller hook: bleak and its platform backend (WinRT on Windows, CoreBluetooth on macOS, BlueZ/dbus-fast on Linux).
# The module lists live in packaging/kandha_bluetooth.py, shared with AccessibilityAI.spec; a missing backend stops
# the build with a message instead of being skipped.
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_found = spec_from_file_location('kandha_bluetooth', Path(__file__).resolve().parents[1] / 'kandha_bluetooth.py')
_helper = module_from_spec(_found)
_found.loader.exec_module(_helper)
datas, binaries, hiddenimports = _helper.collect()
