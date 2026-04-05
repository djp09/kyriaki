"""Application-layer AES-256-GCM encryption for patient PHI.

Ciphertext format (all binary, stored in a ``bytea`` column)::

    [1]  version byte           — currently 0x01
    [1]  key-id length (N)
    [N]  key-id utf-8 bytes
    [12] nonce
    [..] AES-GCM ciphertext || 16-byte tag

The key-id is stored alongside the ciphertext so decryption can pick the
correct key out of the active key ring (see ``phi.keys``). A new key can
be introduced at any time; old rows decrypt with their original key until
they are re-encrypted by ``reencrypt``.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from phi.keys import KEY_BYTES, KeyRing, get_keyring

FORMAT_VERSION = 0x01
NONCE_BYTES = 12


class PHIDecryptError(RuntimeError):
    """Raised when ciphertext cannot be decrypted (bad key, tamper, corruption)."""


def _pack(key_id: str, nonce: bytes, ciphertext: bytes) -> bytes:
    kid_bytes = key_id.encode("utf-8")
    if len(kid_bytes) > 255:
        raise ValueError("key_id must be <= 255 bytes")
    return bytes([FORMAT_VERSION, len(kid_bytes)]) + kid_bytes + nonce + ciphertext


def _unpack(blob: bytes) -> tuple[str, bytes, bytes]:
    if len(blob) < 2 + NONCE_BYTES:
        raise PHIDecryptError("ciphertext too short")
    version = blob[0]
    if version != FORMAT_VERSION:
        raise PHIDecryptError(f"unsupported ciphertext version: {version}")
    kid_len = blob[1]
    offset = 2
    if len(blob) < offset + kid_len + NONCE_BYTES:
        raise PHIDecryptError("ciphertext truncated")
    key_id = blob[offset : offset + kid_len].decode("utf-8")
    offset += kid_len
    nonce = blob[offset : offset + NONCE_BYTES]
    offset += NONCE_BYTES
    ciphertext = blob[offset:]
    return key_id, nonce, ciphertext


def encrypt_bytes(
    plaintext: bytes,
    *,
    keyring: KeyRing | None = None,
    associated_data: bytes | None = None,
) -> bytes:
    """Encrypt plaintext with the active key. Optional AAD is authenticated but not encrypted."""
    keyring = keyring or get_keyring()
    key_id, key = keyring.active()
    if len(key) != KEY_BYTES:
        raise ValueError("key must be 32 bytes for AES-256-GCM")
    aes = AESGCM(key)
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = aes.encrypt(nonce, plaintext, associated_data)
    return _pack(key_id, nonce, ciphertext)


def decrypt_bytes(
    blob: bytes,
    *,
    keyring: KeyRing | None = None,
    associated_data: bytes | None = None,
) -> bytes:
    keyring = keyring or get_keyring()
    key_id, nonce, ciphertext = _unpack(blob)
    key = keyring.get(key_id)
    if key is None:
        raise PHIDecryptError(f"key_id {key_id!r} not in active key ring — cannot decrypt")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data)
    except Exception as e:
        raise PHIDecryptError(f"GCM tag verification failed: {e}") from e


def encrypt_json(
    obj: Any,
    *,
    keyring: KeyRing | None = None,
    associated_data: bytes | None = None,
) -> bytes:
    """JSON-serialise ``obj`` and encrypt it."""
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return encrypt_bytes(data, keyring=keyring, associated_data=associated_data)


def decrypt_json(
    blob: bytes,
    *,
    keyring: KeyRing | None = None,
    associated_data: bytes | None = None,
) -> Any:
    data = decrypt_bytes(blob, keyring=keyring, associated_data=associated_data)
    return json.loads(data.decode("utf-8"))


def key_id_of(blob: bytes) -> str:
    """Return the key ID that encrypted ``blob`` (without decrypting)."""
    key_id, _, _ = _unpack(blob)
    return key_id


def reencrypt(
    blob: bytes,
    *,
    keyring: KeyRing | None = None,
    associated_data: bytes | None = None,
) -> bytes:
    """Decrypt then re-encrypt with the currently active key (rotation helper)."""
    plaintext = decrypt_bytes(blob, keyring=keyring, associated_data=associated_data)
    return encrypt_bytes(plaintext, keyring=keyring, associated_data=associated_data)
