"""Actual Windows credential roundtrip, using a disposable unique test target."""

import sys
import uuid

import pytest


@pytest.mark.skipif(
    sys.platform != "win32", reason="Requires the actual Windows Credential Manager API"
)
def test_credential_roundtrip_never_uses_plaintext_settings(monkeypatch):
    from app.utils import credentials
    from app.utils.paths import data_root

    monkeypatch.setattr(credentials, "TARGET", "AudialAI/pytest/" + uuid.uuid4().hex)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    token = "hf_" + "fixturecredential" * 3
    try:
        assert credentials.get_token() is None
        credentials.save_token(token)
        assert credentials.get_token() == token
        assert not any(
            token.encode() in file.read_bytes()
            for file in data_root().rglob("*")
            if file.is_file()
        )
    finally:
        credentials.forget_token()
    assert credentials.get_token() is None
