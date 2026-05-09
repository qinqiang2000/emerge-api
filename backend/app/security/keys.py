from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "ek_"
_KEY_BYTES = 24


def generate_key() -> str:
    """Return a fresh 192-bit API key as `ek_` + 32 url-safe chars."""
    return KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)


def sha256_key(plaintext: str) -> str:
    """Return lowercase-hex sha256 for key storage and lookup."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def key_prefix_display(plaintext: str) -> str:
    """Return the safe display prefix: `ek_` + 8 chars."""
    return plaintext[:11]


def key_hash_short(hash_hex: str) -> str:
    """Return the last 6 hex chars of a sha256 digest."""
    return hash_hex[-6:]
