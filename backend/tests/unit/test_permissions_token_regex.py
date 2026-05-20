"""Guard the secret-literal regex against `\\btoken\\b` over-match.

The prior `\\btoken\\b` pattern tripped any string containing the word "token"
— legit identifiers like `pagination_token`, `cancel_token`, `csrf_token` were
denied. The pattern is anchored to credential-shaped prefixes
(api/access/auth/bearer) so only token-bearing field names trigger the gate.
"""

from app.chat.permissions import _is_secret_literal


# ── still detected ────────────────────────────────────────────────────────


def test_api_token_field_detected() -> None:
    assert _is_secret_literal("api_token=abc")
    assert _is_secret_literal("api-token: xyz")


def test_access_token_field_detected() -> None:
    assert _is_secret_literal("access_token=xyz")
    assert _is_secret_literal("ACCESS_TOKEN=xyz")


def test_auth_token_field_detected() -> None:
    assert _is_secret_literal("auth_token=xyz")


def test_bearer_token_field_detected() -> None:
    assert _is_secret_literal("Authorization: Bearer\nbearer_token=xyz")


def test_existing_patterns_still_detected() -> None:
    # Regression: other secret-literal patterns must still fire.
    assert _is_secret_literal("export api_key=sk-xxxx")
    assert _is_secret_literal("provider_key=...")
    assert _is_secret_literal("secret_key=...")
    assert _is_secret_literal("secret=...")


# ── no longer over-match ──────────────────────────────────────────────────


def test_pagination_token_not_secret() -> None:
    assert not _is_secret_literal("pagination_token=abc")
    assert not _is_secret_literal("next_pagination_token: xyz")


def test_cancel_token_not_secret() -> None:
    assert not _is_secret_literal("cancel_token=abc")


def test_csrf_token_not_secret() -> None:
    assert not _is_secret_literal("csrf_token=abc")


def test_bare_token_word_not_secret() -> None:
    # The bare word "token" inside a doc filename or sentence should not trip.
    assert not _is_secret_literal("docs/token-design.md")
    assert not _is_secret_literal("The token returned by the page parameter.")
