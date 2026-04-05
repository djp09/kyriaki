"""Helpers to write/read the encrypted patient-profile blob.

Plain-text columns on ``patient_profiles`` remain authoritative for now;
this module only populates and reads the new ``profile_encrypted`` /
``encryption_key_id`` / ``profile_hash`` columns. Follow-up migration will
drop the plaintext columns once callers have cut over.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from phi.crypto import decrypt_bytes, encrypt_bytes, key_id_of
from phi.keys import KeyRing


def _canonical_json(profile: Mapping[str, Any]) -> bytes:
    """Canonical JSON for stable hashing and dedup."""
    return json.dumps(profile, separators=(",", ":"), sort_keys=True).encode("utf-8")


def hash_profile(profile: Mapping[str, Any]) -> str:
    """SHA-256 hex digest of the canonical JSON profile (integrity + dedup)."""
    return hashlib.sha256(_canonical_json(profile)).hexdigest()


def encrypt_profile(
    profile: Mapping[str, Any],
    *,
    keyring: KeyRing | None = None,
) -> tuple[bytes, str, str]:
    """Encrypt the profile dict.

    Returns ``(ciphertext_blob, key_id, profile_hash)``. The caller
    persists all three to ``patient_profiles``. The hash is computed over
    the *plaintext* canonical JSON so it can be recomputed after
    decryption for integrity checks.
    """
    plaintext = _canonical_json(profile)
    blob = encrypt_bytes(plaintext, keyring=keyring)
    return blob, key_id_of(blob), hashlib.sha256(plaintext).hexdigest()


def decrypt_profile(
    blob: bytes,
    *,
    keyring: KeyRing | None = None,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    """Decrypt a profile blob. Optionally verify the stored hash."""
    plaintext = decrypt_bytes(blob, keyring=keyring)
    if expected_hash is not None:
        actual = hashlib.sha256(plaintext).hexdigest()
        if actual != expected_hash:
            raise ValueError("decrypted profile hash mismatch — possible tampering or corruption")
    return json.loads(plaintext.decode("utf-8"))
