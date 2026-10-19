"""Per-user Windows Credential Manager storage; never write tokens to settings."""

import os
import sys

TARGET = "AudialAI/HuggingFace"


def _windows_api():
    if sys.platform != "win32":
        raise OSError(
            "Secure token storage uses Windows Credential Manager. On other systems provide HF_TOKEN in the worker environment."
        )
    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    return ctypes, Credential, api


def save_token(token):
    token = token.strip()
    if (
        not token.startswith("hf_")
        or len(token) > 1024
        or any(c.isspace() for c in token)
    ):
        raise ValueError("Enter a valid Hugging Face read token, beginning with hf_.")
    ctypes, Credential, api = _windows_api()
    encoded = token.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = Credential(
        Type=1,
        TargetName=TARGET,
        UserName="HuggingFace",
        CredentialBlobSize=len(encoded),
        CredentialBlob=blob,
        Persist=2,
    )
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise OSError("Windows could not save the token in Credential Manager.")


def get_token():
    token = os.environ.get("HF_TOKEN")
    if token or sys.platform != "win32":
        return token
    ctypes, Credential, api = _windows_api()
    pointer = ctypes.POINTER(Credential)()
    if not api.CredReadW(TARGET, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise OSError(
            "Windows could not read the saved model credential. Save it again in Setup."
        )
    try:
        return ctypes.string_at(
            pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
        ).decode("utf-16-le")
    finally:
        api.CredFree(pointer)


def forget_token():
    ctypes, _, api = _windows_api()
    if not api.CredDeleteW(TARGET, 1, 0) and ctypes.get_last_error() != 1168:
        raise OSError("Windows could not remove the saved model credential.")
