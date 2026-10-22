"""Run async code from synchronous code, whether or not an event loop is running."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion and return its result.

    ``asyncio.run`` raises if the calling thread already has a running loop (for example
    when a synchronous agent is called from a FastAPI handler). In that case the coroutine
    runs on a fresh loop in a worker thread instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        # copy the context so run records (geospark.runs) see steps made in the coroutine
        return pool.submit(contextvars.copy_context().run, asyncio.run, coro).result()
