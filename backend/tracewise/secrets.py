"""Encrypts connected-account credentials at rest (Fernet, key from TW_SECRET_KEY)."""

import os

from cryptography.fernet import Fernet

_fernet = Fernet(os.environ["TW_SECRET_KEY"].encode()) if os.environ.get("TW_SECRET_KEY") else None


def encrypt(value: str) -> bytes:
    if not _fernet:
        raise RuntimeError("TW_SECRET_KEY is not set; can't store credentials")
    return _fernet.encrypt(value.encode())


def decrypt(token: bytes) -> str:
    if not _fernet:
        raise RuntimeError("TW_SECRET_KEY is not set; can't read credentials")
    return _fernet.decrypt(bytes(token)).decode()
