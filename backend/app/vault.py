"""Encrypts cloud credentials before they are stored, and decrypts them only to run a sync.

Uses Fernet (AES-128 in CBC mode with an HMAC-SHA256 signature) from the `cryptography`
library. The key lives only in the server's environment (CREDENTIALS_KEY), never in the
database, so a copy of the database alone does not reveal anyone's cloud keys.

Make a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os

from cryptography.fernet import Fernet, InvalidToken

from .cloud import CloudError


def _fernet() -> Fernet:
    key = os.environ.get("CREDENTIALS_KEY")
    if not key:
        raise CloudError("Live cloud connections are not switched on for this server yet (CREDENTIALS_KEY is missing).")
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise CloudError("The saved keys could not be unlocked. Remove this account and connect it again.") from None
