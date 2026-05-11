from __future__ import annotations

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

from app.chat.log import append_event, read_chat_session_id, write_chat_session_id
from app.chat.redactor import EventRedactor
from app.chat.stream import sse_event
from app.jobs import get_runner
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp


# Strict allowlist: the agent may ONLY call our emerge MCP tools. See the
# defense-in-depth block in `_build_options` for how this prefix is enforced
# (disallowed_tools is load-bearing; can_use_tool is the backstop).
_EMERGE_TOOL_PREFIX = "mcp__emerge_tools__"

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
            # turns. None on the first turn (or after a self-heal); see INSIGHTS #11.
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
        await append_event(
            self.workspace,
            project_id,
            chat_id,
            {"type": "user", "text": user_message},
        )
        yield sse_event("user_acknowledged", {"text": user_message})

        prev_sid = read_chat_session_id(self.workspace, project_id, chat_id)

        # Leading `/` is intercepted by the Claude Code CLI as a slash command
        # and silently consumed with no model response. A leading space bypasses
        # CLI command dispatch while remaining invisible to the model.
        prompt = f" {user_message}" if user_message.startswith("/") else user_message
        if attachments:
            paths = ", ".join(a.get("filename", "?") for a in attachments)
            prompt = f"{prompt}\n\n[attachments: {paths}]"

        latest_sid: str | None = None

        async def _run(opts: ClaudeAgentOptions) -> AsyncIterator[str]:
            nonlocal latest_sid
            redactor = EventRedactor()
            async with ClaudeSDKClient(options=opts) as client:
                await client.query(prompt)
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
                        yield sse_event(etype, sse_payload)

        try:
            options = self._build_options(user_message, resume=prev_sid)
            try:
                async for chunk in _run(options):
                    yield chunk
            except Exception:  # noqa: BLE001
                if prev_sid is None:
                    raise
                # A sidecar pointing at a transcript that ~/.claude no longer has
                # must not wedge the chat forever — clear it and retry fresh once.
                write_chat_session_id(self.workspace, project_id, chat_id, None)
                latest_sid = None
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
