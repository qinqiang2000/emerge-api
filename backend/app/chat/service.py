from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
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
from app.chat.redactor import EventRedactor
from app.chat.sse_context import current_sse_writer
from app.chat.stream import sse_event
from app.jobs import get_runner
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp
from app.tools.projects import create_project as _create_project
from app.workspace.paths import chat_attachment_path, doc_path, project_json_path
from app.workspace.pid_index import get_index
from app.workspace.staging import StagingClaimError, claim_staged_to_chat


# Strict allowlist: the agent may ONLY call our emerge MCP tools. See the
# defense-in-depth block in `_build_options` for how this prefix is enforced
# (disallowed_tools is load-bearing; can_use_tool is the backstop).
_EMERGE_TOOL_PREFIX = "mcp__emerge_tools__"

# Filename suffix → Anthropic image media type. PDFs deliberately excluded:
# the agent reaches PDF docs via tools (`extract_one` / `extract_batch`), not
# vision inlining, so we don't inflate the user-message token cost.
_IMAGE_MEDIA_TYPE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


def _load_image_blocks(
    workspace: Path,
    slug: str,
    chat_id: str,
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build Anthropic image content blocks for any attached images already on
    disk. Silent skip for entries that aren't images, lack `filename`, or whose
    files we can't read — the surrounding `[attachments: ...]` text mention
    still lets the agent reference them by name.

    Dispatches on `source`:
      - `chat` (default for paste/drop) → reads via `chat_attachment_path`
      - `docs` (post-promote refs) → reads via `doc_path`
    """
    if not attachments:
        return []
    blocks: list[dict[str, Any]] = []
    for a in attachments:
        filename = a.get("filename", "")
        if not (isinstance(filename, str) and filename):
            continue
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        media_type = _IMAGE_MEDIA_TYPE.get(ext)
        if not media_type:
            continue
        source = a.get("source", "chat")
        if source == "docs":
            path = doc_path(workspace, slug, filename)
        else:
            path = chat_attachment_path(workspace, slug, chat_id, filename)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        b64 = base64.standard_b64encode(data).decode("ascii")
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        )
    return blocks

# All Claude Agent SDK built-in tool names. permission_mode='default' does NOT
# consult the can_use_tool callback for these — only an explicit disallowed_tools
# entry actually prevents invocation. Empirically verified during M5 dogfood
# (chat c_1c32d12a2747 had Glob calls returning workspace paths despite the
# can_use_tool callback being installed).
_SDK_BUILT_IN_TOOLS = [
    "Bash", "BashOutput", "KillBash",
    "Edit", "MultiEdit", "Read", "Write", "NotebookEdit",
    "Grep", "Glob",
    "WebFetch", "WebSearch",
    "Task", "TodoWrite", "ExitPlanMode",
    "ToolSearch",
    # emerge loads its skills as system_prompt text, NOT via the SDK Skill
    # mechanism — so the SDK has no "emerge-publish" / "emerge-extractor" /
    # "emerge-autoresearch" registered. When the agent reached for the
    # built-in `Skill` tool on /publish, the SDK returned
    # `<tool_use_error>Unknown skill: emerge-publish</tool_use_error>` and
    # the UI rendered a stray `▸ Skill ERR` chip. Deny it explicitly so the
    # agent never sees `Skill` as an option in the first place.
    "Skill",
]


def _placeholder_project_name() -> str:
    """Auto-name for projects minted by chat_turn when the user drops files
    into the empty-hero state. The `Chat-` prefix signals "this is a
    conversation, not a curated project" — paste/drop files land in
    `chats/<chat_id>/attachments/`, never auto-promoted into `docs/`. The
    agent is expected to rename via `rename_project` once user intent is
    clear (and to call `promote_attachment_to_docs` only on explicit ack)."""
    ts = datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S")
    return f"Chat-{ts}"


# Sentinel for the empty-hero composer (also defined in routes/chat.py).
# Kept here so this module can identify "no project yet" without importing
# the route layer.
_UNSET_SLUG = "p_unset"


def _build_active_context(workspace: Path, slug: str, chat_id: str) -> str:
    """Render the "Active context" block that gets spliced into the system
    prompt every turn.

    The agent otherwise has no idea which project the user is *looking at*
    in the UI — it would have to call `list_projects` and guess. This block
    pins the URL/page state (slug + active prompt + active model) directly
    into the system prompt so the agent calls tools with the right `slug`
    on the first try.

    Reading `project.json` is best-effort: a freshly-minted project may not
    yet have the file flushed, and a renamed slug between turns may briefly
    point at a stale path. In either case we fall back to a minimal block
    containing just the slug — better than nothing, and the agent can still
    operate.
    """
    if slug == _UNSET_SLUG:
        return (
            "## Active context\n\n"
            "The user has NOT selected a project yet (empty-hero state). "
            "No project-scoped tools work until a project is created — call "
            "`create_project` first, then use its returned slug for "
            "subsequent tool calls. Do NOT call `list_projects` to look for "
            "an active project; there isn't one."
        )

    name = slug
    active_prompt_id: str | None = None
    active_model_id: str | None = None
    extract_model: str | None = None
    try:
        blob = json.loads(project_json_path(workspace, slug).read_text())
        name = str(blob.get("name") or slug)
        active_prompt_id = blob.get("active_prompt_id")
        active_model_id = blob.get("active_model_id")
        extract_model = blob.get("extract_model")
    except (OSError, json.JSONDecodeError):
        pass

    lines = [
        "## Active context",
        "",
        f"The user is in project **{name}** (slug=`{slug}`), chat_id=`{chat_id}`.",
        "",
        "Use this slug for every tool call that takes a `slug` parameter "
        "unless the user explicitly names a different project. Do NOT call "
        "`list_projects` to discover the current selection — it is given here.",
    ]
    if active_prompt_id or active_model_id or extract_model:
        detail = []
        if active_prompt_id:
            detail.append(f"active prompt: `{active_prompt_id}`")
        if active_model_id:
            detail.append(f"active model: `{active_model_id}`")
        if extract_model:
            detail.append(f"extract model: `{extract_model}`")
        lines.append("")
        lines.append(", ".join(detail) + ".")
    return "\n".join(lines)


def _build_surface_context_block(surface_context: dict[str, Any]) -> str:
    """Render the "## Surface context" block that gets appended to the system
    prompt for any turn submitted from a surface that snapshots state
    (currently only review).

    The signal here is load-bearing: without it the default extractor skill
    routes feedback messages through its intent classifier, which for an
    empty-project state could misread "应该是 住宿账单" as a project rename
    intent and call `rename_project` instead of `save_reviewed`. See plan
    `/Users/qinqiang02/.claude/plans/1-human-snazzy-hare.md` motivating bug.

    Phase 1 only handles `surface == 'review'`. Ambient navigation state
    (page, page_count, entity_count, active_tab_key, experiment_id) is
    appended whenever the frontend has it — those let the agent answer
    "what am I looking at" without round-tripping through `get_surface_state`.
    """
    surface = str(surface_context.get("surface") or "review")
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
    return "\n".join(lines)


async def _emerge_only_permission(
    tool_name: str,
    _input: dict[str, Any],
    _ctx: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """Hard allowlist gate. Only emerge MCP tools may run."""
    if tool_name.startswith(_EMERGE_TOOL_PREFIX):
        return PermissionResultAllow()
    return PermissionResultDeny(
        message=(
            f"Tool {tool_name!r} is not available. "
            f"emerge restricts the agent to {_EMERGE_TOOL_PREFIX}* tools only."
        ),
        interrupt=False,
    )


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
        extract_model: str = "gemini-2.0-flash",
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.agent_model = agent_model
        self._extractor_skill = load_skill("emerge_extractor")
        self._autoresearch_skill = load_skill("emerge_autoresearch")
        self._publish_skill = load_skill("emerge_publish")
        self.system_prompt = self._extractor_skill
        self.job_runner = get_runner(
            workspace=workspace, provider=provider, model_id=extract_model,
        )
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
    ) -> str:
        """Skill text + live Active context block + optional Surface context.

        Active context tells the agent which slug it is operating on for this
        turn — see `_build_active_context` for the rationale.

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
            _build_active_context(self.workspace, slug, chat_id),
        ]
        if surface_context is not None:
            parts.append("---")
            parts.append(_build_surface_context_block(surface_context))
        return "\n\n".join(parts)

    def _build_options(
        self,
        user_message: str,
        *,
        slug: str,
        chat_id: str,
        resume: str | None = None,
        surface_context: dict[str, Any] | None = None,
    ) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(
                user_message, slug=slug, chat_id=chat_id, surface_context=surface_context,
            ),
            mcp_servers={"emerge_tools": self.mcp_server},
            model=self.agent_model,
            # Resume the prior SDK conversation so the agent remembers earlier
            # turns. None on the first turn (or after a self-heal retry that only
            # fires when the resumed attempt failed before emitting anything);
            # see INSIGHTS #11.
            resume=resume,
            # Do NOT inherit user/project/local Claude Code settings — that's how
            # foreign MCP servers (chrome-devtools, excalidraw, etc.) and
            # SessionStart hooks were leaking into the chat stream.
            setting_sources=[],
            # Defense in depth:
            #   1. disallowed_tools — load-bearing. Empirically (M5 dogfood) the
            #      can_use_tool callback below is NOT consulted for SDK built-ins
            #      under permission_mode='default'. Explicit denial is the only
            #      reliable knob.
            #   2. can_use_tool — backstop for any name that isn't an emerge MCP
            #      tool and isn't in disallowed_tools either.
            #   3. allowed_tools — advisory for the SDK's own bookkeeping.
            permission_mode="default",
            can_use_tool=_emerge_only_permission,
            allowed_tools=[f"{_EMERGE_TOOL_PREFIX}*"],
            disallowed_tools=_SDK_BUILT_IN_TOOLS,
            max_turns=20,
        )

    async def chat_turn(
        self,
        *,
        slug: str,
        chat_id: str,
        user_message: str,
        attachments: list[dict[str, Any]] | None = None,
        surface_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield SSE-encoded event strings; caller passes them through to the response.

        `slug` is the folder-name handle for the project; per chat-events
        contract the immutable `project_id` (pid) is what jsonl event lines
        and downstream tool payloads use as the audit anchor — never the
        slug, which can be renamed. The empty-hero drop case below mints
        both atomically and surfaces them on the `project_minted` SSE event.
        """
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
        minted: dict[str, str] | None = None
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
                if isinstance(tok, str):
                    try:
                        final_name = await claim_staged_to_chat(
                            self.workspace, tok, new_slug, chat_id,
                        )
                        claimed.append({"filename": final_name, "source": "chat"})
                    except (StagingClaimError, ValueError):
                        # Stale / unknown token — drop silently rather than
                        # fail the whole turn; the agent sees one fewer doc
                        # but the rest succeed.
                        continue
                else:
                    fname = a.get("filename") or ""
                    if isinstance(fname, str) and fname:
                        claimed.append({"filename": fname, "source": "chat"})
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
        persisted_attachments = [
            {
                "filename": a.get("filename"),
                "source": a.get("source") if a.get("source") in ("chat", "docs") else "chat",
            }
            for a in (attachments or [])
            if isinstance(a.get("filename"), str) and a.get("filename")
        ]
        user_event: dict[str, Any] = {"type": "user", "text": user_message}
        if persisted_attachments:
            user_event["attachments"] = persisted_attachments
        await append_event(
            self.workspace,
            slug,
            chat_id,
            user_event,
        )
        ensure_chat_meta(
            self.workspace,
            slug,
            chat_id,
            first_user_message=user_message,
            has_attachments=bool(attachments),
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

        # Out-of-band event queue for tools that want to push SSE frames
        # (ui_action). The tool body runs synchronously inside the SDK message
        # loop, drops a payload into this queue, and the loop drains it on the
        # next iteration. `current_sse_writer` is set below for the lifetime of
        # the turn so tools can `current_sse_writer.get()` to find the writer.
        ui_action_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def _ui_writer(event_type: str, payload: dict[str, Any]) -> None:
            await ui_action_queue.put((event_type, payload))

        def _drain_queue() -> list[tuple[str, dict[str, Any]]]:
            drained: list[tuple[str, dict[str, Any]]] = []
            while True:
                try:
                    drained.append(ui_action_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return drained

        async def _run(opts: ClaudeAgentOptions) -> AsyncIterator[str]:
            nonlocal latest_sid, yielded_any
            redactor = EventRedactor()
            async with ClaudeSDKClient(options=opts) as client:
                await client.query(_make_query_payload())
                async for message in client.receive_response():
                    sid = getattr(message, "session_id", None)
                    if isinstance(message, SystemMessage):
                        sid = message.data.get("session_id") or sid
                    if sid:
                        latest_sid = sid
                    for etype, payload in _events_from_message(message):
                        redactor.observe(etype, payload)
                        persist_payload = redactor.scrub_for_persist(etype, payload)
                        sse_payload = redactor.scrub_for_sse(etype, payload)
                        await append_event(
                            self.workspace,
                            _current_slug(),
                            chat_id,
                            {"type": etype, **persist_payload},
                        )
                        yielded_any = True
                        yield sse_event(etype, sse_payload)
                    # Drain any ui_action events that landed during this
                    # message — tool bodies run inline with the message loop,
                    # so anything they pushed is now ready to forward.
                    for etype, payload in _drain_queue():
                        yielded_any = True
                        yield sse_event(etype, payload)

        # Install the SSE writer for the lifetime of this turn so MCP tools
        # (ui_action_*) can push events. ContextVar isolates concurrent turns
        # — each request has its own writer; tools outside a chat turn (e.g.
        # the public `/v1/extract` fast-path) see `None` and refuse cleanly.
        token = current_sse_writer.set(_ui_writer)
        try:
            options = self._build_options(
                user_message,
                slug=slug,
                chat_id=chat_id,
                resume=prev_sid,
                surface_context=surface_context,
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
            # Flush any ui_action events that arrived in the small window
            # between the final SDK message and the end of the loop.
            for etype, payload in _drain_queue():
                yield sse_event(etype, payload)
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
            yield sse_event("turn_end", {})


def _events_from_message(message: Any) -> list[tuple[str, dict[str, Any]]]:
    """Translate an SDK message into a list of (event_type, payload) pairs.

    SDK message types (claude-agent-sdk 0.1.77):
      - AssistantMessage(content=list[TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock | ...])
      - UserMessage(content=str | list[blocks], tool_use_result=dict|None)  -- tool result echo
      - SystemMessage(subtype, data)
      - ResultMessage(subtype, ...)  -- terminal sentinel
    """
    out: list[tuple[str, dict[str, Any]]] = []

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                out.append(("agent_text", {"text": block.text}))
            elif isinstance(block, ThinkingBlock):
                # Drop — model's internal reasoning. Re-enable as `agent_thinking`
                # behind a UI toggle if we ever want a "show thinking" mode.
                continue
            elif isinstance(block, ToolUseBlock):
                out.append(
                    (
                        "tool_call",
                        {
                            "tool_use_id": block.id,
                            "tool_name": block.name,
                            "tool_input": block.input,
                            "tool_result": None,
                            "ok": True,
                        },
                    )
                )
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
