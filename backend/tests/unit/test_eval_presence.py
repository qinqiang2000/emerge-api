from app.eval.presence import (
    DEFAULT_PROJECT_POLICY,
    is_absent,
    resolve_policy,
)
from app.schemas.schema_field import SchemaField


def test_none_is_absent_lenient() -> None:
    assert is_absent(None, "lenient") is True


def test_none_is_absent_strict() -> None:
    assert is_absent(None, "strict") is True


def test_empty_string_lenient() -> None:
    assert is_absent("", "lenient") is True


def test_empty_string_strict() -> None:
    # Behavioural difference: empty string is "present" under strict.
    assert is_absent("", "strict") is False


def test_na_literal_lenient() -> None:
    assert is_absent("  N/A  ", "lenient") is True


def test_na_literal_strict() -> None:
    assert is_absent("  N/A  ", "strict") is False


def test_zero_string_is_value_lenient() -> None:
    assert is_absent("0", "lenient") is False


def test_zero_int_is_value_lenient() -> None:
    assert is_absent(0, "lenient") is False


def test_resolve_policy_inherits_project_default() -> None:
    field = SchemaField(name="x", type="string", description="...")
    assert resolve_policy(field, "lenient") == "lenient"
    assert resolve_policy(field) == DEFAULT_PROJECT_POLICY


def test_resolve_policy_field_override_wins() -> None:
    field = SchemaField(
        name="x", type="string", description="...", absent_policy="strict",
    )
    assert resolve_policy(field, "lenient") == "strict"


def test_null_literal_lenient() -> None:
    assert is_absent("null", "lenient") is True
    assert is_absent("NULL", "lenient") is True


def test_none_literal_lenient() -> None:
    assert is_absent("none", "lenient") is True


def test_random_string_not_absent() -> None:
    assert is_absent("hello", "lenient") is False
    assert is_absent("hello", "strict") is False
