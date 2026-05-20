from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NamedTuple, Optional

from app.config import get_settings
from app.provider import get_provider_for_model
from app.provider.base import TextBlock
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    eval_judge_cache_dir,
    eval_judge_cache_path,
)


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idx": {"type": "integer"},
                    "equivalent": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["idx", "equivalent", "reason"],
            },
        },
    },
    "required": ["verdicts"],
}


def _hash_pair(field_name: str, truth: str, pred: str) -> str:
    h = hashlib.sha256()
    h.update(field_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(truth.encode("utf-8"))
    h.update(b"\x00")
    h.update(pred.encode("utf-8"))
    return h.hexdigest()


class JudgeVerdict(NamedTuple):
    equivalent: bool
    reason: str
    model: str
    cached: bool


def _read_cache(workspace: Path, slug: str, sha: str) -> Optional[JudgeVerdict]:
    p = eval_judge_cache_path(workspace, slug, sha)
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return JudgeVerdict(
        equivalent=bool(blob.get("equivalent", False)),
        reason=str(blob.get("reason", "")),
        model=str(blob.get("model", "")),
        cached=True,
    )


def _write_cache(workspace: Path, slug: str, sha: str, v: JudgeVerdict) -> None:
    eval_judge_cache_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        eval_judge_cache_path(workspace, slug, sha),
        {"equivalent": v.equivalent, "reason": v.reason, "model": v.model},
    )


async def judge_batch(
    workspace: Path,
    slug: str,
    pairs: list[tuple[SchemaField, str, str]],
    *,
    model_id: Optional[str] = None,
    budget: Optional[int] = None,
) -> tuple[list[Optional[JudgeVerdict]], int]:
    """Returns (verdicts_aligned_with_input, skipped_due_to_budget). `None`
    verdict = budget-exceeded; caller keeps L1 verdict for that pair. Cached
    pairs never count against budget."""
    if not pairs:
        return [], 0

    settings = get_settings()
    model_id = model_id or settings.llm_judge_model
    budget = budget if budget is not None else settings.llm_judge_budget_per_eval

    out: list[Optional[JudgeVerdict]] = [None] * len(pairs)
    uncached_idx: list[int] = []
    shas: list[str] = []

    for i, (field, t, p) in enumerate(pairs):
        sha = _hash_pair(field.name, t, p)
        shas.append(sha)
        cached = _read_cache(workspace, slug, sha)
        if cached is not None:
            out[i] = cached
        else:
            uncached_idx.append(i)

    budgeted_idx = uncached_idx[:budget]
    skipped = len(uncached_idx) - len(budgeted_idx)

    if not budgeted_idx:
        return out, skipped

    items = []
    for j, i in enumerate(budgeted_idx):
        f, t, p = pairs[i]
        items.append(
            {
                "idx": j,
                "field": f.name,
                "description": (f.description or "")[:300],
                "truth": t,
                "pred": p,
            }
        )

    system_prompt = (
        "You judge whether two strings refer to the same value for a given field. "
        "Output JSON {verdicts: [{idx, equivalent, reason}]}. "
        "Equivalent means the values would be considered the same by a domain expert "
        "for this field's purpose — formatting differences, abbreviations, and synonyms "
        "are equivalent; numerically or semantically distinct values are not."
    )
    user_text = "Judge each pair:\n" + json.dumps(items, ensure_ascii=False)

    try:
        provider = get_provider_for_model(model_id)
        result = await provider.extract(
            model_id=model_id,
            system_prompt=system_prompt,
            user_content=[TextBlock(type="text", text=user_text)],
            response_schema=JUDGE_SCHEMA,
            params={"temperature": 0.0},
        )
    except Exception:
        # Provider error → keep L1 for all budgeted pairs.
        return out, skipped + len(budgeted_idx)

    try:
        verdicts = result.raw_json["verdicts"]
    except (KeyError, TypeError):
        return out, skipped + len(budgeted_idx)

    for v in verdicts:
        try:
            j = int(v["idx"])
            i = budgeted_idx[j]
            jv = JudgeVerdict(
                equivalent=bool(v["equivalent"]),
                reason=str(v.get("reason", "")),
                model=model_id,
                cached=False,
            )
            out[i] = jv
            _write_cache(workspace, slug, shas[i], jv)
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    return out, skipped
