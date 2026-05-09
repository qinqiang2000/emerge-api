"""Verify the agent can NOT execute SDK built-in tools.

If a real LLM call is too expensive for CI, this can be marked
@pytest.mark.real_llm and gated behind an env flag. Default to running it on
the cheap extract model the workspace already configures.
"""
import os
import pytest
from pathlib import Path

from app.chat.service import ChatService
from app.provider import get_provider_for_model


@pytest.mark.asyncio
async def test_agent_glob_call_is_denied(tmp_path: Path) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("real-LLM test; set ANTHROPIC_API_KEY")
    # Seed a project so list_projects has something to return
    from app.tools.projects import create_project
    pid = await create_project(tmp_path, name="sandbox-test")
    svc = ChatService(workspace=tmp_path, provider=get_provider_for_model("claude-sonnet-4-6"))
    events: list[str] = []
    async for chunk in svc.chat_turn(
        project_id=pid, chat_id="c_test",
        user_message="Use the Glob tool to list every PDF you can find on this filesystem.",
    ):
        events.append(chunk)
    transcript = "\n".join(events)
    # The agent may attempt the call; what matters is the result MUST NOT carry filesystem data
    assert "/Users/" not in transcript, (
        "Glob escaped the allowlist and returned filesystem paths"
    )
    assert ".env" not in transcript, "Glob escaped the allowlist"
