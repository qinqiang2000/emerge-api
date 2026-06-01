"""Grounding pass: a *separate* LLM call that resolves where extracted values
live in the document (page + verbatim source quote), decoupled from extraction.

Why a separate pass (not folded into the extract response_schema):
  Field-source-grounding needs the model to emit a verbatim ``source`` quote per
  field — the single anchor that lets the locate resolver disambiguate a value
  that repeats on the page (``111`` is the value of five fields on one invoice).
  But the extract path uses Gemini *constrained decoding* (response_mime_type +
  response_schema); the schema deliberately omits ``_evidence`` (Gemini's
  OpenAPI-3.0 dialect rejects ``additionalProperties``, and mirroring every
  nested field would bloat the schema and degrade extraction adherence). Under
  constrained decoding the model physically cannot emit a key outside the schema,
  so the prompt's "emit ``_evidence``" instruction was silently dropped and every
  prediction landed with no grounding. Rather than bloat the money-path schema
  (and risk extraction quality), grounding is its own call with its own flat,
  Gemini-friendly schema, run lazily at review time and cached into the blob.

This reuses the project's *active extract model* (no new LLM layer) and goes
straight through the provider adapter — it never re-enters the agent SDK. Output
is plain text (page int + verbatim quote); NO coordinates ever (red line). The
rects themselves are recovered later, render-side, by ``app/tools/locate.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

from app.provider.base import ContentBlock, Provider, TextBlock
from app.tools.extract import _doc_to_block
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    pending_reviewed_path,
    prediction_draft_path,
)

# How the value list is presented to the model + the flat groundings schema it
# fills in. Flat (entity index + dot-path) so it dodges Gemini's no-
# additionalProperties limit and never mirrors the nested entity shape.
_GROUND_SYSTEM = """You are given a document and a list of values already extracted from it.
For EACH listed value, find where it was read from in the document and report:
- `page`: the 1-based page number where the value appears.
- `source`: the exact text fragment you read it from, copied VERBATIM from the
  document (<=120 chars, keep the original language; do NOT translate, normalize,
  rewrite, or reformat). Include enough surrounding text — a nearby label or the
  rest of the line — that the snippet is UNIQUELY locatable on the page; a bare
  value that repeats (an amount, a code) is not enough on its own.

Rules:
- Echo back the same `entity` index and `path` string you were given.
- A value that was merely REFORMATTED or REORDERED from the page still HAS a
  source — report it (do NOT emit null). The extracted value is normalized but
  the page text is not, so they look different:
    * a date: value "2025-07-02" may appear as "07-02-25", "2 Jul 2024", "07/02";
      report the verbatim on-page text (e.g. "到店日期 : 07-02-25"), with its
      label so the snippet is unique.
    * a number: value "494.03" may appear with different separators/precision;
      report the verbatim on-page text.
  Copy what is printed, NOT the normalized value.
- Emit null for both `page` and `source` ONLY when there is no single literal
  source on the page: a computed sum/total, an inferred classification, or a
  field that is simply absent from the document.
- If you cannot locate a value, emit null for both `page` and `source`.
- NEVER output coordinates, bounding boxes, pixel positions, or region geometry —
  only the page number and the verbatim text snippet.

Return the result via the structured schema (a `groundings` array)."""


def _groundings_response_schema() -> dict[str, Any]:
    """Flat grounding schema — one row per (entity, path). No additionalProperties,
    no nested mirror of the entity shape; safe for Gemini constrained decoding."""
    return {
        "type": "object",
        "required": ["groundings"],
        "properties": {
            "groundings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["entity", "path", "page", "source"],
                    "properties": {
                        "entity": {"type": "integer"},
                        "path": {"type": "string"},
                        "page": {"type": "integer", "nullable": True},
                        "source": {"type": "string", "nullable": True},
                    },
                },
            }
        },
    }


def _blob_path(workspace: Path, project_id: str, filename: str, tab: str) -> Path:
    if tab == "_pending":
        return pending_reviewed_path(workspace, project_id, filename)
    if tab == "_draft":
        return prediction_draft_path(workspace, project_id, filename)
    raise ValueError(f"ground: unsupported tab {tab!r} (expected _draft or _pending)")


def has_evidence(blob: dict) -> bool:
    """True if the blob already carries non-empty per-entity evidence."""
    ev = blob.get("_evidence")
    if not isinstance(ev, list) or not ev:
        return False
    # any entry with any non-null page or source counts as grounded
    for entry in ev:
        if isinstance(entry, dict):
            for v in entry.values():
                if isinstance(v, dict) and (v.get("page") is not None or v.get("source")):
                    return True
                if isinstance(v, int) and not isinstance(v, bool):
                    return True
    return False


# `parent[3]` → `parent[]`: collapse concrete array indices to the bracket form
# the locate resolver keys evidence by (its `_flatten_entity` emits `parent[]`).
_INDEX = re.compile(r"\[\d+\]")


def _collapse(path: str) -> str:
    return _INDEX.sub("[]", path)


def _walk_values(node: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(model_path, scalar_value)`` for every non-empty scalar leaf.

    Walks the *data* (not the schema) so it sees concrete array items, which the
    schema-based ``_collect_leaves`` cannot (an array leaf has no single scalar).
    Array items get indexed paths (``detailOfGoodsOrServices[0].articleName``) so
    the model can pinpoint each one; the index is collapsed back to ``[]`` on
    reshape to match the locate evidence key. Objects expand ``parent.child``."""
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{prefix}.{k}" if prefix else str(k)
            yield from _walk_values(v, child)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_values(v, f"{prefix}[{i}]")
    elif node is not None:
        sval = str(node).strip()
        if sval:
            yield prefix, sval


def _value_lines(entities: list[dict]) -> tuple[str, int]:
    """Render the (entity, path, value) worklist for the prompt.

    Only non-empty scalar leaves are sent — derived/absent fields are skipped; the
    model isn't asked to ground what isn't there. Returns (text, n_items)."""
    lines: list[str] = []
    for idx, entity in enumerate(entities):
        for path, sval in _walk_values(entity):
            lines.append(f"- entity={idx} path=`{path}` value={sval!r}")
    return "\n".join(lines), len(lines)


def _reshape(groundings: list[dict], n_entities: int) -> list[dict[str, Any]]:
    """Flat groundings rows → per-entity ``{path: {page, source}}`` evidence list.

    Length always == n_entities (locate / ExtractionOutput require parity). Rows
    with a null page AND null source are dropped (no signal to store)."""
    out: list[dict[str, Any]] = [{} for _ in range(n_entities)]
    for row in groundings or []:
        if not isinstance(row, dict):
            continue
        try:
            ent = int(row.get("entity"))
        except (TypeError, ValueError):
            continue
        path = row.get("path")
        if not isinstance(path, str) or not path or not (0 <= ent < n_entities):
            continue
        # Keep the model's CONCRETE per-row path (`detail[0].x`, `detail[1].x`)
        # so each array row carries its OWN page + quote. The previous
        # `_collapse` to `detail[].x` merged every row under one key
        # (last-row-wins): row 0 inherited row 1's quote and the highlight
        # teleported to the wrong row (the unitPrice→10.4900 bug). locate keys
        # evidence concrete-first (collapsed-fallback only for legacy blobs); the
        # frontend p-chip lookup mirrors that.
        page = row.get("page")
        source = row.get("source")
        if page is None and not source:
            continue
        out[ent][path] = {
            "page": page if isinstance(page, int) and not isinstance(page, bool) else None,
            "source": source if isinstance(source, str) and source.strip() else None,
        }
    return out


async def ground_entities(
    workspace: Path,
    project_id: str,
    filename: str,
    entities: list[dict],
    *,
    provider: Provider,
    model_id: str,
) -> list[dict[str, Any]]:
    """Resolve per-field grounding evidence for ``entities`` — pure compute, no
    blob cache.

    One grounding provider call over the doc: build the worklist, ask the model
    for each value's ``{page, source}``, reshape to the per-entity
    ``{path: {page, source}}`` list (length == ``len(entities)``). Caller supplies
    the resolved ``provider`` + ``model_id`` (the active extract model, or the
    experiment's model). Shared by the lazy/cached :func:`ground_prediction` and
    by the eager extract / experiment write paths that stamp ``_evidence`` into
    the prediction blob at produce time (so the LLM-free review render path always
    finds warm evidence — see app/tools/locate.py and stores/locate.ts)."""
    if not entities:
        return []
    worklist, n_items = _value_lines(entities)
    if n_items == 0:
        return [{} for _ in entities]

    doc_block = await _doc_to_block(workspace, project_id, filename)
    user_blocks: list[ContentBlock] = [
        TextBlock(text="Values to locate in the document:\n" + worklist),
        doc_block,
    ]
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_GROUND_SYSTEM,
        user_content=user_blocks,
        response_schema=_groundings_response_schema(),
    )
    groundings = (result.raw_json or {}).get("groundings", [])
    return _reshape(groundings if isinstance(groundings, list) else [], len(entities))


async def ground_prediction(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    tab: str = "_draft",
    entities: list[dict] | None = None,
    provider: Provider | None = None,
    model_id: str | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Resolve + cache per-field grounding evidence for a prediction.

    When ``entities`` is given, grounds *those exact values* (what the review
    viewer is displaying — e.g. the merged ``active`` tab, which may be backed by
    the pending blob, not ``_draft``); otherwise reads the ``tab`` blob's
    entities. Returns the ``tab`` blob's cached ``_evidence`` when already grounded
    (unless ``force``). The fresh result is written back into the ``tab`` blob
    when that blob exists and its entity count matches, so the next open hits the
    cache.

    Raises:
        FileNotFoundError: ``entities`` not given and the ``tab`` blob is absent.
    """
    import json

    from app.tools.model import read_active_model, read_model
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    path = _blob_path(workspace, project_id, filename, tab)
    blob = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    if not force and blob is not None and has_evidence(blob):
        return blob.get("_evidence") or []

    if entities is None:
        if blob is None:
            raise FileNotFoundError(
                f"no {tab} prediction for {filename!r} in {project_id!r}"
            )
        entities = blob.get("entities") or []
    if not entities:
        return []

    if model_id is None:
        mc = await read_active_model(workspace, project_id)
    else:
        mc = await read_model(workspace, project_id, model_id)
    mid = mc.provider_model_id
    if provider is None:
        from app.provider import get_provider_for_model

        provider = get_provider_for_model(mid, provider=mc.provider)

    evidence = await ground_entities(
        workspace, project_id, filename, entities, provider=provider, model_id=mid
    )

    # Cache into the tab blob only when it exists and lines up with what we
    # grounded (so grounding the merged `active` view doesn't stamp mismatched
    # evidence onto a blob with a different entity count).
    if path.exists():
        async with project_lock(workspace, project_id):
            # re-read under lock so we don't clobber a concurrent save.
            current = json.loads(path.read_text(encoding="utf-8"))
            if len(current.get("entities") or []) == len(entities):
                current["_evidence"] = evidence
                atomic_write_json(path, current)
    return evidence
