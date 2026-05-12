from pathlib import Path
from unittest.mock import AsyncMock

import mcp.types as mcp_types

from app.tools import build_emerge_mcp
from app.tools import _emerge_tool_names


async def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    from app.jobs.runner import JobRunner
    runner = JobRunner(workspace=workspace, provider=stub_provider, model_id="stub")
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=runner)
    names = await _extract_tool_names(server)
    expected = {
        "create_project",
        "upload_doc",
        "list_docs",
        "list_projects",
        "derive_schema",
        "read_schema",
        "write_schema",
        "extract_one",
        "extract_batch",
        "pdf_render_page",
        # M2A additions
        "save_reviewed",
        "list_reviewed",
        "get_reviewed",
        "get_prediction",
        "score",
        # M2C additions
        "start_job",
        "get_job",
        "pause_job",
        "resume_job",
        "cancel_job",
    }
    assert expected.issubset(names), (expected - names, names)


def test_publish_tools_are_registered(workspace: Path, stub_provider: AsyncMock) -> None:
    from unittest.mock import MagicMock

    job_runner = MagicMock()
    build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=job_runner)
    names = _emerge_tool_names()
    assert "readiness_check" in names
    assert "contract_diff" in names
    assert "freeze_version" in names
    assert "issue_api_key" in names


async def _extract_tool_names(server) -> set[str]:
    """Extract registered tool names from an SDK MCP server config dict.

    create_sdk_mcp_server returns a McpSdkServerConfig TypedDict:
      {'type': 'sdk', 'name': str, 'instance': mcp.server.lowlevel.Server}
    The instance has a ListToolsRequest handler registered in request_handlers.
    """
    instance = server["instance"]
    handler = instance.request_handlers.get(mcp_types.ListToolsRequest)
    if handler is None:
        raise AttributeError(f"No ListToolsRequest handler on {type(instance).__name__}")
    result = await handler(mcp_types.ListToolsRequest(method="tools/list"))
    return {t.name for t in result.root.tools}


async def test_prompt_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {
        "write_prompt",
        "create_prompt",
        "switch_active_prompt",
        "list_prompts",
        "delete_prompt",
    }.issubset(names), names


def test_prompt_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in ("write_prompt", "create_prompt", "switch_active_prompt", "list_prompts", "delete_prompt"):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"


async def test_model_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {
        "write_model",
        "create_model",
        "switch_active_model",
        "list_models",
        "delete_model",
    }.issubset(names), names


def test_model_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in ("write_model", "create_model", "switch_active_model", "list_models", "delete_model"):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"


async def test_experiment_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {
        "create_experiment",
        "extract_with_experiment",
        "run_experiment_eval",
        "promote_experiment",
        "archive_experiment",
        "list_experiments",
        "delete_experiment",
    }.issubset(names), names


def test_experiment_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in (
        "create_experiment",
        "extract_with_experiment",
        "run_experiment_eval",
        "promote_experiment",
        "archive_experiment",
        "list_experiments",
        "delete_experiment",
    ):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"
