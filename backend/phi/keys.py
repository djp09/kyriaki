"""PHI encryption key management and rotation.

Keys are loaded from the environment so they can be rotated without a
code change. The key material is *not* stored in the database.

Environment configuration
-------------------------
``KYRIAKI_PHI_ENCRYPTION_KEYS``
    Comma-separated list of ``<key_id>:<base64_32byte_key>`` pairs. All
    keys listed here can be used to decrypt historical ciphertexts.

``KYRIAKI_PHI_ACTIVE_KEY_ID``
    The key ID used for new encryptions. Must appear in
    ``KYRIAKI_PHI_ENCRYPTION_KEYS``.

Example::

    export KYRIAKI_PHI_ENCRYPTION_KEYS="k1:<b64>,k2:<b64>"
    export KYRIAKI_PHI_ACTIVE_KEY_ID="k2"

Rotation path
-------------
1. Generate a new key (``python -m phi.keys generate``) and add it to
   ``KYRIAKI_PHI_ENCRYPTION_KEYS`` without removing the old one.
2. Flip ``KYRIAKI_PHI_ACTIVE_KEY_ID`` to the new key ID and restart.
3. Re-encrypt historical rows via the ``rotate_profile_encryption`` helper
   (lazy: rows are re-encrypted the next time they are written).
4. Once all rows carry the new key ID, drop the retired key.

This module deliberately has no persistent state: upstream systems
(KMS/Vault/AWS KMS) can replace the env loader by monkey-patching
``load_keys_from_env``.
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass

KEY_BYTES = 32  # AES-256


class KeyConfigError(RuntimeError):
    """Raised when PHI key configuration is missing or malformed."""


@dataclass(frozen=True)
class KeyRing:
    """A set of keys indexed by ID, with one designated active key."""

    keys: dict[str, bytes]
    active_key_id: str

    def active(self) -> tuple[str, bytes]:
        return self.active_key_id, self.keys[self.active_key_id]

    def get(self, key_id: str) -> bytes | None:
        return self.keys.get(key_id)


def generate_key() -> bytes:
    """Generate a fresh 32-byte AES-256 key."""
    return secrets.token_bytes(KEY_BYTES)


def encode_key(raw: bytes) -> str:
    if len(raw) != KEY_BYTES:
        raise KeyConfigError(f"Key must be {KEY_BYTES} bytes, got {len(raw)}")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_key(encoded: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except Exception as e:  # pragma: no cover - base64 errors bubble as ValueError
        raise KeyConfigError(f"Invalid base64 key material: {e}") from e
    if len(raw) != KEY_BYTES:
        raise KeyConfigError(f"Decoded key must be {KEY_BYTES} bytes, got {len(raw)}")
    return raw


def parse_keyring(keys_env: str, active_key_id: str) -> KeyRing:
    """Parse a ``KYRIAKI_PHI_ENCRYPTION_KEYS`` value into a KeyRing."""
    if not keys_env.strip():
        raise KeyConfigError("KYRIAKI_PHI_ENCRYPTION_KEYS is empty")
    keys: dict[str, bytes] = {}
    for entry in keys_env.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise KeyConfigError(f"Malformed key entry {entry!r} (expected '<key_id>:<base64>')")
        key_id, encoded = entry.split(":", 1)
        key_id = key_id.strip()
        encoded = encoded.strip()
        if not key_id:
            raise KeyConfigError("Empty key_id in KYRIAKI_PHI_ENCRYPTION_KEYS")
        if key_id in keys:
            raise KeyConfigError(f"Duplicate key_id: {key_id}")
        keys[key_id] = decode_key(encoded)
    if not keys:
        raise KeyConfigError("No keys parsed from KYRIAKI_PHI_ENCRYPTION_KEYS")
    if active_key_id not in keys:
        raise KeyConfigError(f"Active key id {active_key_id!r} not present in KYRIAKI_PHI_ENCRYPTION_KEYS")
    return KeyRing(keys=keys, active_key_id=active_key_id)


def load_keys_from_env() -> KeyRing:
    """Load the key ring from environment variables.

    Raises KeyConfigError if configuration is missing. Callers that want
    a dev-time fallback should catch this explicitly.
    """
    keys_env = os.environ.get("KYRIAKI_PHI_ENCRYPTION_KEYS", "")
    active = os.environ.get("KYRIAKI_PHI_ACTIVE_KEY_ID", "")
    if not keys_env or not active:
        raise KeyConfigError("KYRIAKI_PHI_ENCRYPTION_KEYS and KYRIAKI_PHI_ACTIVE_KEY_ID must be set")
    return parse_keyring(keys_env, active)


# Module-level cache. Call reset_keyring() after changing env in tests.
_cached_keyring: KeyRing | None = None


def get_keyring() -> KeyRing:
    global _cached_keyring
    if _cached_keyring is None:
        _cached_keyring = load_keys_from_env()
    return _cached_keyring


def reset_keyring() -> None:
    """Forget the cached key ring (used by tests and after rotation)."""
    global _cached_keyring
    _cached_keyring = None


def install_keyring(keyring: KeyRing) -> None:
    """Directly install a key ring. Primarily for tests and KMS integrations."""
    global _cached_keyring
    _cached_keyring = keyring


if __name__ == "__main__":  # pragma: no cover - operator CLI
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "generate":
        key_id = sys.argv[2] if len(sys.argv) >= 3 else "k1"
        encoded = encode_key(generate_key())
        print(f"{key_id}:{encoded}")
    else:
        print("Usage: python -m phi.keys generate [key_id]")
        sys.exit(1)
