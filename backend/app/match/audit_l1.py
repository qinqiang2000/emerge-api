"""L1 audit fast path — deterministic rule checks over already-extracted fields.

A rule that carries a structured `check` spec (`L1Check`: eq / range) AND whose
field references happen to resolve against the extracted fields in hand is
decided here for free — no judge trip, fully explainable reason string. Anything
short of that (no spec, doc unresolvable, field absent, values unparsable for a
range) returns ``None`` and the WHOLE rule goes to the LLM judge unchanged.

Philosophy guards (the design's red lines):
- Extraction is never a prerequisite — a missing field silently defers to the
  judge; this module must never surface an "extract first" error.
- Pure function over field VALUES: no provider, no IO, no images, no bbox.
- Normalization is aliased from `app/match/judge.py` (which aliases
  `app/eval/normalize`) so matching/eval/audit share one number/date semantics.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.match.judge import try_date, try_number, unicode_canonical
from app.schemas.match import AuditEvidence, AuditRule, L1FieldRef, L1Operand, RuleCheck

# Sentinel distinguishing "operand failed to resolve → defer to judge" from a
# legitimately resolved value (which is always str after _as_text).
_UNRESOLVED = object()


def _resolve_doc(name: str, doc_fields: dict[str, dict]) -> Optional[str]:
    """Resolved FILENAME for the doc named `name`: exact filename match first,
    else a UNIQUE substring match ("报价单" → `报价单.pdf`). 0 or >1 hits →
    None. Returns the filename (not the fields) so evidence can cite it."""
    if name in doc_fields:
        return name
    hits = [fn for fn in doc_fields if name in fn]
    if len(hits) == 1:
        return hits[0]
    return None


def _is_absent(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _resolve_operand(op: L1Operand, doc_fields: dict[str, dict]):
    """Operand → (raw value, evidence). A field ref that resolves carries a
    synthesized `AuditEvidence` (doc = resolved filename, quote = the raw
    field value as text, page unknown → None — the value is a strong locate
    tier-0/1 input even without a page hint). Constants carry None evidence;
    an unresolvable field ref returns (_UNRESOLVED, None)."""
    if isinstance(op, L1FieldRef):
        fn = _resolve_doc(op.doc, doc_fields)
        if fn is None:
            return _UNRESOLVED, None
        v = doc_fields[fn].get(op.field)
        if _is_absent(v):
            return _UNRESOLVED, None
        return v, AuditEvidence(doc=fn, quote=str(v))
    return op, None


def _num(v) -> Optional[Decimal]:
    """Number under money semantics: strip currency symbols / spaces (keep
    digits, separators, sign) before parsing — mirrors judge.key_match's
    `number` arm so ¥370,815.56 == 370815.56."""
    s = unicode_canonical(str(v))
    cleaned = re.sub(r"[^\d.,\-]", "", s)
    if not re.search(r"\d", cleaned):
        return None
    return try_number(cleaned)


def _date(v):
    s = unicode_canonical(str(v))
    # Don't let plain numbers (amounts) masquerade as dates — dateparser would
    # happily read "370815" as one. A date needs internal separators / words;
    # a bare optionally-signed decimal number is never a date here.
    if re.fullmatch(r"-?[\d.,]+", s):
        return None
    return try_date(s)


def _fmt(v) -> str:
    return unicode_canonical(str(v))


def try_l1(rule: AuditRule, doc_fields: dict[str, dict]) -> Optional[RuleCheck]:
    """Decide `rule` deterministically when possible; ``None`` = judge's turn.

    `doc_fields` = {filename: extracted fields} for the docs run_audit actually
    loaded (only those with extractions in hand). Returns a RuleCheck with
    `decided_by="l1"` and an explainable reason, or None to defer.
    """
    check = rule.check
    if check is None:
        return None

    if check.type == "eq":
        left, lev = _resolve_operand(check.left, doc_fields)
        right, rev = _resolve_operand(check.right, doc_fields)
        if left is _UNRESOLVED or right is _UNRESOLVED:
            return None
        evidence = [e for e in (lev, rev) if e is not None]
        ln, rn = _num(left), _num(right)
        if ln is not None and rn is not None:
            tol = Decimal(str(check.tol)) if check.tol is not None else Decimal("0")
            ok = abs(ln - rn) <= tol
            tol_note = f" (tol {check.tol})" if check.tol is not None else ""
            reason = f"L1: {_fmt(left)} {'==' if ok else '!='} {_fmt(right)}{tol_note}"
        else:
            ld, rd = _date(left), _date(right)
            if ld is not None and rd is not None:
                ok = ld.date() == rd.date()
                reason = f"L1: {_fmt(left)} {'==' if ok else '!='} {_fmt(right)}"
            else:
                ok = unicode_canonical(str(left)) == unicode_canonical(str(right))
                reason = f"L1: {_fmt(left)!r} {'==' if ok else '!='} {_fmt(right)!r}"
        return RuleCheck(
            rule=rule.rule, status="pass" if ok else "fail", reason=reason,
            level=rule.level, decided_by="l1", evidence=evidence,
        )

    # range: low <= value <= high — numbers and dates only; anything that
    # doesn't parse uniformly defers to the judge.
    value, vev = _resolve_operand(check.value, doc_fields)
    low, lev = _resolve_operand(check.low, doc_fields)
    high, hev = _resolve_operand(check.high, doc_fields)
    if value is _UNRESOLVED or low is _UNRESOLVED or high is _UNRESOLVED:
        return None
    evidence = [e for e in (vev, lev, hev) if e is not None]

    vn, ln_, hn = _num(value), _num(low), _num(high)
    if vn is not None and ln_ is not None and hn is not None:
        ok = ln_ <= vn <= hn
    else:
        vd, ld, hd = _date(value), _date(low), _date(high)
        if vd is None or ld is None or hd is None:
            return None  # unparsable spec → judge decides
        ok = ld.date() <= vd.date() <= hd.date()
    reason = (
        f"L1: {_fmt(value)} {'∈' if ok else '∉'} [{_fmt(low)}, {_fmt(high)}]"
    )
    return RuleCheck(
        rule=rule.rule, status="pass" if ok else "fail", reason=reason,
        level=rule.level, decided_by="l1", evidence=evidence,
    )
