# backend/tests/unit/test_chat_review_context.py
"""`surface_context` flows from the turn-start body into the chat-turn system
prompt as a `## Surface context` block. When absent, the block is omitted (so
chat-mode behavior is byte-identical to pre-Phase-B)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from app.chat.service import ChatService, _build_surface_context_block


def _make_service(workspace: Path) -> ChatService:
    return ChatService(
        workspace=workspace,
        provider=AsyncMock(),
        agent_model="claude-sonnet-4-6",
    )


def test_surface_context_block_contains_filename_field_and_value() -> None:
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv-042.pdf",
        "field": "buyer_name",
        "current_value": "ACME Sdn Bhd",
        "entity_index": 0,
    })
    assert "## Surface context" in block
    assert "inv-042.pdf" in block
    assert "buyer_name" in block
    assert "ACME Sdn Bhd" in block
    assert "entity index 0" in block


def test_surface_context_block_handles_missing_field() -> None:
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv-042.pdf",
        "field": None,
        "current_value": None,
        "entity_index": 0,
    })
    assert "## Surface context" in block
    assert "inv-042.pdf" in block
    assert "no specific field is selected" in block
    # No value sentence when field is missing.
    assert "current value" not in block


def test_surface_context_block_handles_empty_current_value() -> None:
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv-042.pdf",
        "field": "buyer_name",
        "current_value": None,
        "entity_index": 0,
    })
    assert "buyer_name" in block
    assert "(empty)" in block


def test_surface_context_block_json_encodes_complex_value() -> None:
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv-042.pdf",
        "field": "line_items",
        "current_value": [{"qty": 1, "desc": "x"}],
        "entity_index": 0,
    })
    assert "qty" in block


def test_surface_context_block_renders_ambient_navigation() -> None:
    """When page/page_count/entity_count are present, the block surfaces them
    so the agent can answer 'what am I looking at' without round-tripping
    through `get_surface_state`."""
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "multi.pdf",
        "field": "buyer_name",
        "current_value": "X",
        "entity_index": 0,
        "page": 3,
        "page_count": 7,
        "entity_count": 2,
    })
    assert "page 3 of 7" in block
    assert "2 entities" in block
    assert "idx 0" in block


def test_surface_context_block_skips_ambient_when_absent() -> None:
    """No page/page_count → no 'Currently viewing' sentence (graceful)."""
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "x.pdf",
        "field": "buyer_name",
        "current_value": "v",
        "entity_index": 0,
    })
    assert "Currently viewing" not in block


def test_surface_context_block_renders_experiment_warning() -> None:
    """When experiment_id is non-null, the block warns the agent the values
    on screen are the experiment's predictions, not the saved annotation."""
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv.pdf",
        "field": "buyer_name",
        "current_value": "ACME",
        "entity_index": 0,
        "active_tab_key": "exp_a1b2",
        "experiment_id": "exp_a1b2",
    })
    assert "experiment `exp_a1b2`" in block
    assert "NOT the saved annotation" in block


def test_surface_context_block_no_experiment_warning_for_active_tab() -> None:
    """active_tab_key='active' + experiment_id=None → no experiment warning."""
    block = _build_surface_context_block({
        "surface": "review",
        "filename": "inv.pdf",
        "field": "buyer_name",
        "current_value": "ACME",
        "entity_index": 0,
        "active_tab_key": "active",
        "experiment_id": None,
    })
    assert "experiment" not in block


def test_build_system_prompt_includes_surface_context_when_present(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "应该是 住宿账单",
        slug="p_unset",
        chat_id="c_test",
        surface_context={
            "surface": "review",
            "filename": "0017292f.pdf",
            "field": "receipt_type",
            "current_value": "住宿发票",
            "entity_index": 0,
        },
    )
    assert "## Surface context" in prompt
    assert "0017292f.pdf" in prompt
    assert "receipt_type" in prompt
    assert "住宿发票" in prompt


def test_build_system_prompt_omits_surface_context_when_absent(tmp_path: Path) -> None:
    """Backward-compat: when no surface_context is passed, the system prompt
    has no `## Surface context` block — chat-mode behavior is byte-identical
    to pre-Phase-B. (Note: the skill text references "## Surface context"
    inline as documentation; the absence check uses a hallmark sentence the
    live block emits but the docs don't.)"""
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "hello",
        slug="p_unset",
        chat_id="c_test",
    )
    # Hallmark sentence emitted by _build_surface_context_block but NOT by any
    # skill documentation: "Treat the message as feedback about this".
    assert "Treat the message as feedback about this" not in prompt


def test_build_system_prompt_surface_context_after_active_context(tmp_path: Path) -> None:
    """Order matters: skill text → Active context → Surface context. Verifies
    Surface context appears AFTER the Active context block so its (filename,
    field) signal is the agent's most recent instruction."""
    svc = _make_service(tmp_path)
    prompt = svc._build_system_prompt(
        "hi",
        slug="p_unset",
        chat_id="c_test",
        surface_context={
            "surface": "review",
            "filename": "f.pdf",
            "field": "buyer",
            "current_value": "X",
            "entity_index": 0,
        },
    )
    active_idx = prompt.find("## Active context")
    # Find the LIVE-block "## Surface context" header, NOT the skill's
    # documentation reference. The live block is preceded by a section
    # separator "---\n\n".
    focus_idx = prompt.find("---\n\n## Surface context")
    assert active_idx != -1
    assert focus_idx != -1
    assert focus_idx > active_idx
