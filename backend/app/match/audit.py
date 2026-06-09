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
    "related documents (each shown by role with its already-extracted fields), an "
    "optional image of the anchor document, and a numbered list of compliance "
    "rules. For EACH rule, decide whether the group satisfies it.\n"
    "- Output one verdict per rule, keyed by the rule's `index` (0-based).\n"
    "- status: 'pass' = clearly satisfied; 'fail' = clearly violated; 'unclear' "
    "= you cannot determine it from the given fields/image (e.g. a needed field "
    "is absent, or a visual mark is illegible). NEVER guess 'fail' when unsure — "
    "use 'unclear'.\n"
    "- For VISUAL rules (e.g. a stamp/seal/signature is present), inspect the "
    "anchor image. If no image is provided and the rule needs one, return "
    "'unclear'.\n"
    "- For cross-document rules, compare the relevant fields across roles. Allow "
    "sensible tolerances (amounts equal within rounding; a date inside a stated "
    "period; the same company written differently; keyword overlap for fuzzy "
    "title/remark matches).\n"
    "- `reason`: one short sentence citing the concrete values you compared."
)


async def audit_group(
    *,
    group_docs: dict[str, dict],
    audit_rules: list[str],
    anchor_image: Optional[ImageBlock] = None,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> list[RuleCheck]:
    """Judge `audit_rules` over `group_docs` (= {role: extracted_fields}).

    Returns one `RuleCheck` per rule, in the rules' order. With no provider (or
    on provider/parse failure) every rule comes back `unclear` — audit is
    inherently LLM-judged, so there is no deterministic fallback verdict.
    """
    if not audit_rules:
        return []
    if provider is None:
        return [RuleCheck(rule=r, status="unclear",
                          reason="no judge model available") for r in audit_rules]

    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(audit_rules))
    payload = {
        "documents": group_docs,           # {role: {field: value}}
        "rules": [{"index": i, "rule": r} for i, r in enumerate(audit_rules)],
    }
    blocks: list = [TextBlock(
        text="Documents and rules:\n" + json.dumps(payload, ensure_ascii=False)
        + "\n\nRules (numbered):\n" + numbered,
    )]
    if anchor_image is not None:
        blocks.append(anchor_image)

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
