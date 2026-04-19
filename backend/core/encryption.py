"""
NeuralEdge AI - AES-256-GCM Encryption for API Keys

Derives a 256-bit key from ENCRYPTION_MASTER_KEY via HKDF-SHA256,
then encrypts/decrypts with AESGCM (96-bit random nonce).

Store (ciphertext, nonce) together -- both are needed for decryption.
"""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import settings

_NONCE_BYTES = 12   # 96-bit nonce (NIST recommended for AES-GCM)
_KEY_BYTES = 32     # 256-bit key
_HKDF_INFO = b"neuraledge-api-key-encryption"


def derive_key() -> bytes:
    """Derive a 256-bit AES key from the master key via HKDF-SHA256.

    The master key is treated as raw key material (hex-encoded in env).
    HKDF adds domain separation so the same master key used elsewhere
    produces a different derived key.
    """
    master = settings.ENCRYPTION_MASTER_KEY.encode("utf-8")
    hkdf = HKDF(
        algorithm=SHA256(),
        length=_KEY_BYTES,
        salt=None,  # Static salt=None is fine when master key has high entropy
        info=_HKDF_INFO,
    )
    return hkdf.derive(master)


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt a plaintext string with AES-256-GCM.

    Returns:
        (ciphertext, nonce) -- both ``bytes``. Store them together
        (e.g. concatenated or in separate DB columns).
    """
    key = derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    """Decrypt AES-256-GCM ciphertext back to a plaintext string.

    Raises ``cryptography.exceptions.InvalidTag`` if the key, nonce,
    or ciphertext has been tampered with.
    """
    key = derive_key()
    aesgcm = AESGCM(key)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode("utf-8")
