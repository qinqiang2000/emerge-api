"""Pair-judgement layer for document matching.

L1 (rules, free + deterministic): for each declared key mapping, compare the
anchor value to the source value under the mapping's tolerance, reusing the
eval normalization primitives (`_try_number`, `_try_date`, `_unicode_canonical`)
— but NOT `normalize_equivalent`, which is exact-equality; matching needs
*within-tolerance* (amount ±abs, date ±days).

L2 (LLM tie-breaker, on the ambiguous middle): when a pair is neither a clean
all-keys-match nor a clean no-keys-match — i.e. SOME keys agree and SOME
disagree — an LLM judge (provider direct, never recursing back into the SDK)
reads `rules` + the two field dicts and decides whether the documents refer to
the same transaction. Clean all-match / clean no-match never spend an LLM call.

Hard rules: the L2 prompt is fed FIELD VALUES ONLY — no bbox, no document body.
"""
from __future__ import annotations

import json
from typing import Optional

from app.eval.normalize import _try_date, _try_number, _unicode_canonical
from app.provider.base import Provider, TextBlock
from app.schemas.match import KeyMapping, PairVerdict, Tol
from app.schemas.schema_field import SchemaField

# Public aliases for the shared normalization primitives — the audit L1 engine
# (`app/match/audit_l1.py`) reuses them; alias instead of re-implementing so
# matching and auditing can never drift on number/date semantics.
try_number = _try_number
try_date = _try_date
unicode_canonical = _unicode_canonical


# L2 judge response shape — a single boolean verdict over the whole pair.
_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "match": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["match", "reason"],
}


def _is_absent(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _exact_equal(a: str, b: str) -> bool:
    """Unicode-canonical equality, then a casefold + punctuation-insensitive
    pass for id/code-style keys (mirrors normalize's `enum`/`id`/`code` arm)."""
    au, bu = _unicode_canonical(a), _unicode_canonical(b)
    if au == bu:
        return True
    import re

    canon = lambda s: re.sub(r"[^\w]", "", s, flags=re.UNICODE).casefold()
    return canon(au) == canon(bu)


def key_match(
    anchor_val,
    source_val,
    tol: Tol,
    *,
    field: Optional[SchemaField] = None,
) -> bool:
    """True when `anchor_val` matches `source_val` under `tol`.

    - Both-absent → True (nothing to contradict). One-absent → False.
    - `exact`     → unicode-canonical + id/code casefold equality.
    - `number`    → both parse as numbers and differ by ≤ `tol.abs` (default 0).
    - `date_days` → both parse as dates and differ by ≤ `tol.days` (default 0).

    `field` is currently advisory (date_order hook); the tolerance type is the
    authority — a `number` tol forces numeric comparison regardless of the
    field's declared type.
    """
    a_abs, s_abs = _is_absent(anchor_val), _is_absent(source_val)
    if a_abs and s_abs:
        return True
    if a_abs != s_abs:
        return False

    a, s = str(anchor_val), str(source_val)

    if tol.type == "number":
        # Strip currency symbols / thousands separators before parsing so money
        # amounts compare (mirrors normalize_equivalent's `money` arm) — the
        # primary use of a `number` tol is amount reconciliation (¥1,200.00 ↔ 1200).
        import re

        def _num(x: str):
            return _try_number(re.sub(r"[^\d.,\-]", "", _unicode_canonical(x)))

        an, sn = _num(a), _num(s)
        if an is None or sn is None:
            return False
        from decimal import Decimal

        limit = Decimal(str(tol.abs)) if tol.abs is not None else Decimal("0")
        return abs(an - sn) <= limit

    if tol.type == "date_days":
        order = (getattr(field, "date_order", None) if field else None) or "YMD"
        ad, sd = _try_date(_unicode_canonical(a), order), _try_date(
            _unicode_canonical(s), order
        )
        if ad is None or sd is None:
            return False
        days = tol.days if tol.days is not None else 0
        return abs((ad.date() - sd.date()).days) <= days

    # default / "exact"
    return _exact_equal(a, s)


def _schema_field(schemas: dict[str, SchemaField], name: str) -> Optional[SchemaField]:
    return schemas.get(name)


async def judge_pair(
    anchor_entity: dict,
    source_entity: dict,
    *,
    source: str,
    mappings_for_source: list[KeyMapping],
    anchor_schema: dict[str, SchemaField],
    source_schema: dict[str, SchemaField],
    rules: str = "",
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> PairVerdict:
    """Judge whether `anchor_entity` and `source_entity` refer to the same
    transaction, per the source's key mappings.

    Score = matched_keys / total_keys. L1 decides the clean cases (all match →
    `match`; none match → `mismatch`). The ambiguous middle (some keys match,
    some don't) escalates to L2 when a `provider` is supplied; L2 can flip a
    partial to `match` (e.g. "商户名不同写法但同一公司"). Without a provider, a
    partial stays `mismatch` with the failing keys listed.
    """
    if not mappings_for_source:
        # No rules declared for this source → cannot judge; treat as mismatch
        # with a zero score so the engine never pairs on an empty contract.
        return PairVerdict(
            source=source, doc=None, status="mismatch",
            mismatched_fields=[], reason="no key mappings declared", score=0.0,
        )

    total = len(mappings_for_source)
    matched_fields: list[str] = []
    mismatched_fields: list[str] = []
    for km in mappings_for_source:
        a_val = anchor_entity.get(km.anchor)
        s_val = source_entity.get(km.source)
        fld = _schema_field(anchor_schema, km.anchor) or _schema_field(
            source_schema, km.source
        )
        if key_match(a_val, s_val, km.tol, field=fld):
            matched_fields.append(km.anchor)
        else:
            mismatched_fields.append(km.anchor)

    score = len(matched_fields) / total if total else 0.0

    if not mismatched_fields:
        return PairVerdict(
            source=source, doc=None, status="match",
            mismatched_fields=[], reason=None, score=score,
        )

    if len(matched_fields) == 0:
        # Nothing agrees → clean no-match, no LLM spend.
        return PairVerdict(
            source=source, doc=None, status="mismatch",
            mismatched_fields=mismatched_fields, reason=None, score=score,
        )

    # Ambiguous middle: some agree, some don't → L2 tie-breaker when available.
    if provider is not None:
        verdict = await _llm_judge(
            anchor_entity, source_entity,
            mappings_for_source=mappings_for_source,
            rules=rules, provider=provider, model_id=model_id,
        )
        if verdict is not None:
            same, reason = verdict
            return PairVerdict(
                source=source, doc=None,
                status="match" if same else "mismatch",
                mismatched_fields=[] if same else mismatched_fields,
                reason=reason, score=score,
            )

    # No provider, or L2 failed → keep the deterministic partial verdict.
    return PairVerdict(
        source=source, doc=None, status="mismatch",
        mismatched_fields=mismatched_fields, reason=None, score=score,
    )


async def _llm_judge(
    anchor_entity: dict,
    source_entity: dict,
    *,
    mappings_for_source: list[KeyMapping],
    rules: str,
    provider: Provider,
    model_id: Optional[str],
) -> Optional[tuple[bool, str]]:
    """Ask the L2 judge whether the two documents match. Returns (same, reason)
    or None on provider/parse failure (caller keeps the L1 verdict). Feeds only
    the mapped field values + the NL rules — no bbox, no document body."""
    mapped = [
        {
            "anchor_field": km.anchor,
            "source_field": km.source,
            "anchor_value": anchor_entity.get(km.anchor),
            "source_value": source_entity.get(km.source),
            "tolerance": km.tol.model_dump(exclude_none=True),
        }
        for km in mappings_for_source
    ]
    system_prompt = (
        "You decide whether an anchor document and a source document refer to "
        "the same real-world transaction, given a set of field correspondences "
        "and the user's matching rules. Some fields already agree under their "
        "tolerance and some do not. Use the rules to break the tie (e.g. a "
        "company name written differently but the same entity counts as a "
        "match). Output JSON {match: bool, reason: string}."
    )
    user_text = json.dumps(
        {"rules": rules, "field_pairs": mapped},
        ensure_ascii=False,
    )
    mid = model_id or "match-judge"
    try:
        result = await provider.extract(
            model_id=mid,
            system_prompt=system_prompt,
            user_content=[TextBlock(type="text", text="Judge this pair:\n" + user_text)],
            response_schema=_JUDGE_SCHEMA,
            params={"temperature": 0.0},
        )
    except Exception:
        return None
    try:
        same = bool(result.raw_json["match"])
        reason = str(result.raw_json.get("reason", ""))
    except (KeyError, TypeError):
        return None
    return same, reason
