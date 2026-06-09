"""Pairing engine: anchor docs × each source → reconcile cards.

P0 strategy (lab scale is small, so no blocking yet — that's P0.5):
  1. For every anchor doc, score it against every candidate doc in each source
     via `judge_pair`.
  2. Greedy 1:1 assignment **within each source**: candidates sorted by score
     desc; an (anchor_doc, source_doc) pair is claimed when both are still free
     and the pair's status is `match` (score ≥ threshold). Each source assigns
     independently.
  3. Assemble one `MatchCard` per anchor (best pair or `missing` per source) +
     per-source `orphans` (source docs no anchor claimed).

Reads extract RESULTS only (`predictions/_draft/{doc}.json` → `entities`).
First entity per doc is used as the document's field record (P0 assumes one
record per doc; multi-entity docs are out of P0 scope). Docs with no draft are
skipped and reported.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.match.judge import judge_pair
from app.schemas.match import (
    MatchCard,
    MatchPromptVariant,
    MatchResult,
    PairVerdict,
)
from app.schemas.schema_field import SchemaField
from app.provider.base import Provider
from app.tools.docs import list_docs
from app.tools.prompt import read_active_prompt
from app.workspace.paths import prediction_draft_path


# Default greedy-assignment threshold. A pair must be judged `match` to be
# claimed; `match` already means all keys agree (or L2 said same), so the
# threshold only guards against ever pairing on a non-match. Kept as a named
# constant so a future per-prompt override has an anchor.
_MATCH_STATUS = "match"


def _load_entities(workspace: Path, slug: str, filename: str) -> Optional[list[dict]]:
    """Return the `entities` list from a doc's draft prediction, or None when
    the draft is missing/unreadable."""
    p = prediction_draft_path(workspace, slug, filename)
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ents = blob.get("entities")
    return ents if isinstance(ents, list) else None


def _first_record(entities: list[dict]) -> Optional[dict]:
    for e in entities:
        if isinstance(e, dict):
            return e
    return None


async def _schema_by_name(workspace: Path, slug: str) -> dict[str, SchemaField]:
    """Map field name → SchemaField from a project's active prompt. Empty on
    any read failure (judge falls back to tolerance-type-driven comparison)."""
    try:
        pv = await read_active_prompt(workspace, slug)
    except Exception:
        return {}
    out: dict[str, SchemaField] = {}
    for f in pv.schema:
        if f.name:
            out[f.name] = f
    return out


async def _doc_records(
    workspace: Path, slug: str,
) -> tuple[dict[str, dict], list[str]]:
    """Return ({filename: first_record}, [skipped_filenames]) for one project."""
    records: dict[str, dict] = {}
    skipped: list[str] = []
    for d in await list_docs(workspace, slug):
        fn = d.get("filename")
        if not fn:
            continue
        ents = _load_entities(workspace, slug, fn)
        rec = _first_record(ents) if ents is not None else None
        if rec is None:
            skipped.append(fn)
            continue
        records[fn] = rec
    return records, skipped


async def run_engine(
    workspace: Path,
    *,
    run_id: str,
    anchor_project: str,
    source_projects: list[str],
    match_prompt: MatchPromptVariant,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> MatchResult:
    """Execute the full match: score all candidates, greedily assign 1:1 per
    source, assemble cards + orphans. `provider` (optional) drives the L2
    tie-breaker; with it None the engine is pure-L1 deterministic."""
    anchor_records, _ = await _doc_records(workspace, anchor_project)
    anchor_schema = await _schema_by_name(workspace, anchor_project)

    # Per-source: records + schema + every candidate score against each anchor.
    source_records: dict[str, dict[str, dict]] = {}
    source_schemas: dict[str, dict[str, SchemaField]] = {}
    # candidates[src] = list of (score, anchor_doc, source_doc, verdict)
    candidates: dict[str, list[tuple[float, str, str, PairVerdict]]] = {}

    anchor_docs = sorted(anchor_records.keys())

    for src in source_projects:
        recs, _ = await _doc_records(workspace, src)
        source_records[src] = recs
        source_schemas[src] = await _schema_by_name(workspace, src)
        maps = match_prompt.mappings.get(src, [])
        cand: list[tuple[float, str, str, PairVerdict]] = []
        for a_doc in anchor_docs:
            for s_doc, s_rec in recs.items():
                verdict = await judge_pair(
                    anchor_records[a_doc], s_rec,
                    source=src,
                    mappings_for_source=maps,
                    anchor_schema=anchor_schema,
                    source_schema=source_schemas[src],
                    rules=match_prompt.rules,
                    provider=provider,
                    model_id=model_id,
                )
                cand.append((verdict.score, a_doc, s_doc, verdict))
        candidates[src] = cand

    # Greedy 1:1 assignment per source. Sort by score desc; tie-break by
    # (anchor_doc, source_doc) for determinism.
    # assigned[src][anchor_doc] = (source_doc, verdict)
    assigned: dict[str, dict[str, tuple[str, PairVerdict]]] = {
        src: {} for src in source_projects
    }
    for src in source_projects:
        used_anchor: set[str] = set()
        used_source: set[str] = set()
        ranked = sorted(
            candidates[src],
            key=lambda c: (-c[0], c[1], c[2]),
        )
        for score, a_doc, s_doc, verdict in ranked:
            if verdict.status != _MATCH_STATUS:
                continue
            if a_doc in used_anchor or s_doc in used_source:
                continue
            used_anchor.add(a_doc)
            used_source.add(s_doc)
            assigned[src][a_doc] = (s_doc, verdict)

    # Cards: one per anchor doc, a pair per source.
    cards: list[MatchCard] = []
    for a_doc in anchor_docs:
        pairs: list[PairVerdict] = []
        matched_count = 0
        for src in source_projects:
            hit = assigned[src].get(a_doc)
            if hit is not None:
                s_doc, verdict = hit
                pairs.append(
                    PairVerdict(
                        source=src, doc=s_doc, status="match",
                        mismatched_fields=[], reason=verdict.reason,
                        score=verdict.score,
                    )
                )
                matched_count += 1
            else:
                pairs.append(
                    PairVerdict(
                        source=src, doc=None, status="missing",
                        mismatched_fields=[], reason=None, score=0.0,
                    )
                )
        if matched_count == len(source_projects) and source_projects:
            overall = "complete"
        elif matched_count == 0:
            overall = "unmatched"
        else:
            overall = "partial"
        cards.append(MatchCard(anchor_doc=a_doc, pairs=pairs, overall=overall))

    # Orphans: source docs not claimed by any anchor.
    orphans: dict[str, list[str]] = {}
    for src in source_projects:
        claimed = {s_doc for (s_doc, _) in assigned[src].values()}
        orphans[src] = sorted(set(source_records[src].keys()) - claimed)

    return MatchResult(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        anchor_project=anchor_project,
        source_projects=list(source_projects),
        cards=cards,
        orphans=orphans,
    )
