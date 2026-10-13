"""Package the installed wheel distribution behind the webrtcvad import.

The upstream hook assumes a distribution named ``webrtcvad``. This application
uses ``webrtcvad-wheels`` for native Windows binaries; its module and extension
keep the old import names, while its runtime version reads wheel metadata.
"""
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("webrtcvad-wheels")
hiddenimports = ["_webrtcvad"]
