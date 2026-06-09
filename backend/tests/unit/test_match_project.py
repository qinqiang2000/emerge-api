"""Match-project creation + reference validation (app/tools/match_project.py)."""
from __future__ import annotations

import json

import pytest

from app.tools.match_project import (
    MatchProjectError,
    create_match_project,
    is_match_project,
    read_match_project,
)
from app.tools.projects import create_project
from app.workspace.paths import project_json_path


async def _extract_project(ws, name) -> str:
    return (await create_project(ws, name=name))["slug"]


async def test_create_match_project_stamps_references(workspace):
    anchor = await _extract_project(workspace, "invoices")
    src = await _extract_project(workspace, "payments")
    out = await create_match_project(workspace, name="对账", anchor=anchor, sources=[src])
    slug = out["slug"]

    blob = json.loads(project_json_path(workspace, slug).read_text())
    assert blob["project_type"] == "match"
    assert blob["anchor_project"] == anchor
    assert blob["source_projects"] == [src]
    assert blob["active_match_prompt_id"] is None
    assert is_match_project(workspace, slug)

    read = await read_match_project(workspace, slug)
    assert read["anchor_project"] == anchor and read["source_projects"] == [src]


async def test_create_rejects_missing_reference(workspace):
    anchor = await _extract_project(workspace, "invoices")
    with pytest.raises(MatchProjectError) as ei:
        await create_match_project(workspace, name="x", anchor=anchor, sources=["nope"])
    assert ei.value.error_code == "match_ref_not_found"


async def test_create_rejects_empty_sources(workspace):
    anchor = await _extract_project(workspace, "invoices")
    with pytest.raises(MatchProjectError) as ei:
        await create_match_project(workspace, name="x", anchor=anchor, sources=[])
    assert ei.value.error_code == "match_no_sources"


async def test_create_rejects_source_equal_anchor(workspace):
    anchor = await _extract_project(workspace, "invoices")
    with pytest.raises(MatchProjectError) as ei:
        await create_match_project(workspace, name="x", anchor=anchor, sources=[anchor])
    assert ei.value.error_code == "match_source_is_anchor"


async def test_create_rejects_duplicate_source(workspace):
    anchor = await _extract_project(workspace, "invoices")
    src = await _extract_project(workspace, "payments")
    with pytest.raises(MatchProjectError) as ei:
        await create_match_project(workspace, name="x", anchor=anchor, sources=[src, src])
    assert ei.value.error_code == "match_duplicate_source"


async def test_create_rejects_match_project_as_reference(workspace):
    anchor = await _extract_project(workspace, "invoices")
    src = await _extract_project(workspace, "payments")
    mp = await create_match_project(workspace, name="m1", anchor=anchor, sources=[src])
    # using a match project as a source must be rejected
    with pytest.raises(MatchProjectError) as ei:
        await create_match_project(workspace, name="m2", anchor=anchor, sources=[mp["slug"]])
    assert ei.value.error_code == "match_ref_is_match_project"


async def test_read_non_match_project_raises(workspace):
    extract = await _extract_project(workspace, "invoices")
    with pytest.raises(MatchProjectError) as ei:
        await read_match_project(workspace, extract)
    assert ei.value.error_code == "not_a_match_project"
