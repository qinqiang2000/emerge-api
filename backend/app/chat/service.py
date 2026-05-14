from __future__ import annotations

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
from app.chat.stream import sse_event
from app.jobs import get_runner
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp
from app.tools.projects import create_project as _create_project
from app.workspace.paths import doc_path
from app.workspace.staging import StagingClaimError, claim_staged


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
    project_id: str,
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build Anthropic image content blocks for any attached images already on
    disk. Silent skip for entries that aren't images, lack `filename`, or whose
    files we can't read — the surrounding `[attachments: ...]` text mention
    still lets the agent reference them by name.

    Post-d_xxx-removal: attachments carry only `{filename}` (the on-disk
    handle); we read the bytes directly via `doc_path`."""
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
        try:
            data = doc_path(workspace, project_id, filename).read_bytes()
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
    into the empty-hero state. The agent is expected to rename via the
    `rename_project` tool once the user's intent (project name) is clear."""
    ts = datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S")
    return f"Untitled-{ts}"


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

    def _select_system_prompt(self, user_message: str) -> str:
        """Choose which skills to load based on the slash intent."""
        stripped = user_message.lstrip()
        if stripped.startswith("/improve"):
            return self._extractor_skill + "\n\n---\n\n" + self._autoresearch_skill
        if stripped.startswith("/publish"):
            return self._extractor_skill + "\n\n---\n\n" + self._publish_skill
        return self._extractor_skill

    def _build_options(
        self, user_message: str, *, resume: str | None = None
    ) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self._select_system_prompt(user_message),
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
        project_id: str,
        chat_id: str,
        user_message: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield SSE-encoded event strings; caller passes them through to the response."""
        # ── pre-flight: claim staged files into a freshly-minted project ──
        # When the user drops files into the empty-hero state, the frontend
        # uploads each file to `/lab/uploads/staging` immediately (so per-file
        # progress/retry is visible while they type) and then submits the chat
        # with `project_id='p_unset'` plus `attachments[i].stage_token`. This
        # block intercepts that pattern: mint a placeholder-named project,
        # claim each staged file into its `docs/` (via the same `upload_doc`
        # pipeline a normal POST /upload would use — sidecar at
        # `docs/.meta/<filename>.json`, slug+dedupe applied), rewrite each
        # attachment to `{filename}` (the only doc handle in the post-d_xxx
        # world), and rebind `project_id` so every subsequent log line + tool
        # call lands under the new pid (no post-hoc migration needed). The
        # agent is expected to rename the project via `rename_project` once
        # the user's intent is clear.
        minted: dict[str, str] | None = None
        if (
            project_id == "p_unset"
            and attachments
            and any(isinstance(a.get("stage_token"), str) for a in attachments)
        ):
            placeholder = _placeholder_project_name()
            try:
                new_pid = await _create_project(self.workspace, name=placeholder)
            except Exception as e:  # noqa: BLE001
                err = {
                    "error_code": "project_mint_failed",
                    "error_message_en": str(e),
                }
                yield sse_event("error", err)
                yield sse_event("turn_end", {})
                return
            claimed: list[dict[str, Any]] = []
            for a in attachments:
                tok = a.get("stage_token")
                if isinstance(tok, str):
                    try:
                        # `claim_staged` returns the post-dedupe on-disk
                        # filename (may differ from the chip name if the
                        # project already had a collision — unlikely on a
                        # freshly-minted project, but handled for free).
                        final_name = await claim_staged(self.workspace, tok, new_pid)
                        claimed.append({"filename": final_name})
                    except (StagingClaimError, ValueError):
                        # Stale / unknown token — drop silently rather than
                        # fail the whole turn; the agent sees one fewer doc
                        # but the rest succeed.
                        continue
                else:
                    # Attachment without a stage_token in the p_unset path
                    # is a legacy/no-op entry — preserve its filename so the
                    # mention text still works, but no claim is performed.
                    fname = a.get("filename") or ""
                    if isinstance(fname, str) and fname:
                        claimed.append({"filename": fname})
            attachments = claimed
            project_id = new_pid
            minted = {"project_id": new_pid, "name": placeholder}

        # Keep only render-relevant fields on the persisted attachment record —
        # the agent doesn't need anything else, and we deliberately don't carry
        # base64 image bytes into events.jsonl (it would balloon the chat log).
        # Filename is now the only doc handle — no separate `doc_id`.
        persisted_attachments = [
            {"filename": a.get("filename")}
            for a in (attachments or [])
            if isinstance(a.get("filename"), str) and a.get("filename")
        ]
        user_event: dict[str, Any] = {"type": "user", "text": user_message}
        if persisted_attachments:
            user_event["attachments"] = persisted_attachments
        await append_event(
            self.workspace,
            project_id,
            chat_id,
            user_event,
        )
        ensure_chat_meta(
            self.workspace,
            project_id,
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

        prev_sid = read_chat_session_id(self.workspace, project_id, chat_id)

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
        image_blocks = _load_image_blocks(self.workspace, project_id, attachments)

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
                            project_id,
                            chat_id,
                            {"type": etype, **persist_payload},
                        )
                        yielded_any = True
                        yield sse_event(etype, sse_payload)

        try:
            options = self._build_options(user_message, resume=prev_sid)
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
                write_chat_session_id(self.workspace, project_id, chat_id, None)
                latest_sid = None
                yielded_any = False
                options = self._build_options(user_message, resume=None)
                async for chunk in _run(options):
                    yield chunk
        except Exception as e:  # noqa: BLE001
            err = {"error_code": "agent_failure", "error_message_en": str(e)}
            await append_event(
                self.workspace,
                project_id,
                chat_id,
                {"type": "error", **err},
            )
            yield sse_event("error", err)
        finally:
            if latest_sid and latest_sid != prev_sid:
                write_chat_session_id(self.workspace, project_id, chat_id, latest_sid)
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
