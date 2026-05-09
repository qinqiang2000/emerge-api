import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client_with_stub_chat(workspace: Path) -> TestClient:
    return TestClient(app)


async def _fake_chat_turn(*args, **kwargs) -> AsyncIterator[str]:
    yield 'event: user_acknowledged\ndata: {"text": "hi"}\n\n'
    yield 'event: agent_text\ndata: {"text": "hello!"}\n\n'
    yield 'event: turn_end\ndata: {}\n\n'


def test_lab_chat_streams_sse(client_with_stub_chat: TestClient) -> None:
    with patch("app.api.routes.chat._get_chat_service") as gcs:
        svc = AsyncMock()
        svc.chat_turn = _fake_chat_turn
        gcs.return_value = svc
        body = {"project_id": "p_x", "chat_id": "c_x", "user_message": "hi"}
        with client_with_stub_chat.stream("POST", "/lab/chat", json=body) as resp:
            assert resp.status_code == 200
            text = b"".join(resp.iter_bytes()).decode()
    assert "event: user_acknowledged" in text
    assert "event: agent_text" in text
    assert "event: turn_end" in text
