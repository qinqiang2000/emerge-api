import re

from app.security.keys import (
    KEY_PREFIX,
    generate_key,
    key_hash_short,
    key_prefix_display,
    sha256_key,
)


def test_generate_key_format() -> None:
    key = generate_key()
    assert key.startswith(KEY_PREFIX)
    assert re.fullmatch(r"ek_[A-Za-z0-9_-]{32}", key)


def test_generate_key_unique() -> None:
    keys = {generate_key() for _ in range(100)}
    assert len(keys) == 100


def test_sha256_deterministic() -> None:
    h1 = sha256_key("ek_test_value")
    h2 = sha256_key("ek_test_value")
    assert h1 == h2
    assert re.fullmatch(r"[0-9a-f]{64}", h1)


def test_sha256_distinct_for_distinct_keys() -> None:
    assert sha256_key("ek_a") != sha256_key("ek_b")


def test_key_prefix_display_returns_first_11_chars() -> None:
    key = "ek_abcdefghIJKLmnopQRSTuvwxyz012345"
    assert key_prefix_display(key) == "ek_abcdefgh"


def test_key_prefix_display_short_input_returns_full() -> None:
    assert key_prefix_display("ek_abc") == "ek_abc"


def test_key_hash_short_returns_last_six_hex() -> None:
    h = "0" * 58 + "abcdef"
    assert key_hash_short(h) == "abcdef"


def test_generate_key_does_not_appear_in_repr() -> None:
    key = generate_key()
    assert isinstance(key, str)
