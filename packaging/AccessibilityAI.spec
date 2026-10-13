# Run on Windows: .venv\Scripts\python -m PyInstaller packaging\AccessibilityAI.spec
from pathlib import Path
from importlib.util import find_spec
from PyInstaller.utils.hooks import collect_all, collect_submodules
project = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []
for package in ['faster_whisper', 'ctranslate2', 'mediapipe', 'speechbrain', 'sounddevice', 'pyttsx3', 'torchaudio', 'onnxruntime']:
    if find_spec(package) is None:
        continue
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('training') + collect_submodules('scripts')
datas += [(str(project / 'assets'), 'assets'), (str(project / 'training'), 'training'),
          (str(project / 'browser'), 'browser'), (str(project / 'docs'), 'docs'),
          (str(project / 'models'), 'models')]
icon_path = project / 'assets' / 'icon.ico'
icon = str(icon_path) if icon_path.is_file() else None
a = Analysis([str(project / 'launcher.py')], pathex=[str(project)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             hookspath=[str(project / 'packaging' / 'hooks')],
             excludes=['tkinter', 'IPython', 'notebook'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AccessibilityAI', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=icon)
# A console-capable worker preserves stdout for QProcess logs. The primary
# desktop executable has no console; it launches this helper for explicit jobs.
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AccessibilityAIWorker', debug=False,
             bootloader_ignore_signals=False, strip=False, upx=False, console=True,
             icon=icon)
coll = COLLECT(exe, worker, a.binaries, a.datas, strip=False, upx=False, name='AccessibilityAI')
