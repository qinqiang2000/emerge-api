"""Audit judge — run a set of NL compliance rules over a GROUP of documents.

This is the new core the audit form turns on: where matching's `judge_pair`
answers "do these two docs pair?", `audit_group` answers "does this grouped set
of docs satisfy each compliance rule?". Rules are natural language (the user
lists them); the judge returns one verdict per rule, index-aligned.

Mixed rule types in one pass (the judge reads them all):
  - single-doc field assertion   ("甲方为 环胜电子商务（上海）")
  - cross-doc field consistency   ("报价单金额 == 收货单金额", "抬头 ~ 备注关键字")
  - cross-doc range/interval      ("报价单周期 ∋ 订单完成日期")
  - single-doc VISUAL assertion   ("乙方加盖合同专用章") → needs the doc image

Hard rules: provider direct (never recurses into the SDK); the image is PULLED
(attached only because a visual rule may need it), never auto-attached; no image
few-shot; no bbox in the prompt. `unclear` is a first-class verdict — the judge
must not guess `fail` when it can't decide.
"""
from __future__ import annotations

import json
from typing import Optional

from app.provider.base import ImageBlock, Provider, TextBlock
from app.schemas.match import RuleCheck

_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {"type": "string", "enum": ["pass", "fail", "unclear"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "status", "reason"],
            },
        }
    },
    "required": ["checks"],
}

_SYSTEM = (
    "You are a meticulous document-compliance auditor. You are given a GROUP of "
    "related documents — EACH shown as one or more images, labelled by role — and "
    "a numbered list of compliance rules. Some pre-extracted fields may also be "
    "provided for reference, but the DOCUMENT IMAGES ARE THE SOURCE OF TRUTH: read "
    "values, stamps, signatures, dates and amounts off the images; use the fields "
    "only as a hint. For EACH rule, decide whether the group satisfies it.\n"
    "- Output one verdict per rule, keyed by the rule's `index` (0-based).\n"
    "- status: 'pass' = clearly satisfied; 'fail' = clearly violated; 'unclear' "
    "= you cannot determine it from the documents (e.g. the relevant area is "
    "absent or illegible). NEVER guess 'fail' when unsure — use 'unclear'.\n"
    "- VISUAL rules (a stamp/seal/red chop, a signature present): inspect the "
    "relevant document image directly.\n"
    "- CROSS-DOCUMENT rules: locate the relevant value on each document and "
    "compare. Allow sensible tolerances (amounts equal within rounding; a date "
    "inside a stated period; the same company written differently; keyword "
    "overlap for fuzzy title/remark matches).\n"
    "- `reason`: one short sentence citing the concrete values/marks you saw."
)


async def audit_group(
    *,
    doc_images: dict[str, list[ImageBlock]],
    audit_rules: list[str],
    doc_fields: Optional[dict[str, dict]] = None,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> list[RuleCheck]:
    """Judge `audit_rules` over a group of documents, one trip.

    `doc_images` = {role: [page images]} — the documents themselves, the source
    of truth (read fields, stamps, dates off them). `doc_fields` = {role: fields}
    is OPTIONAL pre-extracted data passed as a hint (better number precision);
    audit does NOT require prior extraction. Returns one `RuleCheck` per rule, in
    order. With no provider (or on failure) every rule comes back `unclear` —
    audit is inherently LLM-judged.
    """
    if not audit_rules:
        return []
    if provider is None:
        return [RuleCheck(rule=r, status="unclear",
                          reason="no judge model available") for r in audit_rules]

    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(audit_rules))
    intro = "Compliance rules (numbered):\n" + numbered
    if doc_fields:
        intro += (
            "\n\nPre-extracted fields (reference only — verify against the images):\n"
            + json.dumps(doc_fields, ensure_ascii=False)
        )
    intro += "\n\nThe documents follow, each labelled by role:"
    blocks: list = [TextBlock(text=intro)]
    for role, imgs in doc_images.items():
        blocks.append(TextBlock(text=f"--- Document: {role} ---"))
        blocks.extend(imgs)

    try:
        result = await provider.extract(
            model_id=model_id or "audit-judge",
            system_prompt=_SYSTEM,
            user_content=blocks,
            response_schema=_AUDIT_SCHEMA,
            params={"temperature": 0.0},
        )
        raw = result.raw_json
    except Exception:
        return [RuleCheck(rule=r, status="unclear", reason="judge call failed")
                for r in audit_rules]

    # Index-align the verdicts back onto audit_rules; any rule the judge didn't
    # return (or returned out of range) stays `unclear` — never length-fail.
    by_index: dict[int, dict] = {}
    for c in (raw.get("checks") or []) if isinstance(raw, dict) else []:
        try:
            by_index[int(c["index"])] = c
        except (KeyError, TypeError, ValueError):
            continue

    out: list[RuleCheck] = []
    for i, rule in enumerate(audit_rules):
        c = by_index.get(i)
        if not c:
            out.append(RuleCheck(rule=rule, status="unclear",
                                 reason="judge returned no verdict for this rule"))
            continue
        status = c.get("status")
        if status not in ("pass", "fail", "unclear"):
            status = "unclear"
        out.append(RuleCheck(rule=rule, status=status, reason=str(c.get("reason", ""))))
    return out
