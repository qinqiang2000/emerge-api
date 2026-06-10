"""HTTP twins for the document-matching tools (tool↔HTTP symmetry, CLAUDE.md).

Mirrors the `models.py` pattern: team-scoped via `current_ws()`, `{error_code,
error_message_en}` envelopes. Pure logic lives in `app/tools/match_*` +
`app/match/`; these routes are the thin REST face so a CLI/curl client drives the
same reconciliation a remote MCP agent does.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import bind_workspace, current_ws
from app.tools.match_project import (
    MatchProjectError,
    create_match_project,
)
from app.tools.audit_run import run_audit
from app.tools.match_prompt import write_audit_rules, write_match_prompt
from app.tools.match_review import save_reviewed_match, score_match
from app.tools.match_run import run_match

router = APIRouter(dependencies=[Depends(bind_workspace)])


def _envelope(e: MatchProjectError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error_code": e.error_code, "error_message_en": e.error_message_en},
    )


class _CreateMatchBody(BaseModel):
    name: str
    anchor: str
    sources: list[str]


@router.post("/lab/match/projects")
async def post_match_project(body: _CreateMatchBody) -> dict:
    try:
        return await create_match_project(
            current_ws(), name=body.name, anchor=body.anchor, sources=body.sources,
        )
    except MatchProjectError as e:
        raise _envelope(e)


class _WriteMatchPromptBody(BaseModel):
    mappings: dict
    rules: str = ""
    label: str = ""
    reason: str = ""


@router.put("/lab/match/projects/{slug}/prompt")
async def put_match_prompt(slug: str, body: _WriteMatchPromptBody) -> dict:
    mpr_id = await write_match_prompt(
        current_ws(), slug,
        mappings=body.mappings, rules=body.rules, label=body.label, reason=body.reason,
    )
    return {"match_prompt_id": mpr_id}


@router.post("/lab/match/projects/{slug}/run")
async def post_match_run(slug: str) -> dict:
    try:
        return await run_match(current_ws(), slug)
    except MatchProjectError as e:
        raise _envelope(e)


class _ReviewedMatchBody(BaseModel):
    anchor_doc: str
    expected: dict[str, str | None]
    reason: str = ""


@router.post("/lab/match/projects/{slug}/reviewed")
async def post_reviewed_match(slug: str, body: _ReviewedMatchBody) -> dict:
    try:
        return await save_reviewed_match(
            current_ws(), slug,
            anchor_doc=body.anchor_doc, expected=body.expected, reason=body.reason,
        )
    except MatchProjectError as e:
        raise _envelope(e)


@router.get("/lab/match/projects/{slug}/score")
async def get_match_score(slug: str) -> dict:
    try:
        return await score_match(current_ws(), slug)
    except MatchProjectError as e:
        raise _envelope(e)


# --- audit layer (A0) -------------------------------------------------------

class _AuditRulesBody(BaseModel):
    audit_rules: list[str]
    label: str = ""
    reason: str = ""


@router.put("/lab/projects/{slug}/audit-rules")
async def put_audit_rules(slug: str, body: _AuditRulesBody) -> dict:
    mpr_id = await write_audit_rules(
        current_ws(), slug, audit_rules=body.audit_rules,
        label=body.label, reason=body.reason,
    )
    return {"match_prompt_id": mpr_id}


class _RunAuditBody(BaseModel):
    filenames: list[str] | None = None


@router.post("/lab/projects/{slug}/audit")
async def post_audit(slug: str, body: _RunAuditBody | None = None) -> dict:
    from app.tools.audit_run import AuditError
    try:
        return await run_audit(current_ws(), slug, filenames=(body.filenames if body else None))
    except AuditError as e:
        raise HTTPException(
            status_code=400,
            detail={"error_code": e.error_code, "error_message_en": e.error_message_en},
        )
