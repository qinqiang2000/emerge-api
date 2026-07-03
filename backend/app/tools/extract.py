from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.schema import _doc_to_block
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    prediction_draft_path,
    predictions_draft_dir,
)




_EXTRACT_SYSTEM = """You extract structured data from a document.

Output rules:
- top-level: array of objects (entities). One PDF may contain multiple entities (e.g. multiple receipts).
- use the field names from the schema verbatim (case-sensitive); do not translate snake_case↔camelCase.
- ALWAYS include every field declared in the schema for each entity. Use null when the value is absent from the document or you are uncertain. Do NOT omit keys.

Use the emit_extraction tool to return the result."""

log = logging.getLogger(__name__)

# Source-grounding (page + verbatim quote per field) is NOT part of THIS
# response_schema on purpose: it is a SEPARATE provider call (app/tools/ground.py).
# Folding it into this schema would either need `additionalProperties` (which
# Gemini's OpenAPI-3.0 dialect rejects) or a full mirror of the nested field
# shape — bloating the schema and risking extraction adherence under constrained
# decoding. Keeping extraction clean protects value accuracy; grounding owns its
# own flat schema. See 2026-05-29-grounding-pass.md.
#
# Grounding now runs EAGERLY right after the draft is produced (see extract_one),
# warming `_evidence` into the blob at produce time. The review render path
# (locate) stays LLM-free and just reads that warm evidence — it no longer
# grounds lazily (that lazy path was dropped in 04a3730, leaving new predictions
# un-grounded, which is what scattered the source highlights).


def _build_response_schema(schema: list[SchemaField]) -> dict[str, Any]:
    """Convert SchemaField[] to JSON schema for tool input.

    Every schema field is marked `required` and `nullable:true` so that Gemini
    always emits the key (with null when absent). The user-facing schema
    definition == prediction key set; SchemaField.required only documents
    intent and is not enforced at this layer.
    """
    entity_schema: dict[str, Any] = {
        "type": "object",
        "properties": {f.name: _field_jsonschema(f) for f in schema},
        "required": [f.name for f in schema],
    }

    # No `_evidence` here — grounding is a separate pass (see _EXTRACT_SYSTEM note
    # + app/tools/ground.py). ExtractionOutput still accepts `_evidence` as
    # Optional so reviewed-save / grounding can stamp it onto the blob later.
    return {
        "type": "object",
        "required": ["entities"],
        "properties": {
            "entities": {"type": "array", "items": entity_schema},
        },
    }


def _field_jsonschema(f: SchemaField) -> dict[str, Any]:
    base: dict[str, Any]
    if f.type == FieldType.STRING:
        base = {"type": "string"}
        if f.format is not None:
            base["format"] = f.format.value
        if f.enum:
            base["enum"] = f.enum
    elif f.type == FieldType.NUMBER:
        base = {"type": "number"}
    elif f.type == FieldType.INTEGER:
        base = {"type": "integer"}
    elif f.type == FieldType.BOOLEAN:
        base = {"type": "boolean"}
    elif f.type == FieldType.OBJECT:
        props = f.properties or []
        base = {
            "type": "object",
            "properties": {c.name: _field_jsonschema(c) for c in props},
            "required": [c.name for c in props],
        }
    elif f.type == FieldType.ARRAY:
        assert f.items is not None
        base = {"type": "array", "items": _field_jsonschema(f.items)}
    else:
        base = {"type": "string"}
    base["description"] = f.description
    base["nullable"] = True
    return base


def _type_label(f: SchemaField) -> str:
    if f.type == FieldType.STRING and f.format is not None:
        return f"string<{f.format.value}>"
    if f.type == FieldType.ARRAY and f.items is not None:
        inner = _type_label(f.items)
        return f"array<{inner}>"
    return f.type.value


def _collect_leaves(prefix: str, f: SchemaField) -> list[tuple[str, SchemaField]]:
    """Flatten nested object / array shapes into (dot-path, leaf-field) pairs.
    Objects expand into `parent.child`. Arrays expand their items as
    `parent[].…`. Scalar array items become a single leaf `parent[]`."""
    if f.type == FieldType.OBJECT:
        out: list[tuple[str, SchemaField]] = []
        for c in f.properties or []:
            out.extend(_collect_leaves(f"{prefix}.{c.name}", c))
        return out
    if f.type == FieldType.ARRAY:
        assert f.items is not None
        return _collect_leaves(f"{prefix}[]", f.items)
    return [(prefix, f)]


def _build_field_instructions(schema: list[SchemaField]) -> str:
    lines = ["Per-field instructions:"]
    leaves: list[tuple[str, SchemaField]] = []
    for f in schema:
        assert f.name is not None
        leaves.extend(_collect_leaves(f.name, f))
    for i, (path, leaf) in enumerate(leaves, start=1):
        suffix = ""
        if leaf.enum:
            suffix += f" Allowed values: {', '.join(leaf.enum)}."
        lines.append(f"{i}. `{path}` ({_type_label(leaf)}): {leaf.description}{suffix}")
    return "\n".join(lines)


async def extract_one(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    provider: Provider | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    from app.tools.model import read_active_model
    from app.tools.prompt import read_active_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    pv = await read_active_prompt(workspace, project_id)
    schema = pv.schema
    global_notes = pv.global_notes
    if not schema:
        raise ValueError("project has empty schema; nothing to extract")
    if model_id is None:
        mc = await read_active_model(workspace, project_id)
    else:
        from app.tools.model import read_model

        mc = await read_model(workspace, project_id, model_id)
    mid = mc.provider_model_id
    if provider is None:
        from app.provider import get_provider_for_model

        provider = get_provider_for_model(
            mid, provider=mc.provider,
            base_url=mc.base_url, api_key_env=mc.api_key_env,
        )

    doc_block = await _doc_to_block(workspace, project_id, filename)
    user_blocks: list[ContentBlock] = (
        [TextBlock(text=global_notes)] if global_notes else []
    ) + [TextBlock(text=_build_field_instructions(schema)), doc_block]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=mid,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
        # Honor the model config's params (max_tokens / temperature / …). This
        # path historically dropped them, so a user-set max_tokens silently had
        # no effect and every extract ran on the provider's built-in defaults —
        # unlike the experiment (extract_one_with_schema) and prod
        # (extract_bytes_with_schema) paths, which already thread params through.
        # `mc` is the active/override model config resolved above.
        params=mc.params or None,
    )

    output = ExtractionOutput(**result.raw_json)
    payload = output.model_dump(by_alias=True, exclude_none=True)

    # M14 — self-stamp the prediction blob with its producing (model, prompt).
    # Downstream consumers (score, matrix UI, review tabstrip, chat narration)
    # read `_run` rather than re-resolving from project.json at consume time.
    # `mc` + `pv` are already loaded above; minting the stamp is one dict
    # construction with no extra I/O.
    from app.eval.run_stamp import build_stamp

    stamp = build_stamp("baseline", mc, pv)
    payload["_run"] = stamp.model_dump(mode="json", exclude_none=False)

    # Eager grounding: resolve per-field {page, source} evidence now and warm it
    # into the blob, so the LLM-free review render path (locate) always finds a
    # disambiguating anchor. Best-effort — a grounding failure (provider error,
    # etc.) must NEVER fail the extraction; the blob just lands without
    # `_evidence` and locate falls back to the value matcher (+ the hint-less
    # distinctive-only guard). Reuses the same (provider, model) that extracted.
    payload["_evidence"] = await _ground_payload(
        workspace, project_id, filename, payload, provider=provider, model_id=mid
    )

    async with project_lock(workspace, project_id):
        predictions_draft_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            prediction_draft_path(workspace, project_id, filename),
            payload,
        )

    # Eager review-sidecar warming — same philosophy as eager grounding above:
    # do the per-page text-layer work (fitz spans + the Gemini OCR supplement
    # `extract_textlayer` runs on every page) NOW, at produce time, off the
    # human's review critical path. Without this the reviewer pays a multi-
    # second OCR round-trip on first open of every doc — and a one-pass review
    # queue never re-opens a doc, so the on-disk cache otherwise never helps
    # (see screenshot bug 2026-06-05). Best-effort: a prewarm failure must
    # NEVER fail extraction; the page simply warms lazily on open as before.
    # NOT inside `project_lock` — these are LLM calls writing their own
    # docs/.meta sidecars, never the prediction blob.
    await _prewarm_textlayer(workspace, project_id, filename)
    return payload


_PREWARM_CONCURRENCY = 4


async def _prewarm_textlayer(
    workspace: Path, project_id: str, filename: str,
) -> None:
    """Warm the per-page text-layer sidecars for a just-produced doc.

    Bounded-concurrency fan-out over all pages; every failure is swallowed so a
    flaky OCR call or a missing meta sidecar can't sink the extraction that
    already landed. The text-layer sidecar is doc-scoped (not per-prediction),
    so warming it once here also makes experiment-tab review of the same doc
    instant — and it's the INPUT a later translate call reuses, so even an
    on-demand translation skips the OCR step."""
    try:
        from app.tools.textlayer import extract_textlayer
        from app.workspace.paths import doc_meta_path

        meta_p = doc_meta_path(workspace, project_id, filename)
        if not meta_p.exists():
            return
        page_count = int(json.loads(meta_p.read_text()).get("page_count", 1) or 1)
    except Exception:
        log.exception("textlayer prewarm setup failed for %r; review warms lazily", filename)
        return

    sem = asyncio.Semaphore(_PREWARM_CONCURRENCY)

    async def _one(page: int) -> None:
        async with sem:
            try:
                await extract_textlayer(workspace, project_id, filename, page=page)
            except Exception:
                # Per-page best-effort: one bad page never blocks the rest.
                log.debug("textlayer prewarm failed for %r p%d", filename, page)

    await asyncio.gather(*(_one(p) for p in range(1, page_count + 1)))


async def _ground_payload(
    workspace: Path,
    project_id: str,
    filename: str,
    payload: dict[str, Any],
    *,
    provider: Provider,
    model_id: str,
) -> list[dict] | None:
    """Best-effort per-field evidence for a just-produced prediction payload.

    Returns the per-entity evidence list, or ``None`` on any failure (caller
    stamps it onto the blob; ``None`` is omitted by ``exclude_none`` writers and
    simply means "ungrounded"). Centralises the try/except + import so the draft
    and experiment write paths share one resilient grounding step."""
    try:
        from app.tools.ground import ground_entities

        return await ground_entities(
            workspace,
            project_id,
            filename,
            payload.get("entities") or [],
            provider=provider,
            model_id=model_id,
        )
    except Exception:
        log.exception("grounding failed for %r; prediction lands without evidence", filename)
        return None


async def extract_one_with_schema(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: dict[str, Any] | None = None,
    global_notes: str = "",
) -> dict[str, Any]:
    """Like extract_one but uses an in-memory schema (does NOT read schema.json
    or write predictions/_draft/). Used by the autoresearch loop to grade
    candidate schemas without mutating disk state."""
    if not schema:
        raise ValueError("schema must be non-empty")

    doc_block = await _doc_to_block(workspace, project_id, filename)
    user_blocks: list[ContentBlock] = (
        [TextBlock(text=global_notes)] if global_notes else []
    ) + [TextBlock(text=_build_field_instructions(schema)), doc_block]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
        params=params if params is not None else {"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")


async def extract_bytes_with_schema(
    *,
    content: bytes,
    filename: str,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: dict[str, Any] | None = None,
    global_notes: str = "",
) -> dict[str, Any]:
    """Extract from raw multipart bytes without writing the upload to workspace."""
    if not schema:
        raise ValueError("schema must be non-empty")
    from app.tools.schema import _bytes_to_block

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    block = _bytes_to_block(content, ext)
    user_blocks: list[ContentBlock] = (
        [TextBlock(text=global_notes)] if global_notes else []
    ) + [TextBlock(text=_build_field_instructions(schema)), block]
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=_build_response_schema(schema),
        params=params or {"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")


