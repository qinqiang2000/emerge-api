"""`run_audit` — audit one grouped set of documents against the project's rules.

A0 takes the group explicitly (manual grouping): an anchor doc + one source doc
per source project. It loads each doc's already-extracted fields, attaches the
anchor document's image (so visual rules like "盖了红章" can be judged), runs
`audit_group`, and writes `audits/{run}/report.json`.

Provider for the judge is resolved from the match project's own active model
(the design's "L2 judge tier"); with none usable, every rule comes back
`unclear` (audit is inherently LLM-judged — no deterministic fallback).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.match.audit import audit_group
from app.provider.base import ImageBlock, Provider
from app.schemas.match import AuditReport
from app.tools.docs import read_doc_image
from app.tools.match_project import MatchProjectError, read_match_project
from app.tools.match_prompt import read_active_match_prompt
from app.tools.match_run import _resolve_judge_provider
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_audit_run_id
from app.workspace.paths import audit_result_path, prediction_draft_path


def _load_fields(workspace: Path, project: str, filename: str) -> Optional[dict]:
    """First extracted entity (the doc's field record) from its draft, or None
    when the doc hasn't been extracted — fields are an OPTIONAL hint for audit,
    not a prerequisite."""
    p = prediction_draft_path(workspace, project, filename)
    if not p.exists():
        return None
    try:
        ents = json.loads(p.read_text(encoding="utf-8")).get("entities")
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                return e
    return None


async def _doc_images(workspace: Path, project: str, filename: str) -> list[ImageBlock]:
    """Render a doc to image block(s) — the audit judge's source of truth. A0
    uses page 1 (the demo docs are single-page or key-info-on-p1); full-page
    coverage is A1. Raises if the doc file is missing (audit needs the doc)."""
    out = await read_doc_image(workspace, project, filename, page=1)
    return [ImageBlock(media_type=out["mime"], data_b64=out["data"])]


async def run_audit(
    workspace: Path,
    slug: str,
    *,
    anchor_doc: str,
    source_docs: dict[str, str],
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Audit one group in a single LLM trip: the judge reads the DOCUMENT IMAGES
    (source of truth) + the audit rules, with any pre-extracted fields passed
    only as a hint. `source_docs` maps source-project slug → its doc in the
    group. Returns the report dict. Raises MatchProjectError on a bad group
    (unknown source / missing doc / no rules)."""
    project = await read_match_project(workspace, slug)
    anchor_project = project["anchor_project"]
    valid_sources = set(project["source_projects"])

    bad = [s for s in source_docs if s not in valid_sources]
    if bad:
        raise MatchProjectError(
            "audit_unknown_source",
            f"group references unknown source project(s): {', '.join(bad)}",
        )

    from app.tools.match_prompt import MatchPromptNotFoundError
    try:
        mpv = await read_active_match_prompt(workspace, slug)
        audit_rules = list(mpv.audit_rules)
    except MatchPromptNotFoundError:
        audit_rules = []  # no prompt yet == no rules
    if not audit_rules:
        raise MatchProjectError(
            "audit_no_rules",
            "no audit rules set — call write_audit_rules first",
        )

    # Load each doc as image(s) (source of truth, required) + optional fields
    # (hint, only if already extracted). Keyed by project slug = role in group.
    group_files: dict[str, str] = {anchor_project: anchor_doc}
    group_files.update(source_docs)
    doc_images: dict[str, list[ImageBlock]] = {}
    doc_fields: dict[str, dict] = {}
    for role, filename in group_files.items():
        try:
            doc_images[role] = await _doc_images(workspace, role, filename)
        except Exception:
            raise MatchProjectError(
                "audit_doc_not_found",
                f"document '{filename}' not found in project '{role}'",
            )
        fields = _load_fields(workspace, role, filename)
        if fields is not None:
            doc_fields[role] = fields

    if provider is None:
        provider, resolved_model = await _resolve_judge_provider(workspace, slug)
        model_id = model_id or resolved_model

    checks = await audit_group(
        doc_images=doc_images,
        audit_rules=audit_rules,
        doc_fields=doc_fields or None,
        provider=provider,
        model_id=model_id,
    )
    overall = "fail" if any(c.status == "fail" for c in checks) else "pass"

    run_id = new_audit_run_id()
    report = AuditReport(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        group=group_files,
        checks=checks,
        overall=overall,
    )
    out_path = audit_result_path(workspace, slug, run_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, report.model_dump(mode="json"))
    return report.model_dump(mode="json")
