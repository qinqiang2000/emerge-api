from pathlib import Path
from unittest.mock import AsyncMock

from app.chat.service import ChatService


def test_chat_service_constructs(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert svc.workspace == workspace
    assert svc.agent_model == "claude-sonnet-4-6"
    # Skill content present in system prompt
    assert "emerge-extractor" in svc.system_prompt
