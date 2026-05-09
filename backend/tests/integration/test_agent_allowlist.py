"""Verify the agent can NOT execute SDK built-in tools.

This test requires a real Anthropic API call and must be explicitly opted in:

    EMERGE_REAL_LLM=1 EMERGE_REAL_ANTHROPIC_KEY=sk-ant-... uv run pytest \\
        tests/integration/test_agent_allowlist.py -v

Why two env vars?
- conftest.py has an autouse `env_isolation` fixture that stubs ANTHROPIC_API_KEY
  to "anthropic-test-not-used" for every test.  The stub would cause an auth
  failure that superficially "passes" the assertion without exercising the
  allowlist at all.
- EMERGE_REAL_ANTHROPIC_KEY carries the real key past the stub.
- EMERGE_REAL_LLM=1 is the explicit opt-in gate so CI never runs this
  accidentally.
"""
import os
import pytest
from pathlib import Path

from app.chat.service import ChatService
from app.provider import get_provider_for_model


@pytest.mark.asyncio
async def test_agent_glob_call_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("EMERGE_REAL_LLM") != "1":
        pytest.skip("real-LLM test; set EMERGE_REAL_LLM=1 with a working ANTHROPIC_API_KEY")
    real_key = os.environ.get("EMERGE_REAL_ANTHROPIC_KEY")
    if not real_key:
        pytest.skip("set EMERGE_REAL_ANTHROPIC_KEY for this test (conftest stubs the standard var)")
    # Override the conftest env_isolation stub so we actually reach the Anthropic API.
    monkeypatch.setenv("ANTHROPIC_API_KEY", real_key)

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
