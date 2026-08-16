from pathlib import Path
from unittest.mock import AsyncMock

import mcp.types as mcp_types

from app.tools import build_emerge_mcp
from app.tools import _emerge_tool_names


async def test_build_emerge_mcp_lists_tools(workspace: Path, stub_provider: AsyncMock) -> None:
    """Step B trimmed the filesystem-wrapper tools (`list_*`, `get_*`, `read_*`,
    `upload_doc`, `delete_prompt|model|experiment`, `ingest_local_path`,
    `import_prompt`, `create_prompt|model`, `write_prompt|model`,
    `archive_experiment`) — SDK built-in Bash/Glob/Grep/Read/Write/Edit covers
    them under `_workspace_safety_gate`. What stays registered is the
    business moat: provider-bound extract/label, schema atomicity, doc
    vision, lifecycle ops, UI bridge. `delete_doc` / `rename_project` later
    came back (P4 Task 1) — filename/slug is a primary key shared with
    sibling artifacts, so Bash rm/mv silently orphans them; see
    `build_emerge_mcp`'s docstring."""
    from app.jobs.runner import JobRunner
    runner = JobRunner(workspace=workspace, provider=stub_provider)
    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=runner)
    names = await _extract_tool_names(server)
    expected = {
        "create_project",
        "derive_schema",
        "write_schema",
        "extract_one",
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
    # `rename_project` / `delete_doc` are deliberately absent here — P4 Task 1
    # (2026-08-16) restored their registration (see `build_emerge_mcp`'s
    # docstring); they are no longer cut tools.
    cut = {
        "list_projects", "upload_doc", "ingest_local_path",
        "list_docs", "read_schema", "get_pending",
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
    """Mirror of the prompt-axis story: only `set_model` (role='extract')
    survives; CRUD of models/*.json is Write/Edit/Glob/Bash. P4 Task 4 folded
    `switch_active_model` into `set_model` alongside the labeler/proposer/
    translate setters — same tool, selected by `role`."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert "set_model" in names


def test_model_axis_tools_in_emerge_tool_names() -> None:
    names = _emerge_tool_names()
    assert "set_model" in names


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


async def test_label_docs_tools_are_registered(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """Pro Labeler ships `label_docs` (atomic small-batch — what
    `pre_label_runner` subagent loops over) + `set_model` (role='labeler';
    provider HTTP + project.json mutation — P4 Task 4 folded the old
    `set_labeler_model` into it). `get_pending` was cut — `Read
    reviewed/_pending/<f>.json` via SDK Read covers it."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert {"label_docs", "set_model"}.issubset(names), names
    # Legacy `pre_label` must be gone — no deprecated alias.
    assert "pre_label" not in names, names
    canonical = _emerge_tool_names()
    for n in ("label_docs", "set_model"):
        assert n in canonical, f"missing {n!r} in _EMERGE_TOOL_NAMES"
    assert "pre_label" not in canonical


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


async def test_delete_project_registered(
    workspace: Path, stub_provider: AsyncMock,
) -> None:
    """`delete_project` was intended to land in Phase 1 of unbound-chat
    (commit 7286c5e) but its `@tool` decorator slipped past both the
    `tools=[...]` list passed to `create_sdk_mcp_server` and the
    `_EMERGE_TOOL_NAMES` canonical tuple. M11 T14's symmetry invariant
    surfaced the omission. This test pins the registration so the same
    regression — decorator present, registration missing — can't recur
    silently. The pairing with `create_project` is deliberate: lifecycle
    create/delete are dual ops and the agent needs both to discover via
    the MCP listing."""
    from unittest.mock import MagicMock
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    names = await _extract_tool_names(server)
    assert "delete_project" in names
    assert "delete_project" in _emerge_tool_names()


async def test_every_decorated_tool_is_actually_registered() -> None:
    """A `@tool` decorator that never lands in the `tools=[...]` list passed to
    `create_sdk_mcp_server` is invisible to EVERY surface — chat, stdio, remote —
    while still satisfying the symmetry invariant (which used to scan source
    text). That is how nine tools with live HTTP routes, unit tests and skill
    prose ended up unreachable. `test_delete_project_registered` pinned exactly
    one name against this; this is the general form."""
    import re
    from pathlib import Path

    import app.tools as tools_pkg
    from app.tools import registered_tool_names

    src = Path(tools_pkg.__file__).resolve().read_text(encoding="utf-8")
    decorated = set(re.findall(r'@tool\(\s*"([a-z_][a-z0-9_]*)"', src))
    registered = registered_tool_names(headless=True)

    missing = decorated - registered
    assert not missing, (
        f"@tool decorated but never registered (invisible to every agent): "
        f"{sorted(missing)}. Append the t_* function to the `_tools` list in "
        f"build_emerge_mcp."
    )


async def test_filesystem_lookalike_tools_are_reachable() -> None:
    """delete_doc / rename_doc / rename_project / forget_memory read like rm/mv
    wrappers but aren't (INSIGHTS: filename is the primary key of four sibling
    artifacts; MEMORY.md index and note body must move together). If they leave
    the surface again the agent falls back to Bash rm/mv and silently corrupts
    the set — the exact failure those tools exist to prevent.

    `history_log`/`history_diff` folded into `history(op=)` in P4 Task 11;
    `history_restore` stays separate (mutates) — see `app.tools._merged`."""
    from app.tools import registered_tool_names

    names = registered_tool_names(headless=True)
    for n in (
        "delete_doc", "rename_doc", "rename_project", "forget_memory",
        "list_trash", "restore_from_trash",
        "history", "history_restore",
    ):
        assert n in names, f"{n} fell off the registration list again"
