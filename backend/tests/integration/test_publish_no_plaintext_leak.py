"""Real-LLM smoke: drive a full /publish through ChatService and assert no
plaintext API keys land in the persisted chat jsonl. SSE side may still carry
plaintext (frontend reveal modal).

Skipped by default; opt in with:
    EMERGE_REAL_LLM=1 EMERGE_REAL_ANTHROPIC_KEY=sk-ant-... \\
        cd backend && uv run pytest tests/integration/test_publish_no_plaintext_leak.py -v
"""
import json
import os
import re
from pathlib import Path

import pytest

from app.chat.service import ChatService
from app.provider import get_provider_for_model
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    chats_dir,
    predictions_draft_dir,
    reviewed_dir,
)

_EK_RE = re.compile(r"ek_[A-Za-z0-9_-]{32}")


async def _seed_for_publish(workspace: Path, pid: str) -> None:
    """Seed schema + 3 reviewed/predicted docs so readiness_check passes."""
    await write_schema(
        workspace, pid,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
        ],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]})


@pytest.mark.asyncio
async def test_publish_flow_no_plaintext_in_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.getenv("EMERGE_REAL_LLM") != "1":
        pytest.skip("real-LLM test; set EMERGE_REAL_LLM=1 with a working ANTHROPIC_API_KEY")
    real_key = os.environ.get("EMERGE_REAL_ANTHROPIC_KEY")
    if not real_key:
        pytest.skip("set EMERGE_REAL_ANTHROPIC_KEY for this test (conftest stubs the standard var)")
    monkeypatch.setenv("ANTHROPIC_API_KEY", real_key)

    pid = (await create_project(tmp_path, name="publish-no-leak"))["slug"]
    await _seed_for_publish(tmp_path, pid)

    svc = ChatService(
        workspace=tmp_path,
        provider=get_provider_for_model("claude-sonnet-4-6"),
    )
    sse_chunks: list[str] = []
    async for chunk in svc.chat_turn(
        project_id=pid, chat_id="c_publish", user_message="/publish",
    ):
        sse_chunks.append(chunk)

    sse_blob = "\n".join(sse_chunks)
    # SSE may carry plaintext (one-time modal reveal). Confirm at least one ek_
    # appears so we know the flow actually issued a key — otherwise the next
    # assertion is vacuously true.
    assert _EK_RE.search(sse_blob), (
        "expected SSE stream to carry the plaintext key for the modal reveal"
    )

    # The persisted jsonl side MUST NOT carry plaintext.
    log_path = chats_dir(tmp_path, pid) / "c_publish.jsonl"
    assert log_path.exists(), f"chat log was not written at {log_path}"
    log_text = log_path.read_text()
    matches = _EK_RE.findall(log_text)
    assert not matches, f"plaintext API keys leaked into jsonl: {matches}"
