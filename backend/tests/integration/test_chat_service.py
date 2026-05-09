from pathlib import Path
from unittest.mock import AsyncMock

from app.chat.service import ChatService


def test_chat_service_constructs(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert svc.workspace == workspace
    assert svc.agent_model == "claude-sonnet-4-6"
    # Skill content present in system prompt
    assert "emerge-extractor" in svc.system_prompt


def _build_options_for(svc: ChatService, msg: str) -> str:
    """Re-construct the system_prompt the service would send for this user
    message. Uses the new _select_system_prompt helper."""
    return svc._select_system_prompt(msg)


def test_improve_loads_autoresearch_skill(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "/improve")
    assert "emerge-extractor" in text
    assert "emerge-autoresearch" in text


def test_non_improve_keeps_extractor_only(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "give me a status update")
    assert "emerge-extractor" in text
    assert "emerge-autoresearch" not in text


def test_leading_space_or_slash_both_match_improve(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve")
    assert "emerge-autoresearch" in _build_options_for(svc, " /improve")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve please")
