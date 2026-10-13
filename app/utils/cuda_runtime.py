"""Make installed PyTorch CUDA libraries visible to CTranslate2 on Windows."""
import os
from pathlib import Path

_handles = []


def configure_cuda_dlls():
    if os.name == "nt":
        import torch
        library = Path(torch.__file__).parent / "lib"
        if library.exists():
            _handles.append(os.add_dll_directory(str(library)))


prepare_cuda = configure_cuda_dlls
