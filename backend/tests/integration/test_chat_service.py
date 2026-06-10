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
    """Re-construct the skill text the service would route to for this user
    message. Skill routing is `_select_skill`; the full system_prompt (skill
    + Active context) is `_build_system_prompt` — these tests only care
    about the skill-selection half."""
    return svc._select_skill(msg)


def test_improve_loads_autoresearch_skill(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "/improve")
    assert "emerge-extractor" in text
    assert "emerge-autoresearch" in text


def test_non_improve_keeps_extractor_only(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    text = _build_options_for(svc, "give me a status update")
    assert "emerge-extractor" in text
    assert "# emerge-autoresearch (loaded on /improve)" not in text


def test_leading_space_or_slash_both_match_improve(workspace: Path, stub_provider: AsyncMock) -> None:
    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve")
    assert "emerge-autoresearch" in _build_options_for(svc, " /improve")
    assert "emerge-autoresearch" in _build_options_for(svc, "/improve please")


def test_options_raise_sdk_buffer_ceiling(workspace: Path, stub_provider: AsyncMock) -> None:
    """`max_buffer_size` is bumped to 8MB as the accumulation backstop for the
    2026-06-10 SDK image-buffer fix. The primary defense is
    `fit_image_for_agent` at the image boundaries; this only guards the
    several-images-plus-text-in-one-turn pile-up."""
    from app.chat.service import _UNBOUND_SLUG

    svc = ChatService(workspace=workspace, provider=stub_provider, agent_model="claude-sonnet-4-6")
    opts = svc._build_options("hi", slug=_UNBOUND_SLUG, chat_id="c_test123")
    assert opts.max_buffer_size == 8 * 1024 * 1024
