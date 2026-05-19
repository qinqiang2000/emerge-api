"""Backend chat session continuity: resume across turns + self-heal + history GET."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from fastapi.testclient import TestClient

from app.chat.log import append_event, read_chat_session_id
from app.chat.service import ChatService
from app.main import app
from app.workspace.paths import chat_meta_path


PID = "p_abc123def456"
CID = "c_abc123def456"


@pytest.fixture
def project_skel(workspace: Path) -> Path:
    """Materialize a minimal `project.json` at PID so chat-log writes (which
    tombstone-gate on project.json existence) actually persist. Real chat
    turns always run inside an already-minted project; tests that hand-craft
    a slug must do the same."""
    pdir = workspace / PID
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(
        json.dumps({"project_id": PID, "slug": PID, "name": "test"}),
        encoding="utf-8",
    )
    return pdir


class _FakeClient:
    """Async-context-manager stand-in for ClaudeSDKClient.

    `query()` is an async no-op; `receive_response()` yields the configured
    messages (or raises `boom` if set).
    """

    instances: list["_FakeClient"] = []

    def __init__(self, *, options: Any) -> None:
        self.options = options
        self.resume = getattr(options, "resume", None)
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def query(self, prompt: str) -> None:  # noqa: ARG002
        return None

    async def receive_response(self):
        for m in _FAKE_MESSAGES:
            yield m


# Module-level so the fake client can reach them; reset per test.
_FAKE_MESSAGES: list[Any] = []


def _make_service(workspace: Path) -> ChatService:
    provider = AsyncMock()
    return ChatService(workspace=workspace, provider=provider, agent_model="claude-sonnet-4-6")


async def _drain(svc: ChatService, **kwargs: Any) -> list[str]:
    return [chunk async for chunk in svc.chat_turn(**kwargs)]


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    _FakeClient.instances.clear()
    _FAKE_MESSAGES.clear()
    yield
    _FakeClient.instances.clear()
    _FAKE_MESSAGES.clear()


async def test_first_turn_persists_session_id(workspace: Path, project_skel: Path) -> None:
    _FAKE_MESSAGES.append(SimpleNamespace(session_id="sess-abc"))
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        await _drain(svc, slug=PID, chat_id=CID, user_message="hi")
    meta = chat_meta_path(workspace, PID, CID)
    assert meta.exists()
    data = json.loads(meta.read_text())
    # chat_turn sets {kind, label, created_at} on turn 1 (ensure_chat_meta) and
    # merges {sdk_session_id} after the run — both halves coexist.
    assert data["sdk_session_id"] == "sess-abc"
    assert {"kind", "label", "created_at"} <= data.keys()
    assert read_chat_session_id(workspace, PID, CID) == "sess-abc"


async def test_second_turn_resumes_prior_session(workspace: Path, project_skel: Path) -> None:
    _FAKE_MESSAGES.append(SimpleNamespace(session_id="sess-abc"))
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        await _drain(svc, slug=PID, chat_id=CID, user_message="first")
        _FakeClient.instances.clear()
        await _drain(svc, slug=PID, chat_id=CID, user_message="second")
    assert len(_FakeClient.instances) == 1
    assert _FakeClient.instances[0].resume == "sess-abc"


async def test_self_heal_on_dead_resume(workspace: Path, project_skel: Path) -> None:
    # Seed a stale sidecar pointing at a transcript that no longer exists.
    from app.chat.log import write_chat_session_id

    write_chat_session_id(workspace, PID, CID, "sess-dead")
    _FAKE_MESSAGES.append(SimpleNamespace(session_id="sess-new"))

    constructed: list[Any] = []

    class _HealClient(_FakeClient):
        def __init__(self, *, options: Any) -> None:
            constructed.append(getattr(options, "resume", None))
            if getattr(options, "resume", None) is not None:
                raise RuntimeError("No conversation found for session sess-dead")
            super().__init__(options=options)

    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _HealClient):
        chunks = await _drain(svc, slug=PID, chat_id=CID, user_message="hi")

    # First construction with resume="sess-dead" raised; retry with resume=None succeeded.
    assert constructed == ["sess-dead", None]
    assert read_chat_session_id(workspace, PID, CID) == "sess-new"
    assert not any("event: error" in c or '"error_code"' in c for c in chunks)


async def test_no_retry_when_no_prior_session(workspace: Path, project_skel: Path) -> None:
    constructed: list[Any] = []

    class _BoomClient(_FakeClient):
        def __init__(self, *, options: Any) -> None:
            constructed.append(getattr(options, "resume", None))
            raise RuntimeError("kaboom")

    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _BoomClient):
        chunks = await _drain(svc, slug=PID, chat_id=CID, user_message="hi")

    # prev_sid was None → no retry, single construction attempt.
    assert constructed == [None]
    joined = "".join(chunks)
    assert "agent_failure" in joined
    # ensure_chat_meta wrote {kind, label, created_at} before the agent ran; the
    # failed turn never produced an sdk_session_id, so that key is absent.
    meta = chat_meta_path(workspace, PID, CID)
    assert meta.exists()
    assert "sdk_session_id" not in json.loads(meta.read_text())


async def test_no_retry_on_mid_stream_failure_of_resumed_turn(workspace: Path, project_skel: Path) -> None:
    """A resumed turn that fails *after* yielding an event must not retry, and the
    (valid) sidecar must be left intact — re-streaming would duplicate events."""
    from app.chat.log import write_chat_session_id

    write_chat_session_id(workspace, PID, CID, "sess-old")

    constructed: list[Any] = []

    class _MidStreamFailClient(_FakeClient):
        def __init__(self, *, options: Any) -> None:
            constructed.append(getattr(options, "resume", None))
            super().__init__(options=options)

        async def receive_response(self):
            # One agent_text-producing message gets through...
            yield AssistantMessage(
                content=[TextBlock(text="partial answer")], model="claude-sonnet-4-6"
            )
            # ...then the transport dies mid-stream.
            raise RuntimeError("connection reset by peer")

    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _MidStreamFailClient):
        chunks = await _drain(svc, slug=PID, chat_id=CID, user_message="hi")

    # No retry: a single construction with resume="sess-old".
    assert constructed == ["sess-old"]
    # Sidecar left alone — the session is fine, the failure was transient.
    assert read_chat_session_id(workspace, PID, CID) == "sess-old"
    joined = "".join(chunks)
    # The already-streamed agent_text plus an agent_failure error event.
    assert "partial answer" in joined
    assert "agent_failure" in joined


def test_chat_history_endpoint_bad_ids(workspace: Path) -> None:
    client = TestClient(app)
    resp = client.get("/lab/chats/bad/also-bad")
    assert resp.status_code == 400


def test_chat_history_endpoint(workspace: Path, project_skel: Path) -> None:
    import asyncio

    async def _seed() -> None:
        await append_event(workspace, PID, CID, {"type": "user", "text": "hi"})
        await append_event(workspace, PID, CID, {"type": "agent_text", "text": "hello!"})

    asyncio.run(_seed())

    client = TestClient(app)
    resp = client.get(f"/lab/chats/{PID}/{CID}")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert {"type": "user", "text": "hi"} in events
    assert {"type": "agent_text", "text": "hello!"} in events


def test_chat_history_endpoint_empty(workspace: Path) -> None:
    client = TestClient(app)
    resp = client.get(f"/lab/chats/{PID}/c_000000000000")
    assert resp.status_code == 200
    assert resp.json() == {"events": []}
