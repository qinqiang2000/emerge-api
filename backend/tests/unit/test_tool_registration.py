from pathlib import Path
from unittest.mock import AsyncMock

import mcp.types as mcp_types

from app.tools import build_emerge_mcp
from app.tools import _emerge_tool_names


async def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    """Step B trimmed the filesystem-wrapper tools (`list_*`, `get_*`, `read_*`,
    `upload_doc`, `delete_*`, `ingest_local_path`, `rename_project`,
    `import_prompt`, `create_prompt|model`, `write_prompt|model`,
    `archive_experiment`) — SDK built-in Bash/Glob/Grep/Read/Write/Edit covers
    them under `_workspace_safety_gate`. What stays registered is the
    business moat: provider-bound extract/label, schema atomicity, doc
    vision, lifecycle ops, UI bridge."""
    from app.jobs.runner import JobRunner
    runner = JobRunner(workspace=workspace, provider=stub_provider, model_id="stub")
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=runner)
    names = await _extract_tool_names(server)
    expected = {
        "create_project",
        "derive_schema",
        "write_schema",
        "extract_one",
        "extract_batch",
        "pdf_render_page",
        "read_doc_image",
        # M2A additions
        "save_reviewed",
        "score",
        # M2C additions
        "start_job",
        "get_job",
        "pause_job",
        "resume_job",
        "cancel_job",
    }
    assert expected.issubset(names), (expected - names, names)

    # Step B negative assertion — cut tools must NOT be registered. Catches
    # regressions where someone re-adds a wrapper tool by reflex.
    cut = {
        "rename_project", "list_projects", "upload_doc", "ingest_local_path",
        "list_docs", "delete_doc", "read_schema", "get_pending",
        "create_prompt", "write_prompt", "list_prompts", "delete_prompt",
        "create_model", "write_model", "list_models", "delete_model",
        "archive_experiment", "list_experiments", "delete_experiment",
        "import_prompt", "list_reviewed", "get_reviewed", "get_prediction",
    }
    assert cut.isdisjoint(names), cut & names


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
    """Step B kept only `switch_active_prompt` on the prompt axis — flipping
    active is a project.json mutation that needs lock-protected atomicity,
    so SDK Write/Edit can't replace it. CRUD of prompts/*.json files (create
    / write / list / delete) is now Write/Edit/Glob/Bash territory."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert "switch_active_prompt" in names


def test_prompt_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    assert "switch_active_prompt" in names


async def test_model_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """Mirror of the prompt-axis story: only `switch_active_model` survives;
    CRUD of models/*.json is Write/Edit/Glob/Bash."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert "switch_active_model" in names


def test_model_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    assert "switch_active_model" in names


async def test_experiment_axis_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """Step B cut `archive_experiment`, `list_experiments`, `delete_experiment`
    (Bash mv to a graveyard dir / `Glob experiments/*/meta.json` / `Bash rm -r`
    cover them). The four kept tools each have business semantics SDK
    built-ins can't reproduce: upsert-by-axes pair, provider HTTP, eval loop
    + score persistence, atomic active flip + draft re-seed."""
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
    }.issubset(names), names


def test_experiment_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    for n in (
        "create_experiment",
        "extract_with_experiment",
        "run_experiment_eval",
        "promote_experiment",
    ):
        assert n in names, f"missing {n!r} in _EMERGE_TOOL_NAMES"


def test_fork_in_emerge_tool_names() -> None:
    """`fork_project` survives Step B (project skeleton init + hardlink
    semantics aren't safely reproducible from Bash cp). `import_prompt` was
    cut in favor of `Bash cp src/prompts/X.json dst/prompts/`."""
    from app.tools import _EMERGE_TOOL_NAMES
    assert "fork_project" in _EMERGE_TOOL_NAMES
    assert "import_prompt" not in _EMERGE_TOOL_NAMES


async def test_pre_label_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """Pro Labeler kept `pre_label` + `set_labeler_model` (provider HTTP +
    project.json mutation). `get_pending` was cut — `Read reviewed/_pending/<f>.json`
    via SDK Read covers it."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {"pre_label", "set_labeler_model"}.issubset(names), names
    canonical = _emerge_tool_names()
    for n in ("pre_label", "set_labeler_model"):
        assert n in canonical, f"missing {n!r} in _EMERGE_TOOL_NAMES"


async def test_read_doc_image_registered(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """`read_doc_image` is the pull-mode vision tool added by the
    progressive-doc-vision plan (2026-05-16). Mirrors the assertion shape
    used for the other "tool exists" smoke checks above — present in both
    the live MCP server and the `_EMERGE_TOOL_NAMES` canonical tuple."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert "read_doc_image" in names
    assert "read_doc_image" in _emerge_tool_names()
