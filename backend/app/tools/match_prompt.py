"""Match-prompt CRUD — the versioned carrier of matching rules.

Mirrors `app/tools/prompt.py::write_prompt`: a content hash over the
*content* (mappings + rules) drives version-bump-on-change, every distinct
version is snapshotted under `match_prompts/_versions/{id}/v{n}.json`, and the
head is mutated in place. The match project tracks one active match prompt in
`project.json.active_match_prompt_id`.

`write_match_prompt` upserts the project's single active match prompt: it mints
one on first call, then mutates it in place on subsequent calls. (P0 keeps a
single match prompt per project; A/B of two match prompts is P1.)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.match import AuditRule, KeyMapping, MatchPromptVariant
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_match_prompt_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    match_prompt_path,
    match_prompt_version_path,
    match_prompt_versions_dir,
    match_prompts_dir,
    project_json_path,
)


class MatchPromptNotFoundError(Exception):
    """Raised when read targets a match prompt that does not exist on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(
    mappings: dict[str, list[KeyMapping]], rules: str, audit_rules: list[AuditRule],
) -> str:
    """Stable fingerprint of a match prompt's content — mappings + rules +
    audit_rules. Label is excluded (cosmetic). Mirrors `prompt._content_hash`.
    Audit rules hash over their canonical model dump so the same content always
    yields the same hash regardless of input spelling (bare string vs object);
    the one-time hash change vs the pure-str era just bumps the version on the
    next real write — acceptable by design."""
    payload = {
        "mappings": {
            src: [m.model_dump(mode="json", exclude_none=True) for m in maps]
            for src, maps in sorted(mappings.items())
        },
        "rules": rules,
        "audit_rules": [
            r.model_dump(mode="json", exclude_none=True) for r in audit_rules
        ],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _snapshot_version(workspace: Path, slug: str, mpv: MatchPromptVariant) -> None:
    vp = match_prompt_version_path(workspace, slug, mpv.prompt_id, mpv.version)
    match_prompt_versions_dir(workspace, slug, mpv.prompt_id).mkdir(
        parents=True, exist_ok=True,
    )
    atomic_write_json(vp, mpv.model_dump(mode="json", exclude_none=True))


def _coerce_mappings(
    mappings: dict[str, list[dict]] | dict[str, list[KeyMapping]],
) -> dict[str, list[KeyMapping]]:
    out: dict[str, list[KeyMapping]] = {}
    for src, maps in (mappings or {}).items():
        coerced: list[KeyMapping] = []
        for m in maps:
            coerced.append(m if isinstance(m, KeyMapping) else KeyMapping(**m))
        out[src] = coerced
    return out


def _coerce_audit_rules(
    audit_rules: list[str | dict | AuditRule] | None,
) -> list[AuditRule]:
    """Mixed str/object/model input → list[AuditRule] (bare string = critical
    rule, no check — AuditRule's own validator does the coercion)."""
    return [
        r if isinstance(r, AuditRule) else AuditRule.model_validate(r)
        for r in (audit_rules or [])
    ]


async def write_match_prompt(
    workspace: Path,
    slug: str,
    *,
    mappings: dict[str, list[dict]] | dict[str, list[KeyMapping]] | None = None,
    rules: str | None = None,
    audit_rules: list[str | dict | AuditRule] | None = None,
    label: str = "",
    reason: str = "",  # accepted for tool symmetry / audit; not persisted
) -> str:
    """Upsert the project's active match prompt. Each of `mappings`/`rules`/
    `audit_rules` is a PARTIAL update — pass it to change that facet, omit (None)
    to preserve the current value (defaults on first mint: {} / "" / []). This
    lets `write_match_prompt` (pairing) and `write_audit_rules` (audit) touch
    their own facet without clobbering the other.

    Mints a new prompt (version 1) when none is active; otherwise mutates the
    active head in place, bumping `version` + snapshotting only when the content
    actually changes (a no-op save keeps the version). Sets
    `project.json.active_match_prompt_id`. Holds `project_lock`.
    """
    async with project_lock(workspace, slug):
        pj = project_json_path(workspace, slug)
        project = json.loads(pj.read_text(encoding="utf-8"))
        active = project.get("active_match_prompt_id")
        now = _now_iso()
        match_prompts_dir(workspace, slug).mkdir(parents=True, exist_ok=True)

        if not active:
            coerced = _coerce_mappings(mappings or {})
            r = rules or ""
            ar = _coerce_audit_rules(audit_rules)
            mpr_id = new_match_prompt_id()
            mpv = MatchPromptVariant(
                prompt_id=mpr_id, label=label,
                mappings=coerced, rules=r, audit_rules=ar,
                derived_from=None, created_at=now, updated_at=now,
                version=1, content_hash=_content_hash(coerced, r, ar),
            )
            atomic_write_json(
                match_prompt_path(workspace, slug, mpr_id),
                mpv.model_dump(mode="json", exclude_none=True),
            )
            _snapshot_version(workspace, slug, mpv)
            project["active_match_prompt_id"] = mpr_id
            atomic_write_json(pj, project)
            return mpr_id

        mpr_id = active
        mp = match_prompt_path(workspace, slug, mpr_id)
        existing = MatchPromptVariant(**json.loads(mp.read_text(encoding="utf-8")))
        # Partial update: keep existing facet when its arg is None.
        coerced = _coerce_mappings(mappings) if mappings is not None else existing.mappings
        r = rules if rules is not None else existing.rules
        ar = (
            _coerce_audit_rules(audit_rules)
            if audit_rules is not None
            else list(existing.audit_rules)
        )
        existing_hash = existing.content_hash or _content_hash(
            existing.mappings, existing.rules, existing.audit_rules,
        )
        if existing.content_hash is None:
            _snapshot_version(
                workspace, slug,
                existing.model_copy(update={"content_hash": existing_hash}),
            )
        new_hash = _content_hash(coerced, r, ar)
        changed = new_hash != existing_hash
        new_version = existing.version + 1 if changed else existing.version
        updated = MatchPromptVariant(
            prompt_id=existing.prompt_id,
            label=label or existing.label,
            mappings=coerced, rules=r, audit_rules=ar,
            derived_from=existing.derived_from,
            created_at=existing.created_at, updated_at=now,
            version=new_version, content_hash=new_hash,
        )
        atomic_write_json(mp, updated.model_dump(mode="json", exclude_none=True))
        if changed:
            _snapshot_version(workspace, slug, updated)
        return mpr_id


async def write_audit_rules(
    workspace: Path,
    slug: str,
    *,
    audit_rules: list[str | dict | AuditRule],
    label: str = "",
    reason: str = "",
) -> str:
    """Set the project's audit rules (the compliance checks run by `run_audit`),
    preserving the pairing mappings/rules. Each rule is either a bare NL string
    (= critical, judge-decided) or an object `{rule, level?, check?}` adding a
    severity and/or a deterministic L1 spec. Thin facet-update over
    `write_match_prompt`."""
    return await write_match_prompt(
        workspace, slug, audit_rules=audit_rules, label=label, reason=reason,
    )


async def read_match_prompt(
    workspace: Path, slug: str, mpr_id: str,
) -> MatchPromptVariant:
    mp = match_prompt_path(workspace, slug, mpr_id)
    if not mp.exists():
        raise MatchPromptNotFoundError(f"{mpr_id} not found in project {slug}")
    return MatchPromptVariant(**json.loads(mp.read_text(encoding="utf-8")))


async def read_active_match_prompt(
    workspace: Path, slug: str,
) -> MatchPromptVariant:
    project = json.loads(
        project_json_path(workspace, slug).read_text(encoding="utf-8")
    )
    active = project.get("active_match_prompt_id")
    if not active:
        raise MatchPromptNotFoundError(
            f"project {slug} has no active_match_prompt_id"
        )
    return await read_match_prompt(workspace, slug, active)
