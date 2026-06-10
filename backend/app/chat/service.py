from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.chat.log import (
    append_event,
    ensure_chat_meta,
    read_chat_session_id,
    write_chat_session_id,
)
from app.chat.ask_user import cancel_pending_ask_user
from app.chat.permissions import cancel_pending, make_gate
from app.chat.redactor import EventRedactor
from app.chat.sse_context import current_chat_id, current_sse_writer
from app.chat.stream import sse_event
from app.jobs import get_runner
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp
from app.tools.docs import fit_image_for_agent
from app.tools.projects import create_project as _create_project
from app.workspace.paths import (
    chat_attachment_path,
    doc_path,
    project_json_path,
    reviewed_dir,
    unbound_chat_attachment_path,
)
from app.workspace.pid_index import get_index
from app.workspace.staging import (
    StagingClaimError,
    claim_staged_to_chat,
    claim_staged_to_unbound_chat,
)


# Filename suffix → Anthropic image media type. PDFs deliberately excluded:
# the agent reaches PDF docs via tools (`extract_one`), not vision inlining,
# so we don't inflate the user-message token cost.
_IMAGE_MEDIA_TYPE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

# Attachment kinds whose bytes we want inlined as image blocks. `doc` is the
# pdf/png/jpg drop path; `None` is the legacy/unset shape from older clients
# (treat as `doc` for back-compat). Schemas / data / notes are text-shaped —
# the agent reads them via the `Read` tool when relevant, NEVER as image
# blocks. Keeping the gate explicit here means a future kind that's also
# visual just adds an entry; the default is "don't waste vision tokens".
_IMAGE_KINDS: frozenset[str | None] = frozenset({None, "doc"})


def _load_image_blocks(
    workspace: Path,
    slug: str,
    chat_id: str,
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build Anthropic image content blocks for any attached images already on
    disk. Silent skip for entries that aren't images, lack `filename`, carry a
    non-doc `kind` (schema/data/note), or whose files we can't read — the
    surrounding `[attachments: ...]` text mention still lets the agent
    reference them by name.

    Dispatches on `source` + slug shape:
      - slug == `_chats` (unbound chat) → `_chats/<chat_id>/attachments/<f>`
      - `source='docs'` (post-promote refs) → reads via `doc_path`
      - default (`source='chat'`) → `<slug>/chats/<chat_id>/attachments/<f>`
    """
    if not attachments:
        return []
    blocks: list[dict[str, Any]] = []
    for a in attachments:
        filename = a.get("filename", "")
        if not (isinstance(filename, str) and filename):
            continue
        # Skip non-doc kinds — schemas / data / notes have no visual payload
        # to inline, and a `kind=schema` yaml that happens to share an image
        # ext would be a bug to image-inline regardless.
        kind = a.get("kind")
        if kind not in _IMAGE_KINDS:
            continue
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        media_type = _IMAGE_MEDIA_TYPE.get(ext)
        if not media_type:
            continue
        source = a.get("source", "chat")
        if slug == _UNBOUND_SLUG:
            # Unbound chat: no project, no docs/ — every attachment is per-chat.
            path = unbound_chat_attachment_path(workspace, chat_id, filename)
        elif source == "docs":
            path = doc_path(workspace, slug, filename)
        else:
            path = chat_attachment_path(workspace, slug, chat_id, filename)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        # SDK boundary: user-attached images go through the same fit as
        # `t_read_doc_image` — three high-res screenshots dropped into one
        # message would otherwise blow the SDK control-protocol buffer just
        # like multi-page tool pulls. Vision-lossless (see fit_image_for_agent
        # design note in app/tools/docs.py).
        data, media_type = fit_image_for_agent(data, media_type)
        b64 = base64.standard_b64encode(data).decode("ascii")
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        )
    return blocks

# Narrow blacklist of tools we never want the agent to reach for. Everything
# else (Bash / Read / Write / Edit / Glob / Grep / Task* / WebFetch / ...) is
# gated by `_workspace_safety_gate` below — workspace-internal ops are auto-
# allowed, sensitive paths hard-blocked, network ops ask the user. The
# `Skill` entry is preserved because emerge ships its skills as system_prompt
# text rather than registering them via the SDK Skill mechanism, so the
# built-in Skill tool would error out with `Unknown skill: emerge-...`.
_SDK_NEVER_TOOLS = ["Skill", "PowerShell"]


# emerge-controlled SDK settings file. Checked into the repo so the agent
# cannot mutate its own deny rules (the file itself is listed in `permissions.deny`
# as Read/Write/Edit). The SDK CLI enforces these patterns *before* invoking
# `can_use_tool`, which is the only reliable way to hard-block `.env` / `*.key`
# reads under SDK 0.1.77 — see INSIGHTS #1.5.
_SDK_SETTINGS_PATH = Path(__file__).parent / "sdk_settings.json"


def _placeholder_project_name() -> str:
    """Auto-name for projects minted by chat_turn when the user drops files
    into the empty-hero state. The `Chat-` prefix signals "this is a
    conversation, not a curated project" — paste/drop files land in
    `chats/<chat_id>/attachments/`, never auto-promoted into `docs/`. The
    agent is expected to rename via `rename_project` once user intent is
    clear (and to call `promote_attachment_to_docs` only on explicit ack)."""
    ts = datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S")
    return f"Chat-{ts}"


def _history_commit_message(user_message: str, slug: str) -> str:
    """One-line git message for a turn snapshot: the user's intent, scoped to the
    project. The diff carries the detail; this just marks "a turn happened"."""
    first = ""
    if user_message and user_message.strip():
        first = user_message.strip().splitlines()[0][:60].strip()
    scoped = slug and slug != _UNBOUND_SLUG
    if scoped:
        return f"turn [{slug}]: {first}" if first else f"turn [{slug}]"
    return f"turn: {first}" if first else "turn"


# Keep strong refs to in-flight commit tasks so the loop doesn't GC them.
_pending_history_commits: set[asyncio.Task] = set()


def _schedule_history_commit(workspace: Path, message: str) -> None:
    """Fire-and-forget a git snapshot of the team workspace for this turn.

    MUST NOT block / be awaited: it's called from `chat_turn`'s generator
    `finally`, and `await`-ing thread work there can deadlock the turn's task
    teardown (it hung the lifecycle tests). Scheduling a detached task keeps the
    semantic commit message while guaranteeing `turn_end` fires immediately.
    Skipped under tests (the conftest sets `EMERGE_DISABLE_PREWARM`) so the suite
    doesn't spawn git per turn; the history wrapper is unit-tested directly."""
    if os.getenv("EMERGE_TEST_MODE") == "1" or os.getenv("EMERGE_DISABLE_PREWARM") == "1":
        return

    async def _do() -> None:
        try:
            from app.workspace import history
            if not history.is_repo(workspace):
                await asyncio.to_thread(history.ensure_repo, workspace)
            await asyncio.to_thread(history.commit_all, workspace, message)
        except Exception:  # noqa: BLE001 — history is never load-bearing
            pass

    try:
        task = asyncio.create_task(_do())
    except RuntimeError:
        return  # no running loop (non-async context) — skip silently
    _pending_history_commits.add(task)
    task.add_done_callback(_pending_history_commits.discard)


# Sentinel for the empty-hero composer (also defined in routes/chat.py).
# Kept here so this module can identify "no project yet" without importing
# the route layer.
_UNSET_SLUG = "p_unset"

# Sentinel for an unbound chat — a conversation that has not been bound to a
# project (yet). Routes events to `_chats/<chat_id>.jsonl` instead of
# `<slug>/chats/<chat_id>.jsonl`. Coexists with `_UNSET_SLUG` during Phase 1
# so the existing frontend's empty-hero mint flow keeps working until the
# Phase 2 frontend cutover migrates it to this sentinel. Must stay in sync
# with `_UNBOUND_SLUG` in `chat/log.py`.
_UNBOUND_SLUG = "_chats"


_WORKSPACE_LAYOUT_TEMPLATE = """{project_dir}/
  docs/                # 源文档（pdf / image / 其它 user-supplied files）
  docs/.meta/          # sidecar metadata — emerge 维护，不要手改
  docs/.meta/_render/  # PDF 渲染缓存 — 不要手改
  prompts/             # 项目 prompt JSON（{{prompt_id}}.json）
  models/              # 项目 model 配置 JSON（{{model_id}}.json）
  experiments/         # autoresearch 实验输出
  versions/            # 冻结的公共 API 版本（v{{n}}.json，从 agent 视角只读）
  reviewed/            # 人工标注 ground truth
  reviewed/_pending/   # label_docs 产生的待审稿
  predictions/_draft/  # 最新提取输出
  chats/               # chat 历史（jsonl）+ chats/<chat_id>/attachments/
  schema.json          # 编辑态 schema — 只能用 write_schema/write_prompt 工具改
  project.json         # 项目配置（active_prompt_id / active_model_id / ...）"""


def _build_active_context(
    workspace: Path, slug: str, chat_id: str, *, interface: str = "browser"
) -> str:
    """Render the "Active context" block that gets spliced into the system
    prompt every turn.

    The agent otherwise has no idea which project the user is *looking at*
    in the UI — it would have to call `list_projects` and guess. This block
    pins the URL/page state (slug + active prompt + active model) plus the
    absolute filesystem paths (so Bash / Glob / Read can be invoked with
    deterministic absolute paths on the first try) directly into the system
    prompt.

    `interface` is `"browser"` (default) when the frontend is active, or
    `"headless"` when called from a CLI agent / MCP client / programmatic
    HTTP caller. Skill prompts gate rendering contracts on this value: in
    browser mode the UI renders rich cards (EvalCard, PublishStage, etc.) and
    the agent stays terse; in headless mode the agent renders full text output.

    Reading `project.json` is best-effort: a freshly-minted project may not
    yet have the file flushed, and a renamed slug between turns may briefly
    point at a stale path. In either case we fall back to a minimal block
    containing just the slug — better than nothing, and the agent can still
    operate.
    """
    workspace_root = workspace.resolve()
    if slug == _UNSET_SLUG:
        return (
            "## Active context\n\n"
            f"interface: {interface}\n\n"
            f"WORKSPACE_ROOT=`{workspace_root}` (absolute)\n\n"
            "The user has NOT selected a project yet (empty-hero state). "
            "No project-scoped tools work until a project is created — call "
            "`create_project` first, then use its returned slug for "
            "subsequent tool calls. Do NOT call `list_projects` to look for "
            "an active project; there isn't one."
        )
    if slug == _UNBOUND_SLUG:
        return (
            "## Active context\n\n"
            f"interface: {interface}\n\n"
            f"WORKSPACE_ROOT=`{workspace_root}` (absolute)\n\n"
            f"You are in an **unbound chat** (no project), chat_id=`{chat_id}`. "
            "Chat history and attachments live under `_chats/`. "
            "Project-scoped tools (`derive_schema`, `write_schema`, "
            "`extract_one`, `promote_attachment_to_docs`, `label_docs`, …) "
            "will raise `chat_not_bound` if called from here. "
            "If the user expresses project intent (`/init`, \"build a schema "
            "for these\", \"make this a project\"), ASK for a name first, "
            "then call `create_project(name=..., from_unbound_chat_id="
            f"\"{chat_id}\")`. That atomically relocates this chat's history "
            "+ attachments under the new project's slug; you then own a "
            "normal project context and the full tool kit unlocks. Do NOT "
            "silently bind a chat to a project on the user's behalf."
        )

    name = slug
    active_prompt_id: str | None = None
    active_model_id: str | None = None
    used_extract_model: str | None = None
    try:
        blob = json.loads(project_json_path(workspace, slug).read_text())
        name = str(blob.get("name") or slug)
        active_prompt_id = blob.get("active_prompt_id")
        active_model_id = blob.get("active_model_id")
    except (OSError, json.JSONDecodeError):
        pass
    # Resolve the live extract model from the active ModelConfig (the runtime
    # source of truth — `tools/extract.py:extract_one_with_schema`'s path).
    # Inlined as a direct file read because this builder is sync (the SDK's
    # system_prompt construction path); `read_active_model` is async-shaped
    # but does no real I/O that warrants awaiting. Best-effort: a fresh /
    # unmigrated project may not have a model file yet — fall back to no
    # surface line rather than echo an env-derived guess.
    if active_model_id:
        from app.workspace.paths import model_path as _model_path

        try:
            mp = _model_path(workspace, slug, active_model_id)
            mblob = json.loads(mp.read_text())
            pmid = mblob.get("provider_model_id")
            if isinstance(pmid, str) and pmid:
                used_extract_model = pmid
        except (OSError, json.JSONDecodeError):
            pass

    project_dir = workspace_root / slug
    lines = [
        "## Active context",
        "",
        f"interface: {interface}",
        "",
        f"The user is in project **{name}** (slug=`{slug}`), chat_id=`{chat_id}`.",
        "",
        f"WORKSPACE_ROOT=`{workspace_root}`",
        f"CURRENT_PROJECT_DIR=`{project_dir}`",
        "",
        "Use the slug above for every tool call that takes a `slug` parameter "
        "unless the user explicitly names a different project. Do NOT call "
        "`list_projects` to discover the current selection — it is given here.",
        "",
        "When you reach for Bash / Glob / Read / Write / Edit / Grep, prefer "
        "absolute paths built from `WORKSPACE_ROOT` / `CURRENT_PROJECT_DIR` "
        "above. Anything inside `WORKSPACE_ROOT` is auto-approved; paths "
        "outside it (or network ops) will ask the user for confirmation.",
        "",
        "Directory layout (current project):",
        "```",
        _WORKSPACE_LAYOUT_TEMPLATE.format(project_dir=project_dir),
        "```",
    ]
    if active_prompt_id or active_model_id or used_extract_model:
        detail = []
        if active_prompt_id:
            detail.append(f"active prompt: `{active_prompt_id}`")
        if active_model_id:
            detail.append(f"active model: `{active_model_id}`")
        if used_extract_model:
            detail.append(f"extract model: `{used_extract_model}`")
        lines.append("")
        lines.append(", ".join(detail) + ".")
    return "\n".join(lines)


def _format_cell_value(v: Any) -> str:
    """Compact stringify for a cell `truth` / `pred` value going into the
    Surface context block. Mirrors the review-surface ``current_value``
    repr: quote strings, json-encode complex shapes, em-dash for null/empty.
    Kept short — the agent only needs the value to anchor the message.
    """
    if v is None:
        return "—"
    if isinstance(v, str):
        if v == "":
            return "—"
        return repr(v)
    if isinstance(v, (int, float, bool)):
        return str(v)
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def _build_eval_cell_surface_block(surface_context: dict[str, Any]) -> str:
    """Render the ``surface: 'eval_cell'`` flavour of the Surface context
    block. Used when the user submits from the EvalMatrix drilldown's
    inline composer — the chat envelope carries the cell's truth / pred /
    status / verdict so the agent can ground questions like "why is the
    prediction X instead of Y?" without round-tripping through a tool call.

    Layout mirrors the review block (header line + identity line + ambient
    facts) so the agent's system prompt looks structurally consistent
    across both surfaces.
    """
    filename = str(surface_context.get("filename") or "")
    field = surface_context.get("field")
    eval_ts = surface_context.get("eval_ts")
    status = surface_context.get("status")
    entity_idx_raw = surface_context.get("entity_idx")
    truth = surface_context.get("truth")
    pred = surface_context.get("pred")
    verdict_reason = surface_context.get("verdict_reason")

    lines = [
        "## Surface context",
        "",
        (
            f"The user is reviewing an eval cell in **{filename}** "
            f"from eval `{eval_ts}`." if eval_ts
            else f"The user is reviewing an eval cell in **{filename}**."
        ),
    ]
    if field:
        lines.append(f"- field: `{field}`")
    if isinstance(entity_idx_raw, int) and entity_idx_raw > 0:
        lines.append(f"- entity_idx: {entity_idx_raw}")
    if status:
        lines.append(f"- status: {status}")
    lines.append(f"- truth: {_format_cell_value(truth)}")
    lines.append(f"- pred:  {_format_cell_value(pred)}")
    if verdict_reason:
        lines.append(f"- verdict_reason: {verdict_reason}")
    lines.append("")
    lines.append(
        "Treat the user's message as feedback about this specific cell "
        "(filename + field + entity_idx) — they are asking about why the "
        "prediction differs from the truth, or how to make the model do "
        "better on this case. Do NOT call `save_reviewed` from this surface "
        "unless the user explicitly requests it — eval cells are read-only "
        "from the agent's POV; corrections belong in description / "
        "global_notes (see review surface for the save flow)."
    )
    return "\n".join(lines)


def _build_review_nudge_block(workspace: Path, slug: str) -> str | None:
    """Render an ambient "tune nudge" line for the review surface, or None.

    Reads the denormalized `corrections_since_tune` counter (bumped by
    `save_reviewed` whenever the human changed fields) plus the reviewed-doc
    count, and — only when BOTH clear the thresholds the autoresearch skill
    already gates on — appends them so the agent can proactively offer
    `/improve`. The decision to offer (and the wording) lives in the skill;
    this block only supplies the two numbers. Best-effort: any read error
    yields None so a missing/garbled project never breaks the turn.
    """
    if slug in (_UNSET_SLUG, _UNBOUND_SLUG):
        return None
    try:
        blob = json.loads(project_json_path(workspace, slug).read_text())
        corrections = int(blob.get("corrections_since_tune") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    # Reviewed count = number of *.json files under reviewed/. Cheap glob count;
    # no need to parse each file.
    try:
        rd = reviewed_dir(workspace, slug)
        reviewed_count = sum(1 for _ in rd.glob("*.json")) if rd.exists() else 0
    except OSError:
        reviewed_count = 0
    out = [
        f"corrections_since_tune: {corrections}",
        f"reviewed_count: {reviewed_count}",
    ]
    # Per-field tally so the agent can name the hot field(s) and offer a
    # *focused* /improve scoped to them (target_fields) rather than a broad
    # all-field tune. Sorted high→low; only the top few matter for the nudge.
    raw_by_field = blob.get("corrections_by_field")
    if isinstance(raw_by_field, dict) and raw_by_field:
        ranked = sorted(
            ((str(k), int(v)) for k, v in raw_by_field.items() if int(v or 0) > 0),
            key=lambda kv: kv[1], reverse=True,
        )[:5]
        if ranked:
            out.append(
                "corrections_by_field: "
                + ", ".join(f"{name}×{n}" for name, n in ranked)
            )
    return "\n".join(out)


def _build_surface_context_block(
    surface_context: dict[str, Any],
    *,
    workspace: Path | None = None,
    slug: str | None = None,
) -> str:
    """Render the "## Surface context" block that gets appended to the system
    prompt for any turn submitted from a surface that snapshots state.

    The signal here is load-bearing: without it the default extractor skill
    routes feedback messages through its intent classifier, which for an
    empty-project state could misread "应该是 住宿账单" as a project rename
    intent and call `rename_project` instead of `save_reviewed`. See plan
    `/Users/qinqiang02/.claude/plans/1-human-snazzy-hare.md` motivating bug.

    Two surfaces today: ``review`` (the review overlay's chat column) and
    ``eval_cell`` (the EvalMatrix drilldown's inline composer). Both share
    the filename + field identity; ``review`` carries ambient navigation
    state (page, page_count, entity_count, active_tab_key, experiment_id)
    so the agent can answer "what am I looking at" without round-tripping
    through ``get_surface_state``; ``eval_cell`` carries the truth/pred
    diff + verdict so the agent can answer "why is this prediction wrong?"
    without re-fetching the eval cell.
    """
    surface = str(surface_context.get("surface") or "review")
    if surface == "eval_cell":
        return _build_eval_cell_surface_block(surface_context)
    if surface != "review":
        # Forward-compat: render an empty block rather than crash if a future
        # frontend sends an unknown surface.
        return f"## Surface context\n\n(unknown surface `{surface}`)"

    filename = str(surface_context.get("filename") or "")
    field = surface_context.get("field")
    current_value = surface_context.get("current_value")
    entity_index = int(surface_context.get("entity_index") or 0)

    lines = [
        "## Surface context",
        "",
        f"The user is reviewing **{filename}** in this project. They selected",
    ]
    if field:
        # Pre-render the value as a short repr — quoting strings, json-ifying
        # objects, leaving primitives plain. Keep it terse: the agent only
        # needs the value to anchor the message; long blobs would just bloat
        # the prompt.
        if current_value is None:
            value_repr = "(empty)"
        elif isinstance(current_value, str):
            value_repr = repr(current_value)
        elif isinstance(current_value, (int, float, bool)):
            value_repr = str(current_value)
        else:
            try:
                value_repr = json.dumps(current_value, ensure_ascii=False)
            except (TypeError, ValueError):
                value_repr = str(current_value)
        lines.append(
            f"field `{field}` (current value: {value_repr}, entity index {entity_index}) before"
        )
        lines.append(
            "sending this message. Treat the message as feedback about this"
        )
        lines.append(
            "(filename, field) unless they explicitly broaden scope."
        )
    else:
        lines.append(
            f"this document but no specific field is selected (entity index {entity_index})."
        )
        lines.append(
            "Treat the message as feedback about this document unless they"
        )
        lines.append(
            "explicitly broaden scope."
        )

    page = surface_context.get("page")
    page_count = surface_context.get("page_count")
    entity_count = surface_context.get("entity_count")
    if isinstance(page, int) and isinstance(page_count, int) and page_count > 0:
        ambient = f"Currently viewing page {page} of {page_count}."
        if isinstance(entity_count, int) and entity_count > 0:
            ambient += (
                f" This document has {entity_count} "
                f"{'entity' if entity_count == 1 else 'entities'} "
                f"(user is on idx {entity_index})."
            )
        lines.append("")
        lines.append(ambient)
    elif isinstance(entity_count, int) and entity_count > 0:
        lines.append("")
        lines.append(
            f"This document has {entity_count} "
            f"{'entity' if entity_count == 1 else 'entities'} "
            f"(user is on idx {entity_index})."
        )

    experiment_id = surface_context.get("experiment_id")
    active_tab_key = surface_context.get("active_tab_key")
    if experiment_id:
        # Active tab is an experiment — values shown are predictions from that
        # experiment, NOT the saved annotation. A value-correction here must
        # NOT call `save_reviewed` against the active annotation without first
        # confirming intent with the user.
        lines.append("")
        lines.append(
            f"User is comparing against experiment `{experiment_id}` — values "
            f"shown are predictions from that experiment, NOT the saved "
            f"annotation. Treat field references in the message as referring "
            f"to the experiment's output unless they clarify otherwise."
        )
    elif active_tab_key and active_tab_key != "active":
        # Defensive: tab key signals an experiment but `experiment_id` was not
        # threaded — render a softer warning rather than crash.
        lines.append("")
        lines.append(
            f"User is on tab `{active_tab_key}` (non-annotation view)."
        )

    # Ambient tune-nudge signals (corrections backlog + reviewed coverage).
    # The skill decides whether to offer /improve based on these two numbers.
    if workspace is not None and slug is not None:
        nudge = _build_review_nudge_block(workspace, slug)
        if nudge:
            lines.append("")
            lines.append(nudge)
    return "\n".join(lines)


class ChatService:
    """Bridge from HTTP/SSE -> Claude Agent SDK -> emerge tools + skill.

    Loads `emerge-extractor` SKILL.md as the system prompt, builds an in-process
    MCP server for the emerge tools, and drives a `ClaudeSDKClient` per turn.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        provider: Provider,
        agent_model: str = "claude-sonnet-4-6",
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.agent_model = agent_model
        self._extractor_skill = load_skill("emerge_extractor")
        self._autoresearch_skill = load_skill("emerge_autoresearch")
        self._publish_skill = load_skill("emerge_publish")
        self._pre_label_runner_skill = load_skill("emerge_pre_label_runner")
        self.system_prompt = self._extractor_skill
        self.job_runner = get_runner(workspace=workspace, provider=provider)
        self.mcp_server = build_emerge_mcp(
            workspace=workspace, provider=provider, job_runner=self.job_runner,
        )

    def _select_skill(self, user_message: str) -> str:
        """Choose which skill text to load based on the slash intent.

        Slash-routed skills are appended after the base extractor skill so
        the agent keeps its core toolbelt knowledge while also picking up
        the specialised playbook for `/improve` or `/publish`.
        """
        stripped = user_message.lstrip()
        if stripped.startswith("/improve"):
            return self._extractor_skill + "\n\n---\n\n" + self._autoresearch_skill
        if stripped.startswith("/publish"):
            return self._extractor_skill + "\n\n---\n\n" + self._publish_skill
        return self._extractor_skill

    def _build_system_prompt(
        self,
        user_message: str,
        *,
        slug: str,
        chat_id: str,
        surface_context: dict[str, Any] | None = None,
        interface: str = "browser",
    ) -> str:
        """Skill text + live Active context block + optional Surface context.

        Active context tells the agent which slug it is operating on for this
        turn — see `_build_active_context` for the rationale.

        `interface` is forwarded into the Active context block so skill prompts
        can gate rendering contracts on `browser` vs `headless`.

        Surface context is appended only when the chat envelope carries a
        `surface_context` (i.e. the user submitted from the review overlay's
        chat column). The block pins the (filename, field, current_value,
        entity_index) snapshot + ambient navigation state so the agent treats
        the message as feedback about that specific cell instead of routing
        through default extractor intent classifiers (which would, e.g.,
        misread "应该是 住宿账单" as a project rename intent on an empty-hero
        turn).
        """
        parts = [
            self._select_skill(user_message),
            "---",
            _build_active_context(self.workspace, slug, chat_id, interface=interface),
        ]
        if surface_context is not None:
            parts.append("---")
            parts.append(
                _build_surface_context_block(
                    surface_context, workspace=self.workspace, slug=slug,
                )
            )
        return "\n\n".join(parts)

    def _build_options(
        self,
        user_message: str,
        *,
        slug: str,
        chat_id: str,
        resume: str | None = None,
        surface_context: dict[str, Any] | None = None,
        interface: str = "browser",
    ) -> ClaudeAgentOptions:
        # Build the permission gate inline so it closes over both the
        # workspace path (for the allow/deny/ask classifier) and the chat_id
        # (for the ask-user round-trip registry). The SSE writer is looked up
        # lazily via ContextVar — at this point the writer hasn't been set yet
        # (that happens further down in `chat_turn`), so we hand the gate a
        # getter rather than the writer itself.
        gate = make_gate(
            self.workspace,
            chat_id=chat_id,
            sse_writer_getter=lambda: current_sse_writer.get(),
        )
        # `pre_label_runner` is a subagent that loops `label_docs` in small
        # chunks for batch pre-label runs. Spawning it via the SDK `Agent`
        # tool gives us native session_id resume, per-batch progress narration,
        # and cancel semantics without a custom job-runner — see
        # docs/superpowers/plans/2026-05-20-pre-label-subagent.md.
        agents: dict[str, AgentDefinition] = {
            "pre_label_runner": AgentDefinition(
                description=(
                    "Use this subagent to pre-label many docs (typically >10 "
                    "files). It batches in chunks of ~8, narrates progress "
                    "between batches via short turn-text lines, and "
                    "soft-fails per doc instead of aborting the run. Pass "
                    "the project slug and the filename list in the prompt; "
                    "the subagent returns a single-line summary to the "
                    "parent on completion. Idempotent: re-invoking after a "
                    "disconnect resumes from filesystem state."
                ),
                prompt=self._pre_label_runner_skill,
                tools=[
                    "mcp__emerge_tools__label_docs",
                    "mcp__emerge_tools__get_labeler_config",
                    "Glob",
                ],
                maxTurns=30,
                effort="low",
            ),
        }
        return ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(
                user_message, slug=slug, chat_id=chat_id,
                surface_context=surface_context, interface=interface,
            ),
            mcp_servers={"emerge_tools": self.mcp_server},
            model=self.agent_model,
            # Lock the SDK CLI's working directory to the workspace root so the
            # CLI's "trusted local dir" heuristic aligns with our gate boundary.
            # Empirically, SDK 0.1.77 under permission_mode="default" skips
            # can_use_tool for Read of files inside the CLI's cwd — without
            # this, the CLI inherits uvicorn's cwd (= backend/) and silently
            # auto-allows Read of backend/.env, bypassing our hard-deny rule.
            cwd=self.workspace.resolve(),
            # Resume the prior SDK conversation so the agent remembers earlier
            # turns. None on the first turn (or after a self-heal retry that only
            # fires when the resumed attempt failed before emitting anything);
            # see INSIGHTS #11.
            resume=resume,
            # Load ONLY emerge's controlled SDK settings file. `setting_sources=["project"]`
            # tells the SDK to read `settings=<path>` as the project-level config —
            # we point it at our checked-in `sdk_settings.json` with strict deny
            # patterns (`.env` / `*.key` / `*.pem` / `~/.ssh/**` / `Bash(printenv*)`
            # etc.). This is BEFORE-callback enforcement: deny matches here don't
            # even reach `can_use_tool`, which is the only reliable way to hard-
            # block `.env` reads (the SDK CLI auto-allows in-cwd files BEFORE
            # consulting the callback under permission_mode="default" — see
            # INSIGHTS #1.5).
            #
            # INSIGHTS #2's foreign-MCP isolation still holds: we never set
            # setting_sources=["user", "local"], and the project setting we load
            # is our own checked-in file (not user-level ~/.claude/settings.json),
            # so third-party MCP servers and SessionStart hooks stay out.
            settings=str(_SDK_SETTINGS_PATH),
            setting_sources=["project"],
            # No static allowlist — the gate classifies every tool call at
            # runtime based on (a) emerge MCP prefix, (b) workspace path
            # range-check, (c) network keyword sniff. Static lists couldn't
            # express the path-dependent rules we need.
            permission_mode="default",
            can_use_tool=gate,
            # Pre-approve `Agent` here so the gate sees it as "explicitly
            # allowed in the SDK manifest", separate from the workspace-safety
            # gate that classifies it as agent bookkeeping. Subagent tool
            # calls re-enter the gate independently — the parent's allowlist
            # does NOT propagate to the subagent.
            #
            # `mcp__emerge_tools__*` wildcard pre-approves every emerge MCP
            # tool, telling the SDK to skip the `can_use_tool` callback for
            # them. The permissions gate still classifies every call (path-
            # range / network-keyword / hard-block) — pre-approval cuts the
            # SDK round-trip, not the gate.
            allowed_tools=["mcp__emerge_tools__*", "Agent"],
            disallowed_tools=_SDK_NEVER_TOOLS,
            # Strict MCP config — SDK uses only `mcp_servers={...}` passed
            # here and ignores any MCP-server entries that might appear in
            # `sdk_settings.json`. Defense in depth against a future settings
            # edit leaking a third-party server into the agent's tool list.
            strict_mcp_config=True,
            agents=agents,
            max_turns=20,
            # Emit raw Anthropic stream events (content_block_delta) alongside
            # the completed-block messages so the chat can render token-level
            # streaming. `_events_from_message` translates StreamEvent →
            # `agent_text_delta` / `agent_thinking`; the completed
            # `AssistantMessage` still arrives and remains the persisted truth.
            include_partial_messages=True,
            # Let Claude decide per-turn whether to engage extended thinking,
            # matching claude.ai's default. Cheap turns stay cheap; harder
            # reasoning (autoresearch planning, schema diffs) gets the budget.
            thinking={"type": "adaptive"},
            # Control-protocol buffer ceiling (SDK default: 1MB). 8MB absorbs
            # the accumulation case — several images + long tool results in a
            # single turn. This is the BACKSTOP, not the fix: the primary
            # defense is `fit_image_for_agent` at the SDK image boundaries
            # (`t_read_doc_image` wrapper + `_load_image_blocks`). Don't read
            # the headroom here as license to inline full-resolution renders.
            max_buffer_size=8 * 1024 * 1024,
        )

    async def chat_turn(
        self,
        *,
        slug: str,
        chat_id: str,
        user_message: str,
        attachments: list[dict[str, Any]] | None = None,
        surface_context: dict[str, Any] | None = None,
        interface: str = "browser",
    ) -> AsyncIterator[str]:
        """Yield SSE-encoded event strings; caller passes them through to the response.

        `slug` is the folder-name handle for the project; per chat-events
        contract the immutable `project_id` (pid) is what jsonl event lines
        and downstream tool payloads use as the audit anchor — never the
        slug, which can be renamed. The empty-hero drop case below mints
        both atomically and surfaces them on the `project_minted` SSE event.
        """
        # ── pre-flight: unbound-chat path — no project, write to `_chats/` ──
        # Phase 1 new path: frontend (post-cutover) submits with `slug='_chats'`
        # for any conversation that hasn't been bound to a project yet. No
        # project is minted; events land in `_chats/<chat_id>.jsonl`. Staged
        # attachments claim into `_chats/<chat_id>/attachments/`. The legacy
        # `p_unset` branch below stays alive until Phase 2 cuts the frontend
        # over to this sentinel.
        minted: dict[str, str] | None = None
        if slug == _UNBOUND_SLUG:
            claimed: list[dict[str, Any]] = []
            for a in (attachments or []):
                tok = a.get("stage_token")
                # Frontend may pin a `kind` per chip from the staging response
                # so the agent skill can route by attachment kind without
                # re-sniffing. Fallback to None — `_load_image_blocks` treats
                # missing kind as legacy `doc` for back-compat.
                kind = a.get("kind") if isinstance(a.get("kind"), str) else None
                if isinstance(tok, str):
                    try:
                        final_name = await claim_staged_to_unbound_chat(
                            self.workspace, tok, chat_id,
                        )
                        entry: dict[str, Any] = {"filename": final_name, "source": "chat"}
                        if kind is not None:
                            entry["kind"] = kind
                        claimed.append(entry)
                    except (StagingClaimError, ValueError):
                        # Stale / unknown token — drop silently rather than
                        # fail the whole turn; the agent sees one fewer doc
                        # but the rest succeed.
                        continue
                else:
                    fname = a.get("filename") or ""
                    if isinstance(fname, str) and fname:
                        entry = {"filename": fname, "source": "chat"}
                        if kind is not None:
                            entry["kind"] = kind
                        claimed.append(entry)
            attachments = claimed

        # ── pre-flight: mint a placeholder project whenever slug is unset ──
        # Empty-hero entry: frontend submits with `slug='p_unset'` either
        # because the user dropped files (each carries a `stage_token`) OR
        # because they just typed text with no files. Both branches mint a
        # placeholder project (`Chat-{ts}`) so chat events never write to
        # `workspace/p_unset/` (which used to leave an unlistable orphan dir
        # behind). When stage tokens exist we claim them into the new
        # project's `chats/<chat_id>/attachments/`; files do NOT enter
        # `docs/` (that requires an explicit user-ack
        # `promote_attachment_to_docs` later).
        if slug == "p_unset":
            placeholder = _placeholder_project_name()
            try:
                _proj = await _create_project(self.workspace, name=placeholder)
                new_slug = _proj["slug"]
                new_pid = _proj["project_id"]
            except Exception as e:  # noqa: BLE001
                err = {
                    "error_code": "project_mint_failed",
                    "error_message_en": str(e),
                }
                yield sse_event("error", err)
                yield sse_event("turn_end", {})
                return
            claimed: list[dict[str, Any]] = []
            for a in (attachments or []):
                tok = a.get("stage_token")
                kind = a.get("kind") if isinstance(a.get("kind"), str) else None
                if isinstance(tok, str):
                    try:
                        final_name = await claim_staged_to_chat(
                            self.workspace, tok, new_slug, chat_id,
                        )
                        entry: dict[str, Any] = {"filename": final_name, "source": "chat"}
                        if kind is not None:
                            entry["kind"] = kind
                        claimed.append(entry)
                    except (StagingClaimError, ValueError):
                        # Stale / unknown token — drop silently rather than
                        # fail the whole turn; the agent sees one fewer doc
                        # but the rest succeed.
                        continue
                else:
                    fname = a.get("filename") or ""
                    if isinstance(fname, str) and fname:
                        entry = {"filename": fname, "source": "chat"}
                        if kind is not None:
                            entry["kind"] = kind
                        claimed.append(entry)
            attachments = claimed
            slug = new_slug
            minted = {
                "project_id": new_slug,
                "slug": new_slug,
                "pid": new_pid,
                "name": placeholder,
            }

        # Anchor on the immutable project_id so post-rename IO lands in the
        # right place. If the agent calls `rename_project` mid-turn,
        # `slug` (a local var) silently goes stale: subsequent `append_event`
        # calls would `mkdir` the OLD path and split chat history into two
        # dirs (we observed this on dogfood — 3 events landed in the
        # renamed dir, 9 in the stranded husk). `_current_slug()` re-asks
        # the pid_index on every read so every IO sees the up-to-date slug.
        # Falls back to the captured `slug` when the pid is unknown (e.g.
        # legacy projects without an index entry); behaviour-preserving.
        anchor_pid: str | None = None
        if minted is not None:
            anchor_pid = minted["pid"]
        else:
            try:
                anchor_pid = json.loads(
                    project_json_path(self.workspace, slug).read_text()
                ).get("project_id")
            except (OSError, json.JSONDecodeError):
                anchor_pid = None
        initial_slug = slug

        def _current_slug() -> str:
            if anchor_pid is None:
                return slug
            return get_index(self.workspace).resolve_pid(anchor_pid) or slug

        # Keep only render-relevant fields on the persisted attachment record —
        # the agent doesn't need anything else, and we deliberately don't carry
        # base64 image bytes into events.jsonl (it would balloon the chat log).
        # `source` distinguishes chat-scoped paste/drop (`"chat"`) from
        # docs-promoted refs (`"docs"`); image-block resolver dispatches on it.
        # `kind` (when present) routes the agent's behaviour by attachment
        # type — `doc` (visual), `schema` (yaml/json schema candidate),
        # `data` (csv), `note` (txt/md). Omitted on legacy entries; the image
        # resolver treats missing kind as `doc` for back-compat.
        persisted_attachments: list[dict[str, Any]] = []
        for a in (attachments or []):
            fn = a.get("filename")
            if not (isinstance(fn, str) and fn):
                continue
            entry: dict[str, Any] = {
                "filename": fn,
                "source": a.get("source") if a.get("source") in ("chat", "docs") else "chat",
            }
            kind = a.get("kind")
            if isinstance(kind, str) and kind:
                entry["kind"] = kind
            persisted_attachments.append(entry)
        user_event: dict[str, Any] = {"type": "user", "text": user_message}
        if persisted_attachments:
            user_event["attachments"] = persisted_attachments
        # Write the meta sidecar BEFORE the first event. For unbound chats the
        # alive gate accepts the meta sidecar as "chat registered" — without
        # this order the very first `append_event` would see neither jsonl
        # nor attachments dir nor meta and drop the user line. For project
        # chats the order is harmless (the gate is on `project.json`).
        ensure_chat_meta(
            self.workspace,
            slug,
            chat_id,
            first_user_message=user_message,
            has_attachments=bool(attachments),
        )
        await append_event(
            self.workspace,
            slug,
            chat_id,
            user_event,
        )
        yield sse_event("user_acknowledged", {"text": user_message})
        if minted is not None:
            # Surface the freshly-minted pid + placeholder name so the frontend
            # can bind selectedId, persist activeChatId under the new pid key,
            # and refresh the projects list. Emitting this *after*
            # `user_acknowledged` keeps the existing front-end "ack first" UX.
            yield sse_event("project_minted", minted)

        prev_sid = read_chat_session_id(self.workspace, slug, chat_id)

        # Leading `/` is intercepted by the Claude Code CLI as a slash command
        # and silently consumed with no model response. A leading space bypasses
        # CLI command dispatch while remaining invisible to the model.
        prompt = f" {user_message}" if user_message.startswith("/") else user_message
        if attachments:
            paths = ", ".join(a.get("filename", "?") for a in attachments)
            prompt = f"{prompt}\n\n[attachments: {paths}]"

        # Inline image attachments as multimodal content blocks so the agent
        # can actually see what the user pasted/dropped. PDFs stay as filename
        # mentions only — those flow through the extractor tools, not vision.
        image_blocks = _load_image_blocks(self.workspace, slug, chat_id, attachments)

        def _make_query_payload() -> str | AsyncIterator[dict[str, Any]]:
            """Fresh query payload per `_run` attempt — AsyncIterables can't be
            replayed, and the self-heal branch retries once with no resume."""
            if not image_blocks:
                return prompt
            content = [{"type": "text", "text": prompt}, *image_blocks]

            async def _iter() -> AsyncIterator[dict[str, Any]]:
                yield {
                    "type": "user",
                    "message": {"role": "user", "content": content},
                    "parent_tool_use_id": None,
                    "session_id": "default",
                }

            return _iter()

        latest_sid: str | None = None
        yielded_any = False

        # Per-turn unified output queue. Both the SDK message loop and
        # out-of-band writers (`_ui_writer`, used by tools that push SSE frames
        # like ui_action / permission_request) feed into this queue; the outer
        # generator is the sole consumer. This means out-of-band events
        # (e.g. a permission_request emitted from a `can_use_tool` callback
        # while the SDK is mid-tool-execution) are forwarded immediately rather
        # than waiting for the next SDK message boundary — that wait would
        # deadlock because the callback itself is what's blocking the next
        # message.
        #
        # The queue is rebound on each `_run` attempt so the self-heal retry
        # (INSIGHTS #11) starts with a clean queue; `_ui_writer` reads the
        # current queue via the mutable holder.
        _SENTINEL: object = object()
        queue_holder: dict[str, asyncio.Queue[tuple[str, dict[str, Any]] | object]] = {
            "q": asyncio.Queue()
        }

        async def _ui_writer(event_type: str, payload: dict[str, Any]) -> None:
            await queue_holder["q"].put((event_type, payload))

        async def _run_into_queue(
            opts: ClaudeAgentOptions,
            out_queue: asyncio.Queue[tuple[str, dict[str, Any]] | object],
        ) -> None:
            nonlocal latest_sid, yielded_any
            redactor = EventRedactor()
            try:
                async with ClaudeSDKClient(options=opts) as client:
                    await client.query(_make_query_payload())
                    async for message in client.receive_response():
                        # `ResultMessage.session_id` is the documented contract
                        # field — every result carries it (success or error).
                        # SystemMessage.data["session_id"] is internal init
                        # event shape, not a stable surface.
                        if isinstance(message, ResultMessage):
                            sid = message.session_id
                            if sid:
                                latest_sid = sid
                        for etype, payload in _events_from_message(message):
                            redactor.observe(etype, payload)
                            # Internal control events (`_block_start` resets the
                            # redactor's per-block delta scrub buffer) are observed
                            # above but never persisted or forwarded.
                            if etype.startswith("_"):
                                continue
                            sse_payload = redactor.scrub_for_sse(etype, payload)
                            # Token-level deltas are ephemeral SSE sugar — never
                            # written to events.jsonl. The completed `agent_text`
                            # block (persisted below) is the authoritative record
                            # reattach/reload rebuild from; the frontend replaces
                            # its streaming buffer with it on arrival.
                            if etype not in _SSE_ONLY_EVENTS:
                                persist_payload = redactor.scrub_for_persist(
                                    etype, payload
                                )
                                await append_event(
                                    self.workspace,
                                    _current_slug(),
                                    chat_id,
                                    {"type": etype, **persist_payload},
                                )
                            yielded_any = True
                            await out_queue.put((etype, sse_payload))
            finally:
                await out_queue.put(_SENTINEL)

        async def _run(opts: ClaudeAgentOptions) -> AsyncIterator[str]:
            # Fresh queue per attempt — protects the self-heal retry from
            # consuming a stale sentinel left behind by the failed first try.
            out_queue: asyncio.Queue[tuple[str, dict[str, Any]] | object] = (
                asyncio.Queue()
            )
            queue_holder["q"] = out_queue
            task = asyncio.create_task(_run_into_queue(opts, out_queue))
            try:
                while True:
                    item = await out_queue.get()
                    if item is _SENTINEL:
                        break
                    etype, payload = item  # type: ignore[misc]
                    yield sse_event(etype, payload)
                # Surface any exception raised inside the SDK task.
                await task
            except BaseException:
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                raise

        # Install the SSE writer for the lifetime of this turn so MCP tools
        # (ui_action_*) can push events. ContextVar isolates concurrent turns
        # — each request has its own writer; tools outside a chat turn (e.g.
        # the public `/v1/extract` fast-path) see `None` and refuse cleanly.
        # ``current_chat_id`` rides alongside so ``ask_user`` can scope its
        # pending-future registry without taking chat_id as an MCP tool param.
        token = current_sse_writer.set(_ui_writer)
        chat_id_token = current_chat_id.set(chat_id)
        try:
            options = self._build_options(
                user_message,
                slug=slug,
                chat_id=chat_id,
                resume=prev_sid,
                surface_context=surface_context,
                interface=interface,
            )
            try:
                async for chunk in _run(options):
                    yield chunk
            except Exception:  # noqa: BLE001
                # Only self-heal when the *resumed* attempt failed before emitting
                # anything user-visible. The dead-transcript case fails fast at
                # client startup (before any yield); a mid-stream failure of a
                # resumed session (dropped connection, provider 5xx) is transient —
                # retrying would re-stream already-delivered SSE events and the
                # frontend would see duplicates, so re-raise and leave the (valid)
                # sidecar alone. See INSIGHTS #11.
                if prev_sid is None or yielded_any:
                    raise
                # A sidecar pointing at a transcript that ~/.claude no longer has
                # must not wedge the chat forever — clear it and retry fresh once.
                write_chat_session_id(self.workspace, slug, chat_id, None)
                latest_sid = None
                yielded_any = False
                options = self._build_options(
                    user_message,
                    slug=slug,
                    chat_id=chat_id,
                    resume=None,
                    surface_context=surface_context,
                    interface=interface,
                )
                async for chunk in _run(options):
                    yield chunk
        except Exception as e:  # noqa: BLE001
            err = {"error_code": "agent_failure", "error_message_en": str(e)}
            await append_event(
                self.workspace,
                _current_slug(),
                chat_id,
                {"type": "error", **err},
            )
            yield sse_event("error", err)
        finally:
            current_sse_writer.reset(token)
            current_chat_id.reset(chat_id_token)
            # Clear any permission requests that were still in flight when
            # the turn ended (e.g. user closed the tab while the agent was
            # waiting on an ask). Idempotent — no-op if everything resolved.
            await cancel_pending(chat_id)
            # Same for ask_user — stranded futures resolve to a cancelled
            # envelope so the tool body unblocks instead of hanging forever.
            await cancel_pending_ask_user(chat_id)
            final_slug = _current_slug()
            if latest_sid and latest_sid != prev_sid:
                write_chat_session_id(self.workspace, final_slug, chat_id, latest_sid)
            # Mid-turn `rename_project` updates the pid_index — let the
            # frontend re-point its selectedSlug (and thus the URL) so the
            # user keeps seeing the conversation under the right address.
            # Skip the no-op case where rename ended up at the starting
            # slug. Also skip when initial_slug==minted placeholder and
            # final differs (project_minted already steered the frontend
            # to the placeholder; project_renamed completes the hop).
            if final_slug != initial_slug:
                yield sse_event(
                    "project_renamed",
                    {"old_slug": initial_slug, "new_slug": final_slug},
                )
            # Snapshot the team workspace into git history so this turn becomes a
            # restorable version. Fire-and-forget (NOT awaited): doing thread work
            # in this generator `finally` deadlocks the turn task's teardown. A
            # `_chats`-only turn stages nothing (gitignored) → no-op commit.
            _schedule_history_commit(
                self.workspace, _history_commit_message(user_message, final_slug)
            )
            yield sse_event("turn_end", {})


# Ephemeral SSE-only events — streamed to the browser for the typewriter
# effect but never written to events.jsonl. See `_run_into_queue`.
_SSE_ONLY_EVENTS = frozenset({"agent_text_delta", "agent_thinking"})


def _events_from_message(message: Any) -> list[tuple[str, dict[str, Any]]]:
    """Translate an SDK message into a list of (event_type, payload) pairs.

    SDK message types (claude-agent-sdk 0.1.77):
      - AssistantMessage(content=list[TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock | ...])
      - UserMessage(content=str | list[blocks], tool_use_result=dict|None)  -- tool result echo
      - SystemMessage(subtype, data)
      - ResultMessage(subtype, ...)  -- terminal sentinel
      - StreamEvent(event=dict)  -- raw Anthropic stream event (token deltas),
        present only when `include_partial_messages=True`
    """
    out: list[tuple[str, dict[str, Any]]] = []

    if isinstance(message, StreamEvent):
        # `event` is the raw Anthropic streaming event. We surface text/thinking
        # deltas for live rendering and a `_block_start` control event so the
        # redactor can reset its per-block secret-scrub buffer. tool-arg
        # (input_json_delta) and signature (signature_delta) streams are dropped
        # — the completed ToolUseBlock already carries the full input.
        ev = message.event
        if not isinstance(ev, dict):
            return out
        stype = ev.get("type")
        parent_id = getattr(message, "parent_tool_use_id", None)
        if stype == "content_block_start":
            block = ev.get("content_block")
            out.append(
                (
                    "_block_start",
                    {
                        "index": ev.get("index"),
                        "block_type": block.get("type")
                        if isinstance(block, dict)
                        else None,
                    },
                )
            )
            return out
        if stype == "content_block_delta":
            delta = ev.get("delta")
            if not isinstance(delta, dict):
                return out
            idx = ev.get("index")
            dtype = delta.get("type")
            if dtype == "text_delta":
                payload: dict[str, Any] = {"index": idx, "text": delta.get("text", "")}
                if parent_id:
                    payload["parent_tool_use_id"] = parent_id
                out.append(("agent_text_delta", payload))
            elif dtype == "thinking_delta":
                out.append(
                    ("agent_thinking", {"index": idx, "text": delta.get("thinking", "")})
                )
        return out

    if isinstance(message, AssistantMessage):
        parent_id = getattr(message, "parent_tool_use_id", None)
        for block in message.content:
            if isinstance(block, TextBlock):
                payload: dict[str, Any] = {"text": block.text}
                if parent_id:
                    payload["parent_tool_use_id"] = parent_id
                out.append(("agent_text", payload))
            elif isinstance(block, ThinkingBlock):
                # Currently dropped — model's internal reasoning, emerge does
                # not consume it.
                continue
            elif isinstance(block, ToolUseBlock):
                payload = {
                    "tool_use_id": block.id,
                    "tool_name": block.name,
                    "tool_input": block.input,
                    "tool_result": None,
                    "ok": True,
                }
                if parent_id:
                    payload["parent_tool_use_id"] = parent_id
                out.append(("tool_call", payload))
            elif isinstance(block, ToolResultBlock):
                # Emit a `tool_result` event paired by tool_use_id. Frontend looks
                # up the matching `tool_call` card and attaches the result.
                # Insight #7: the original drop-the-block design left the
                # frontend blind to tool output. M2C needs job_id surfaced
                # so the JobProgressCard can subscribe to /lab/jobs/{job_id}/events.
                content = block.content
                if isinstance(content, list):
                    text_pieces = [
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    result_text = "".join(text_pieces)
                else:
                    result_text = str(content) if content is not None else ""
                out.append(
                    (
                        "tool_result",
                        {
                            "tool_use_id": block.tool_use_id,
                            "result_text": result_text,
                            "ok": not block.is_error,
                        },
                    )
                )
                continue
            else:
                # ServerToolUseBlock / ServerToolResultBlock / unknown — drop
                # silently rather than dump raw class names into the chat.
                continue
        return out

    if isinstance(message, UserMessage):
        # SDK echoes tool results back as UserMessage(content=list[ToolResultBlock]).
        # Surface them as `tool_result` SSE events so the frontend can pair to the
        # original `tool_call` card via tool_use_id (Insight #7). Plain-string
        # UserMessage echoes the user prompt — already logged at chat_turn entry,
        # skip.
        if isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    content = block.content
                    if isinstance(content, list):
                        text_pieces = [
                            c.get("text", "") for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        ]
                        result_text = "".join(text_pieces)
                    else:
                        result_text = str(content) if content is not None else ""
                    out.append(
                        (
                            "tool_result",
                            {
                                "tool_use_id": block.tool_use_id,
                                "result_text": result_text,
                                "ok": not block.is_error,
                            },
                        )
                    )
        return out

    if isinstance(message, SystemMessage):
        # init / hook_started / hook_response — internal SDK noise, not chat content.
        return out

    if isinstance(message, ResultMessage):
        # Only surface results when the run errored — successful turn already
        # reflected in the closing `turn_end` event.
        if message.is_error:
            out.append(
                (
                    "error",
                    {
                        "error_code": message.subtype or "agent_failure",
                        "error_message_en": (
                            f"{message.subtype} after {message.num_turns} turns"
                        ),
                    },
                )
            )
        return out

    # Unknown message type — drop silently.
    return out
