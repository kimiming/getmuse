"""Small retry helper with cancellation and typed logging callbacks."""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

from muse_auto.core.errors import Stopped
from muse_auto.core.stop import StopToken

T = TypeVar("T")


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    delay: float = 0.4,
    backoff: float = 2.0,
    stop: StopToken | None = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_error: Callable[[int, BaseException], None] | None = None,
    jitter: float = 0.0,
) -> T:
    """Run ``func`` up to ``attempts`` times.

    ``Stopped`` is never retried. The final exception is re-raised unchanged so
    the caller keeps the original context.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if stop is not None:
            stop.check()
        try:
            return func()
        except Stopped:
            raise
        except exceptions as exc:  # noqa: PERF203 - retry is the point
            last = exc
            if on_error is not None:
                on_error(attempt, exc)
            if attempt >= attempts:
                break
            pause = delay * (backoff ** (attempt - 1))
            if jitter:
                pause += random.uniform(0, jitter)
            if stop is not None:
                stop.sleep(pause)
            else:
                time.sleep(pause)
    assert last is not None
    raise last
