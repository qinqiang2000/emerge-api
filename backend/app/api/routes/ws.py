"""Workspace filesystem HTTP twins — the dual-form mirror of the ``ws_*`` MCP
tools (plan ``2026-06-09-filesystem-over-mcp.md``; symmetry invariant requires
every tool have a live route). Team-scoped via ``current_ws()`` exactly like the
rest of ``/lab/*``; the pure logic lives in ``app/tools/workspace_fs.py`` and is
shared with the MCP tool bodies, so containment is enforced identically on both
forms. These let a CLI / curl client drive the same filesystem bus a remote MCP
agent uses.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import bind_workspace, current_ws
from app.tools import workspace_fs

router = APIRouter(dependencies=[Depends(bind_workspace)])


def _guard(call):
    try:
        return call()
    except workspace_fs.WsPathError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ws_path_blocked", "error_message_en": str(exc)},
        )


@router.get("/lab/ws/list")
async def ws_list(path: str = ".", recursive: bool = False) -> dict:
    return _guard(lambda: workspace_fs.ws_list(current_ws(), path, recursive))


@router.get("/lab/ws/read")
async def ws_read(path: str = Query(...)) -> dict:
    return _guard(lambda: workspace_fs.ws_read(current_ws(), path))


@router.get("/lab/ws/grep")
async def ws_grep(pattern: str = Query(...), path: str = ".", glob: str | None = None) -> dict:
    return _guard(lambda: workspace_fs.ws_grep(current_ws(), pattern, path, glob))


class _WriteBody(BaseModel):
    file_path: str
    content: str


@router.post("/lab/ws/write")
async def ws_write(body: _WriteBody) -> dict:
    return _guard(lambda: workspace_fs.ws_write(current_ws(), body.file_path, body.content))


class _EditBody(BaseModel):
    file_path: str
    old_string: str
    new_string: str
    replace_all: bool = False


@router.post("/lab/ws/edit")
async def ws_edit(body: _EditBody) -> dict:
    return _guard(lambda: workspace_fs.ws_edit(
        current_ws(), body.file_path, body.old_string, body.new_string, body.replace_all))


class _MoveBody(BaseModel):
    source_path: str
    destination_path: str
    # named `copy` on the wire (mirrors the MCP tool arg); aliased because
    # `copy` shadows a BaseModel attribute
    copy_: bool = Field(False, alias="copy")


@router.post("/lab/ws/move")
async def ws_move(body: _MoveBody) -> dict:
    return _guard(lambda: workspace_fs.ws_move(
        current_ws(), body.source_path, body.destination_path, body.copy_))
