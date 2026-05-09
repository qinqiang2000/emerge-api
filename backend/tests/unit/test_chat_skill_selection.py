from unittest.mock import AsyncMock

from app.chat.service import ChatService
from app.provider.base import Provider


def _make_svc(tmp_path) -> ChatService:
    return ChatService(
        workspace=tmp_path,
        provider=AsyncMock(spec=Provider),
        agent_model="claude-sonnet-4-6",
        extract_model="claude-sonnet-4-6",
    )


def test_select_system_prompt_publish_loads_publish_skill(tmp_path) -> None:
    svc = _make_svc(tmp_path)
    prompt = svc._select_system_prompt("/publish")
    assert "emerge-extractor" in prompt
    assert "# emerge-publish" in prompt
    assert "---" in prompt


def test_select_system_prompt_publish_with_leading_space(tmp_path) -> None:
    svc = _make_svc(tmp_path)
    prompt = svc._select_system_prompt(" /publish")
    assert "# emerge-publish" in prompt


def test_select_system_prompt_default_does_not_include_publish(tmp_path) -> None:
    svc = _make_svc(tmp_path)
    prompt = svc._select_system_prompt("hello")
    assert "# emerge-publish" not in prompt
    assert "emerge-extractor" in prompt
