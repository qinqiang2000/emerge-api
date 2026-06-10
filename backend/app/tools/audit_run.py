"""`run_audit` — audit ONE project's group of documents against its rules.

An audit project holds a single business's related documents in its own `docs/`
(报价单 + 收货单 + 订单 + …, any types) and a set of NL compliance rules. There
is NO multi-project anchor/source wiring — that was the matching (对账) model,
wrong for auditing one business's set. `run_audit` reads every document in the
project's `docs/`, sends each as an image (the source of truth) plus the rules,
and writes `audits/{run}/report.json`.

Documents do NOT need to be extracted — the judge reads the images directly; any
existing extracted fields are passed only as a hint. The judge model is resolved
from the project's own active model (provider-direct; never the agent's SDK).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.match.audit import audit_group
from app.provider.base import ImageBlock, Provider
from app.schemas.match import AuditReport
from app.tools.docs import list_docs, read_doc_image
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_audit_run_id
from app.workspace.paths import audit_result_path, prediction_draft_path


class AuditError(Exception):
    """Audit precondition failure, carrying a stable error_code for the envelope."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_message_en = message


def _load_fields(workspace: Path, slug: str, filename: str) -> Optional[dict]:
    """First extracted entity for a doc, or None — OPTIONAL hint for audit, not a
    prerequisite."""
    p = prediction_draft_path(workspace, slug, filename)
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


async def run_audit(
    workspace: Path,
    slug: str,
    *,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Audit the project `slug`: read its audit rules + every document in its
    `docs/`, judge all rules in one LLM trip (images = source of truth, any
    extracted fields = hint), and persist the report. Returns the report dict.
    Raises `AuditError` when rules or documents are missing."""
    from app.tools.match_prompt import MatchPromptNotFoundError, read_active_match_prompt
    try:
        mpv = await read_active_match_prompt(workspace, slug)
        audit_rules = list(mpv.audit_rules)
    except MatchPromptNotFoundError:
        audit_rules = []
    if not audit_rules:
        raise AuditError(
            "audit_no_rules", "no audit rules set — call write_audit_rules first",
        )

    docs = await list_docs(workspace, slug)
    doc_images: dict[str, list[ImageBlock]] = {}
    doc_fields: dict[str, dict] = {}
    for d in docs:
        fn = d.get("filename")
        if not fn:
            continue
        try:
            out = await read_doc_image(workspace, slug, fn, page=1)
        except Exception:
            continue  # skip docs that don't render to an image
        doc_images[fn] = [ImageBlock(media_type=out["mime"], data_b64=out["data"])]
        fields = _load_fields(workspace, slug, fn)
        if fields is not None:
            doc_fields[fn] = fields

    if not doc_images:
        raise AuditError(
            "audit_no_docs",
            "project has no readable documents — upload the group (报价单/收货单/…) first",
        )

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
        group={fn: fn for fn in doc_images},   # the documents that were audited
        checks=checks,
        overall=overall,
    )
    out_path = audit_result_path(workspace, slug, run_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, report.model_dump(mode="json"))
    return report.model_dump(mode="json")


async def _resolve_judge_provider(
    workspace: Path, slug: str,
) -> tuple[Optional[Provider], Optional[str]]:
    """(provider, model_id) for the judge from the project's own active model —
    provider-direct (extract/judge tier), never the agent's SDK. (None, None) if
    unresolvable → engine runs pure-`unclear`."""
    try:
        from app.provider import get_provider_for_model
        from app.tools.model import read_active_model

        mc = await read_active_model(workspace, slug)
        return get_provider_for_model(mc.provider_model_id, provider=mc.provider), mc.provider_model_id
    except Exception:
        return None, None
