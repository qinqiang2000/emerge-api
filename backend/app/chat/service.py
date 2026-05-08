from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.chat.log import append_event
from app.chat.stream import sse_event
from app.provider.base import Provider
from app.skills import load_skill
from app.tools import build_emerge_mcp


# Tool-spec patterns disallowed by the SDK CLI's permission system.
# These map to the `disallowed_tools` option (which takes CLI tool-spec strings,
# not a separate "permissions" dict).
_DISALLOWED_TOOLS = [
    "Read(.env)",
    "Read(.env.*)",
    "Read(/secrets/**)",
    "Read(/*.pem)",
    "Read(/*.key)",
    "Bash(printenv)",
    "Bash(export)",
]


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
        self.system_prompt = load_skill("emerge_extractor")
        self.mcp_server = build_emerge_mcp(workspace=workspace, provider=provider)

    def _build_options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            mcp_servers={"emerge_tools": self.mcp_server},
            model=self.agent_model,
            disallowed_tools=list(_DISALLOWED_TOOLS),
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

        prompt = user_message
        if attachments:
            paths = ", ".join(a.get("filename", "?") for a in attachments)
            prompt = f"{user_message}\n\n[attachments: {paths}]"

        options = self._build_options()
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    for etype, payload in _events_from_message(message):
                        await append_event(
                            self.workspace,
                            project_id,
                            chat_id,
                            {"type": etype, **payload},
                        )
                        yield sse_event(etype, payload)
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
                # Surface thinking as a distinct event; UI can hide if desired.
                out.append(("agent_thinking", {"text": block.thinking}))
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
                out.append(
                    (
                        "tool_call",
                        {
                            "tool_use_id": block.tool_use_id,
                            "tool_name": None,
                            "tool_input": None,
                            "tool_result": block.content,
                            "ok": not bool(block.is_error),
                        },
                    )
                )
            else:
                # ServerToolUseBlock / ServerToolResultBlock / unknown — emit a
                # generic event so the UI can show *something* instead of dropping.
                out.append(
                    (
                        "agent_text",
                        {
                            "text": "",
                            "raw_class": type(block).__name__,
                        },
                    )
                )
        return out

    if isinstance(message, UserMessage):
        # The SDK echoes back tool results as UserMessage with tool_use_result.
        if message.tool_use_result is not None:
            out.append(
                (
                    "tool_call",
                    {
                        "tool_use_id": None,
                        "tool_name": None,
                        "tool_input": None,
                        "tool_result": message.tool_use_result,
                        "ok": True,
                    },
                )
            )
            return out
        # Otherwise it's a re-emit of user text — skip (we already logged it).
        return out

    if isinstance(message, SystemMessage):
        out.append(("system", {"subtype": message.subtype, "data": message.data}))
        return out

    if isinstance(message, ResultMessage):
        out.append(
            (
                "result",
                {
                    "subtype": message.subtype,
                    "is_error": message.is_error,
                    "num_turns": message.num_turns,
                    "stop_reason": message.stop_reason,
                    "duration_ms": message.duration_ms,
                },
            )
        )
        return out

    # Unknown message type — emit a debug event so we don't lose it.
    out.append(("agent_text", {"text": "", "raw_class": type(message).__name__}))
    return out
