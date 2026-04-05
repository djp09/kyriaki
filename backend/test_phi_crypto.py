"""Tests for phi.keys, phi.crypto, and phi.profile_storage."""

from __future__ import annotations

import pytest

from phi.crypto import (
    PHIDecryptError,
    decrypt_bytes,
    decrypt_json,
    encrypt_bytes,
    encrypt_json,
    key_id_of,
    reencrypt,
)
from phi.keys import (
    KeyConfigError,
    KeyRing,
    decode_key,
    encode_key,
    generate_key,
    install_keyring,
    parse_keyring,
    reset_keyring,
)
from phi.profile_storage import decrypt_profile, encrypt_profile, hash_profile

# --- Key ring tests ---


def test_generate_and_encode_key_roundtrip() -> None:
    raw = generate_key()
    assert len(raw) == 32
    encoded = encode_key(raw)
    assert decode_key(encoded) == raw


def test_parse_keyring_single_key() -> None:
    raw = generate_key()
    ring = parse_keyring(f"k1:{encode_key(raw)}", "k1")
    assert ring.active() == ("k1", raw)
    assert ring.get("k1") == raw
    assert ring.get("nope") is None


def test_parse_keyring_multi_keys() -> None:
    k1 = encode_key(generate_key())
    k2 = encode_key(generate_key())
    ring = parse_keyring(f"k1:{k1}, k2:{k2}", "k2")
    assert ring.active_key_id == "k2"
    assert len(ring.keys) == 2


def test_parse_keyring_errors() -> None:
    with pytest.raises(KeyConfigError, match="empty"):
        parse_keyring("", "k1")
    with pytest.raises(KeyConfigError, match="Malformed"):
        parse_keyring("not-valid", "x")
    with pytest.raises(KeyConfigError, match="Duplicate"):
        k = encode_key(generate_key())
        parse_keyring(f"k1:{k},k1:{k}", "k1")
    with pytest.raises(KeyConfigError, match="Active key id"):
        k = encode_key(generate_key())
        parse_keyring(f"k1:{k}", "missing")


def test_decode_key_wrong_length() -> None:
    import base64

    bad = base64.urlsafe_b64encode(b"shortkey").decode("ascii")
    with pytest.raises(KeyConfigError):
        decode_key(bad)


# --- Test fixtures: install a deterministic key ring ---


@pytest.fixture(autouse=True)
def _test_keyring() -> None:
    k1 = generate_key()
    k2 = generate_key()
    ring = KeyRing(keys={"k1": k1, "k2": k2}, active_key_id="k1")
    install_keyring(ring)
    yield
    reset_keyring()


# --- Crypto roundtrip tests ---


def test_encrypt_decrypt_roundtrip_bytes() -> None:
    plaintext = b"some PHI bytes with unicode: 65\xc2\xb0"
    blob = encrypt_bytes(plaintext)
    assert blob != plaintext
    assert decrypt_bytes(blob) == plaintext


def test_encrypt_decrypt_json() -> None:
    payload = {"name": "Jane Doe", "age": 64, "labs": {"wbc": 5.2}}
    blob = encrypt_json(payload)
    assert decrypt_json(blob) == payload


def test_key_id_is_embedded() -> None:
    blob = encrypt_bytes(b"x")
    assert key_id_of(blob) == "k1"


def test_nonce_is_random() -> None:
    # Same plaintext → different ciphertexts (random nonce).
    a = encrypt_bytes(b"same")
    b = encrypt_bytes(b"same")
    assert a != b
    assert decrypt_bytes(a) == decrypt_bytes(b) == b"same"


def test_tamper_detection() -> None:
    blob = encrypt_bytes(b"secret")
    # Flip a byte in the ciphertext region
    corrupted = bytearray(blob)
    corrupted[-1] ^= 0x01
    with pytest.raises(PHIDecryptError, match="GCM tag"):
        decrypt_bytes(bytes(corrupted))


def test_wrong_key_fails() -> None:
    blob = encrypt_bytes(b"secret")
    # Install a key ring without k1
    k2 = generate_key()
    install_keyring(KeyRing(keys={"k2": k2}, active_key_id="k2"))
    with pytest.raises(PHIDecryptError, match="not in active key ring"):
        decrypt_bytes(blob)


def test_truncated_blob_fails() -> None:
    with pytest.raises(PHIDecryptError):
        decrypt_bytes(b"\x01")


def test_unsupported_version_fails() -> None:
    with pytest.raises(PHIDecryptError, match="unsupported ciphertext version"):
        decrypt_bytes(b"\x99\x00" + b"\x00" * 12 + b"ct")


def test_associated_data_must_match() -> None:
    blob = encrypt_bytes(b"data", associated_data=b"patient-id-42")
    assert decrypt_bytes(blob, associated_data=b"patient-id-42") == b"data"
    with pytest.raises(PHIDecryptError):
        decrypt_bytes(blob, associated_data=b"patient-id-9")


# --- Rotation ---


def test_reencrypt_switches_to_active_key() -> None:
    # Encrypt under k1
    blob_k1 = encrypt_bytes(b"payload")
    assert key_id_of(blob_k1) == "k1"

    # Switch active key to k2 (keeping k1 around for decrypt)
    k1 = generate_key()
    k2 = generate_key()
    # We need the actual k1 to decrypt the blob we just made, so get it from current ring
    # and rebuild with k2 active.
    from phi.keys import get_keyring

    current = get_keyring()
    new_ring = KeyRing(
        keys={"k1": current.keys["k1"], "k2": k2},
        active_key_id="k2",
    )
    install_keyring(new_ring)

    # k1 blob still decrypts
    assert decrypt_bytes(blob_k1) == b"payload"

    # After reencrypt, it carries the k2 key_id
    blob_k2 = reencrypt(blob_k1)
    assert key_id_of(blob_k2) == "k2"
    assert decrypt_bytes(blob_k2) == b"payload"

    # keep unused vars referenced to satisfy linters
    del k1


# --- Profile storage ---


def test_profile_storage_roundtrip() -> None:
    profile = {
        "cancer_type": "NSCLC",
        "age": 62,
        "biomarkers": ["EGFR+"],
        "location_zip": "94110",
    }
    blob, key_id, h = encrypt_profile(profile)
    assert key_id == "k1"
    assert len(h) == 64  # sha256 hex
    assert hash_profile(profile) == h
    assert decrypt_profile(blob, expected_hash=h) == profile


def test_profile_hash_is_stable_under_key_order() -> None:
    a = {"a": 1, "b": 2}
    b = {"b": 2, "a": 1}
    assert hash_profile(a) == hash_profile(b)


def test_profile_hash_mismatch_raises() -> None:
    profile = {"cancer_type": "NSCLC"}
    blob, _, _ = encrypt_profile(profile)
    with pytest.raises(ValueError, match="hash mismatch"):
        decrypt_profile(blob, expected_hash="0" * 64)
