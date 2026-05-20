from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple, Optional

import dateparser
from babel.numbers import NumberFormatError, parse_decimal
from rapidfuzz import fuzz

from app.schemas.schema_field import SchemaField


class NormalizeResult(NamedTuple):
    equivalent: bool
    normalizer: Optional[str]


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_NUMBER_LOCALES = ("en_US", "en_GB", "de_DE", "zh_CN")


def _unicode_canonical(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = _WS.sub(" ", s.strip())
    return s


def _try_number(s: str) -> Optional[Decimal]:
    cleaned = s.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        pass
    for loc in _NUMBER_LOCALES:
        try:
            return Decimal(parse_decimal(s, locale=loc))
        except (NumberFormatError, InvalidOperation):
            continue
    return None


def _try_date(s: str, date_order: str = "YMD"):
    return dateparser.parse(s, settings={"DATE_ORDER": date_order})


def _field_type_str(field: SchemaField) -> str:
    t = field.type
    if t is None:
        return "string"
    return str(t.value if hasattr(t, "value") else t).lower()


def _field_format_str(field: SchemaField) -> Optional[str]:
    f = field.format
    if f is None:
        return None
    return str(f.value if hasattr(f, "value") else f).lower()


def normalize_equivalent(
    truth: Any,
    pred: Any,
    field: SchemaField,
) -> NormalizeResult:
    """Return (equivalent, normalizer_name) for a non-absent pair. The caller
    has already established that neither side is absent."""
    if truth is None or pred is None:
        return NormalizeResult(False, None)

    t = str(truth)
    p = str(pred)

    if t == p:
        return NormalizeResult(True, None)

    t_u = _unicode_canonical(t)
    p_u = _unicode_canonical(p)
    if t_u == p_u:
        return NormalizeResult(True, "unicode")

    field_type = _field_type_str(field)
    field_format = _field_format_str(field)

    if field_type in ("number", "integer", "decimal", "float"):
        td, pd_ = _try_number(t_u), _try_number(p_u)
        if td is not None and pd_ is not None and td == pd_:
            return NormalizeResult(True, "number")

    if field_type in ("date", "datetime") or field_format in (
        "date",
        "date-time",
        "time",
    ):
        order = getattr(field, "date_order", None) or "YMD"
        td_, pd_ = _try_date(t_u, order), _try_date(p_u, order)
        if td_ is not None and pd_ is not None and td_.date() == pd_.date():
            return NormalizeResult(True, "date")

    if field_type in ("money", "currency", "amount"):
        t_strip = re.sub(r"[^\d.,\-]", "", t_u)
        p_strip = re.sub(r"[^\d.,\-]", "", p_u)
        td, pd_ = _try_number(t_strip), _try_number(p_strip)
        if td is not None and pd_ is not None and td == pd_:
            return NormalizeResult(True, "money")

    if field_type in ("enum", "id", "code"):
        t_canon = _PUNCT.sub("", t_u).casefold()
        p_canon = _PUNCT.sub("", p_u).casefold()
        if t_canon == p_canon:
            return NormalizeResult(True, "enum")

    threshold = getattr(field, "fuzzy_threshold", None) or 95
    if fuzz.ratio(t_u, p_u) >= threshold:
        return NormalizeResult(True, "string-fuzzy")

    return NormalizeResult(False, None)
