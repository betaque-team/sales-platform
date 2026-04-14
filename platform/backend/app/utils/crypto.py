"""Credential encryption/decryption using Fernet symmetric encryption."""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the configured encryption key or JWT secret."""
    settings = get_settings()
    secret = settings.credential_encryption_key or settings.jwt_secret
    # Derive a 32-byte key via SHA-256, then base64-encode for Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a credential string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a credential string."""
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
