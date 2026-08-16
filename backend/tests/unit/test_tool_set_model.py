"""set_model(role=) folds the four identical `(slug, model_id)` setters.

They had byte-identical input schemas, all idempotent, all non-destructive,
and zero recorded calls across 764 chat tool_calls + 145 remote MCP calls —
the textbook case for the four merge criteria (same noun, same input shape,
same policy, no destructive member)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools import build_emerge_mcp, registered_tool_names
from app.tools.projects import create_project


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


@pytest.mark.parametrize(
    "role", ["extract", "labeler", "proposer", "translate"],
)
async def test_set_model_writes_the_role(
    workspace: Path, stub_provider: AsyncMock, role: str,
) -> None:
    from app.tools.model import create_model
    from app.tools.project_config import get_project_config

    slug = (await create_project(workspace, name="p"))["slug"]
    # `extract` resolves through `switch_active_model`, which (unlike the
    # other three roles) validates the target against a real
    # `models/{mid}.json` — model_id is minted server-side, never hand-typed.
    # labeler/proposer/translate accept any raw provider id string, no
    # models/*.json entry required (see domains/self.md).
    model_id = (
        await create_model(
            workspace, slug, label="t",
            provider="google", provider_model_id="gemini-2.5-flash",
        )
        if role == "extract" else "m_test"
    )
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    await _call(server, "set_model", {
        "slug": slug, "role": role, "model_id": model_id,
    })
    cfg = await get_project_config(workspace, slug)
    if role == "extract":
        assert cfg["extract"]["model_id"] == model_id
    else:
        assert cfg[role]["resolved"] == model_id or cfg[role]["override"] == model_id


async def test_set_model_rejects_unknown_role(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """`role` is schema-constrained to the four tunable axes, so the MCP
    server's own jsonschema `validate_input` gate (mcp/server/lowlevel/
    server.py) rejects `agent_brain` before `t_set_model`'s body ever runs —
    confirmed empirically: the handler's own `_error_envelope` branch never
    fires for a real dispatched call. That branch stays as defense-in-depth
    for any caller that reaches the handler directly, bypassing dispatch."""
    slug = (await create_project(workspace, name="p"))["slug"]
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "set_model", {
        "slug": slug, "role": "agent_brain", "model_id": "m",
    })
    assert res.root.isError is True
    assert "agent_brain" in res.root.content[0].text


def test_the_four_old_setters_are_gone() -> None:
    live = registered_tool_names(headless=True)
    for old in (
        "set_labeler_model", "set_proposer_model",
        "set_translate_model", "switch_active_model",
    ):
        assert old not in live, f"{old} should have been folded into set_model"
    assert "set_model" in live
