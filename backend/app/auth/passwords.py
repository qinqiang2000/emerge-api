"""Password hashing — stdlib `pbkdf2_hmac`, zero new dependency.

Decision (2026-06-03, `MEMORY:priorities-efficiency-experience-over-security`):
efficiency first / security a distant third → we deliberately do NOT pull in
`argon2-cffi` (a C-extension build dependency). pbkdf2-hmac-sha256 with a random
per-password salt is good-enough for an internal B2B tool and ships with no
install friction.

Stored format: `pbkdf2$<iterations>$<salt_hex>$<hash_hex>` — self-describing so
the iteration count can be bumped later without a migration (verify reads the
count off the stored string). High-entropy tokens (PAT / API keys) use plain
sha256 elsewhere; only low-entropy passwords need this slow salted KDF.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(plaintext: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(_ALGO, plaintext.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(plaintext: str, stored: str) -> bool:
    """Constant-time verify. Returns False on any malformed stored value
    rather than raising — a corrupt row should fail closed, not 500."""
    try:
        scheme, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac(_ALGO, plaintext.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)
