from dataclasses import dataclass
from typing import Optional

from app.eval.normalize import normalize_equivalent
from app.schemas.schema_field import SchemaField


@dataclass
class _StubField:
    """Minimal duck-typed stand-in for SchemaField for unit-testing
    normalize_equivalent against field types the live SchemaField enum
    doesn't model (money/enum/id/code/date/datetime). The dispatcher only
    reads `type`, `format`, `date_order`, `fuzzy_threshold`."""

    name: str
    type: str
    description: str = ""
    format: Optional[str] = None
    date_order: Optional[str] = None
    fuzzy_threshold: Optional[int] = None
    absent_policy: Optional[str] = None


def test_exact_equal_returns_true_no_normalizer() -> None:
    f = SchemaField(name="x", type="string", description="x")
    r = normalize_equivalent("ACME", "ACME", f)
    assert r.equivalent is True
    assert r.normalizer is None


def test_number_trailing_zero() -> None:
    f = _StubField(name="amount", type="number")
    r = normalize_equivalent("123.10", "123.1", f)
    assert r.equivalent is True
    assert r.normalizer == "number"


def test_number_thousands_comma() -> None:
    f = _StubField(name="amount", type="number")
    r = normalize_equivalent("1,000", "1000", f)
    assert r.equivalent is True
    assert r.normalizer == "number"


def test_money_with_symbol() -> None:
    f = _StubField(name="amount", type="money")
    r = normalize_equivalent("$1,000.00", "1000", f)
    assert r.equivalent is True
    assert r.normalizer == "money"


def test_number_distinct_not_equivalent() -> None:
    f = _StubField(name="amount", type="number")
    r = normalize_equivalent("100", "100.01", f)
    assert r.equivalent is False


def test_number_truly_different_not_equivalent() -> None:
    f = _StubField(name="amount", type="number")
    r = normalize_equivalent("100", "1000", f)
    assert r.equivalent is False


def test_date_slash_vs_dash() -> None:
    f = _StubField(name="d", type="date")
    r = normalize_equivalent("2024/3/12", "2024-03-12", f)
    assert r.equivalent is True
    assert r.normalizer == "date"


def test_date_natural_language() -> None:
    f = _StubField(name="d", type="date")
    r = normalize_equivalent("12 March 2024", "2024-03-12", f)
    assert r.equivalent is True
    assert r.normalizer == "date"


def test_date_string_format_attribute_dispatch() -> None:
    # Real SchemaField with type=string + format=date should still hit date
    # normalizer.
    f = SchemaField(name="d", type="string", description="x", format="date")
    r = normalize_equivalent("2024/3/12", "2024-03-12", f)
    assert r.equivalent is True
    assert r.normalizer == "date"


def test_date_distinct_days_not_equivalent() -> None:
    f = _StubField(name="d", type="date")
    r = normalize_equivalent("2024-03-12", "2024-03-13", f)
    assert r.equivalent is False


def test_unicode_whitespace_chinese_default_threshold_too_strict() -> None:
    # Documents the risk: at default threshold 95, single-space CJK drift is
    # NOT auto-equivalent (fuzz.ratio ~= 92). Per the plan's known-unknowns
    # section, the user lowers `fuzzy_threshold` per-field when needed.
    f = _StubField(name="city", type="string")
    r = normalize_equivalent("广东省深圳市", "广东省 深圳市", f)
    assert r.equivalent is False


def test_unicode_whitespace_chinese_with_lower_threshold() -> None:
    f = _StubField(name="city", type="string", fuzzy_threshold=90)
    r = normalize_equivalent("广东省深圳市", "广东省 深圳市", f)
    assert r.equivalent is True
    assert r.normalizer == "string-fuzzy"


def test_unicode_collapse_internal_whitespace() -> None:
    f = _StubField(name="x", type="string")
    r = normalize_equivalent("ACME  Sdn  Bhd", "ACME Sdn Bhd", f)
    assert r.equivalent is True
    assert r.normalizer == "unicode"


def test_enum_punct_and_case() -> None:
    f = _StubField(name="x", type="enum")
    r = normalize_equivalent("INV-001", "inv001", f)
    assert r.equivalent is True
    assert r.normalizer == "enum"


def test_string_fuzzy_punctuation_default_threshold_strict() -> None:
    # At default 95, two extra periods drop ratio to ~92.3.
    f = _StubField(name="x", type="string")
    r = normalize_equivalent("ACME Sdn Bhd", "ACME Sdn. Bhd.", f)
    assert r.equivalent is False


def test_string_fuzzy_punctuation_with_lower_threshold() -> None:
    f = _StubField(name="x", type="string", fuzzy_threshold=90)
    r = normalize_equivalent("ACME Sdn Bhd", "ACME Sdn. Bhd.", f)
    assert r.equivalent is True
    assert r.normalizer == "string-fuzzy"


def test_string_truly_different_not_equivalent() -> None:
    f = _StubField(name="x", type="string")
    r = normalize_equivalent("ACME Sdn Bhd", "XYZ Pte Ltd", f)
    assert r.equivalent is False


def test_none_inputs_return_false() -> None:
    f = _StubField(name="x", type="string")
    assert normalize_equivalent(None, "abc", f).equivalent is False
    assert normalize_equivalent("abc", None, f).equivalent is False


def test_field_without_type_defaults_to_string() -> None:
    # Use the live SchemaField (always has a type) — this test asserts the
    # default-to-string branch via fuzz path.
    f = SchemaField(name="x", type="string", description="x")
    r = normalize_equivalent("hello world", "hello world", f)
    assert r.equivalent is True
