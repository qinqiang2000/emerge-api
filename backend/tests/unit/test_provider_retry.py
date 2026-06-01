import asyncio

import httpx
import pytest

from app.provider.retry import is_transient, retry_async, RetryableError


async def test_succeeds_on_first_try() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        return 42

    assert await retry_async(f, max_attempts=3, base_delay=0.0) == 42
    assert calls == 1


async def test_retries_on_retryable_error() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableError("temporary")
        return 7

    result = await retry_async(f, max_attempts=5, base_delay=0.0)
    assert result == 7
    assert calls == 3


async def test_gives_up_after_max_attempts() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        raise RetryableError("nope")

    with pytest.raises(RetryableError):
        await retry_async(f, max_attempts=3, base_delay=0.0)
    assert calls == 3


async def test_does_not_retry_non_retryable() -> None:
    calls = 0

    async def f() -> int:
        nonlocal calls
        calls += 1
        raise ValueError("hard")

    with pytest.raises(ValueError):
        await retry_async(f, max_attempts=3, base_delay=0.0)
    assert calls == 1


def test_is_transient_bare_connect_error_empty_message() -> None:
    # The 振兴_testset proxy bug: a flaky GOOGLE_PROXY raises httpx.ConnectError
    # with an EMPTY message. Substring sniffing classified it as permanent and
    # gave up after one shot; type-based classification must catch it.
    exc = httpx.ConnectError("")
    assert str(exc) == ""
    assert is_transient(exc) is True


def test_is_transient_covers_transport_error_subclasses() -> None:
    for exc in (
        httpx.ConnectTimeout("x"),
        httpx.ReadTimeout("x"),
        httpx.PoolTimeout("x"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ReadError("x"),
    ):
        assert is_transient(exc) is True, exc


def test_is_transient_message_hints_for_opaque_sdk_errors() -> None:
    # google-genai wraps a 503 into an opaque Exception carrying the status in
    # its text — not an httpx type, so we still sniff the message.
    assert is_transient(Exception("503 UNAVAILABLE: model overloaded")) is True
    assert is_transient(Exception("429 rate limit exceeded")) is True


def test_is_transient_false_for_permanent_errors() -> None:
    assert is_transient(ValueError("schema must be non-empty")) is False
    assert is_transient(KeyError("entities")) is False
