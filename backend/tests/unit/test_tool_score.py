"""score(kind=) folds the three scoring verbs. Inputs were (slug, use_llm_judge?)
/ (slug) / (slug) — same noun, same policy (all provider-touching), compatible
shapes. Return shapes differ per kind and that is fine: the merge criterion
constrains INPUT shape."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools import build_emerge_mcp, registered_tool_names
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.fixture
async def scored_project(workspace: Path) -> str:
    """A project with schema + one _draft prediction + a matching reviewed
    example — enough ground truth for score(kind='extract') to run without
    needing the provider (L1 normalize matches every cell, so the L2 judge is
    never invoked)."""
    schema = [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="d"),
        SchemaField(name="total", type=FieldType.NUMBER, description="d"),
    ]
    slug = (await create_project(workspace, name="score-tool"))["slug"]
    await write_schema(workspace, slug, schema, reason="t", allow_structural=True)
    meta = await upload_doc(workspace, slug, b"\x89PNG\r\n\x1a\nstub", "x.png")
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(workspace, slug) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1", "total": 100}]},
    )
    await save_reviewed(
        workspace, slug, filename,
        entities=[{"invoice_no": "INV-1", "total": 100}],
        source=ReviewedSource.MANUAL,
    )
    return slug


async def test_score_defaults_to_extract_kind(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    slug = scored_project
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {"slug": slug})
    assert "field_accuracy" in res.root.content[0].text


async def test_score_rejects_llm_judge_flag_for_non_extract_kinds(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {
        "slug": scored_project, "kind": "audit", "use_llm_judge": False,
    })
    text = res.root.content[0].text
    assert "score_kind_arg_unsupported" in text


async def test_score_rejects_an_unknown_kind_at_the_schema_layer(
    workspace: Path, stub_provider: AsyncMock, scored_project,
) -> None:
    """The enum is the guard. Asserted here so that deleting it from the schema
    to "simplify" the tool shows up as a failure rather than as a silently
    wider surface."""
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "score", {"slug": scored_project, "kind": "audti"})
    assert "Input validation error" in res.root.content[0].text


def test_old_score_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    assert "score_audit" not in live
    assert "score_match" not in live
    assert "score" in live
