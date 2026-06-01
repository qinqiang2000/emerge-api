import asyncio
import random
from typing import Awaitable, Callable, TypeVar


class RetryableError(Exception):
    """Marker exception. retry_async will catch and retry these."""


# Substrings that mark an opaque SDK/API exception as a retryable
# availability/gateway failure. Kept for the cases that arrive as a bare
# `Exception` carrying the status in its text (google-genai wraps 429/503
# into APIError, anthropic/codex surface the status in our own message).
_TRANSIENT_HINTS = (
    "rate", "429", "500", "502", "503", "504",
    "timeout", "timed out", "disconnect", "remoteprotocol",
    "incomplete", "connection reset", "connection refused",
    "temporarily unavailable", "overloaded",
)


def is_transient(exc: BaseException) -> bool:
    """True when `exc` is a retryable transport / upstream-availability failure.

    Classify by EXCEPTION TYPE first: every `httpx.TransportError` subclass
    (ConnectError, ConnectTimeout, ReadTimeout, WriteTimeout, PoolTimeout,
    RemoteProtocolError, ReadError, ...) is a network-layer blip worth a
    retry. This is the robust path — a bare `httpx.ConnectError` from a flaky
    proxy carries an EMPTY message, so the old substring-only check classified
    it as permanent and gave up after one shot (the 振兴_testset proxy bug).

    Fall back to substring sniffing for opaque SDK exceptions that aren't httpx
    types but still encode a gateway status in their text.
    """
    try:
        import httpx

        if isinstance(exc, httpx.TransportError):
            return True
    except ImportError:  # httpx always present in prod; guard test envs
        pass
    msg = str(exc).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except RetryableError as e:
            last_exc = e
            if attempt == max_attempts:
                raise
            sleep_for = min(max_delay, base_delay * (2 ** (attempt - 1)))
            sleep_for *= 0.75 + random.random() * 0.5  # jitter ±25%
            await asyncio.sleep(sleep_for)
    # unreachable
    raise last_exc  # type: ignore[misc]
