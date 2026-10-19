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
hiddenimports += collect_submodules('training')
# Developer browser/benchmark tooling must never bundle Playwright or Node.
hiddenimports += [name for name in collect_submodules('scripts') if name not in {
    'scripts.verify_browser', 'scripts.benchmark_browser', 'scripts.benchmark_ui',
    'scripts.evaluate_voice_models', 'scripts.package_extension', 'scripts.verify_ui',
    'scripts.verify_browser_ui'}]
hiddenimports += collect_submodules('accessibilityai_upgrade')
if find_spec('pyannote') is not None and find_spec('pyannote.audio') is not None:
    d, b, h = collect_all('pyannote.audio')
    datas += d
    binaries += b
    hiddenimports += h
# Keep upstream distribution metadata and license files for the runtime SBOM.
from PyInstaller.utils.hooks import copy_metadata
for package in ['faster-whisper', 'speechbrain', 'torch', 'torchaudio', 'ctranslate2',
                'mediapipe', 'PySide6', 'numpy', 'scipy', 'scikit-learn', 'soundfile',
                'sounddevice', 'pyttsx3', 'pyannote.audio', 'filelock']:
    try:
        datas += copy_metadata(package, recursive=True)
    except Exception:
        if package != 'pyannote.audio':
            raise
datas += [(str(project / 'assets'), 'assets'), (str(project / 'training'), 'training'),
          (str(project / 'browser'), 'browser'), (str(project / 'docs'), 'docs'),
          (str(project / 'models'), 'models')]
icon_path = project / 'assets' / 'icon.ico'
icon = str(icon_path) if icon_path.is_file() else None
a = Analysis([str(project / 'launcher.py')], pathex=[str(project)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             hookspath=[str(project / 'packaging' / 'hooks')],
             excludes=['tkinter', 'IPython', 'notebook', 'playwright', 'pytest'], noarchive=False)
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
