import asyncio

import pytest

from app.provider.retry import retry_async, RetryableError


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
