from pathlib import Path
from unittest.mock import AsyncMock

import mcp.types as mcp_types

from app.tools import build_emerge_mcp


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
