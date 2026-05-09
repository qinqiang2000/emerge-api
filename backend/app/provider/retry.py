import asyncio
import random
from typing import Awaitable, Callable, TypeVar


class RetryableError(Exception):
    """Marker exception. retry_async will catch and retry these."""


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
