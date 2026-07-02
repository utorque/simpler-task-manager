"""Symmetric encryption for secrets at rest (mailbox passwords).

The Fernet key is derived from the app's SECRET_KEY (sha256 → urlsafe base64),
so a leaked tasks.db alone does not leak mailbox passwords. Trade-off (flagged
in the PrePRD): rotating SECRET_KEY invalidates stored mailbox passwords —
they must be re-entered.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401  (re-exported)


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode('utf-8')).decode('ascii')


def decrypt_secret(token: str, secret_key: str) -> str:
    return _fernet(secret_key).decrypt(token.encode('ascii')).decode('utf-8')
