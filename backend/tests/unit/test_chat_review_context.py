# backend/tests/unit/test_chat_review_context.py
"""Phase B `review_context` flows from ChatBody into the chat-turn system
prompt as a `## Review focus` block. When absent, the block is omitted (so
chat-mode behavior is byte-identical to pre-Phase-B)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.chat.service import ChatService, _build_review_focus


def _make_service(workspace: Path) -> ChatService:
    return ChatService(
        workspace=workspace,
        provider=AsyncMock(),
        agent_model="claude-sonnet-4-6",
        extract_model="gemini-2.0-flash",
    )


def test_review_focus_block_contains_filename_field_and_value() -> None:
    block = _build_review_focus({
        "filename": "inv-042.pdf",
        "field": "buyer_name",
        "current_value": "ACME Sdn Bhd",
        "entity_index": 0,
    })
    assert "## Review focus" in block
    assert "inv-042.pdf" in block
    assert "buyer_name" in block
    assert "ACME Sdn Bhd" in block
    assert "entity index 0" in block


def test_review_focus_block_handles_missing_field() -> None:
    block = _build_review_focus({
        "filename": "inv-042.pdf",
        "field": None,
        "current_value": None,
        "entity_index": 0,
    })
    assert "## Review focus" in block
    assert "inv-042.pdf" in block
    assert "no specific field is selected" in block
    # No value sentence when field is missing.
    assert "current value" not in block


def test_review_focus_block_handles_empty_current_value() -> None:
    block = _build_review_focus({
        "filename": "inv-042.pdf",
        "field": "buyer_name",
        "current_value": None,
        "entity_index": 0,
    })
    assert "buyer_name" in block
    assert "(empty)" in block


def test_review_focus_block_json_encodes_complex_value() -> None:
    block = _build_review_focus({
        "filename": "inv-042.pdf",
        "field": "line_items",
        "current_value": [{"qty": 1, "desc": "x"}],
        "entity_index": 0,
    })
    assert "qty" in block


def test_build_system_prompt_includes_review_focus_when_present(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "应该是 住宿账单",
        slug="p_unset",
        chat_id="c_test",
        review_context={
            "filename": "0017292f.pdf",
            "field": "receipt_type",
            "current_value": "住宿发票",
            "entity_index": 0,
        },
    )
    assert "## Review focus" in prompt
    assert "0017292f.pdf" in prompt
    assert "receipt_type" in prompt
    assert "住宿发票" in prompt


def test_build_system_prompt_omits_review_focus_when_absent(tmp_path: Path) -> None:
    """Backward-compat: when no review_context is passed, the system prompt
    has no `## Review focus` block — chat-mode behavior is byte-identical to
    pre-Phase-B. (Note: the skill text references "## Review focus" inline
    as documentation; the absence check uses a hallmark sentence the live
    block emits but the docs don't.)"""
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "hello",
        slug="p_unset",
        chat_id="c_test",
    )
    # Hallmark sentence emitted by _build_review_focus but NOT by any skill
    # documentation: "Treat the message as feedback about this".
    assert "Treat the message as feedback about this" not in prompt


def test_build_system_prompt_review_focus_after_active_context(tmp_path: Path) -> None:
    """Order matters: skill text → Active context → Review focus. Verifies
    Review focus appears AFTER the Active context block so its (filename,
    field) signal is the agent's most recent instruction."""
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "hi",
        slug="p_unset",
        chat_id="c_test",
        review_context={
            "filename": "f.pdf",
            "field": "buyer",
            "current_value": "X",
            "entity_index": 0,
        },
    )
    active_idx = prompt.find("## Active context")
    # Find the LIVE-block "## Review focus" header, NOT the skill's documentation
    # reference. The live block is preceded by a section separator "---\n\n".
    focus_idx = prompt.find("---\n\n## Review focus")
    assert active_idx != -1
    assert focus_idx != -1
    assert focus_idx > active_idx
