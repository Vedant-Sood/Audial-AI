"""Make installed PyTorch CUDA libraries visible to CTranslate2 on Windows."""
import os
import threading
from pathlib import Path

_handles = []
_directories = set()
_lock = threading.Lock()


def configure_cuda_dlls():
    if os.name == "nt":
        import torch
        library = Path(torch.__file__).parent / "lib"
        with _lock:
            if library.exists() and library not in _directories:
                _handles.append(os.add_dll_directory(str(library)))
                _directories.add(library)


prepare_cuda = configure_cuda_dlls
