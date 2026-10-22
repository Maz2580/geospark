"""Server-wide cap on concurrent heavy work (LLM calls, agents), shared by every interface.

Kept free of web-framework imports so the MCP server (``pip install geospark-ai[mcp]``)
and the REST API (``[api]``) can both use it.

Configuration:
    GEOSPARK_MAX_LLM_CONCURRENCY   concurrent LLM/agent calls (default 2)
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator

_llm_slots: threading.BoundedSemaphore | None = None
_llm_slots_lock = threading.Lock()


def _slots() -> threading.BoundedSemaphore:
    global _llm_slots
    with _llm_slots_lock:
        if _llm_slots is None:
            size = max(1, int(os.getenv("GEOSPARK_MAX_LLM_CONCURRENCY", "2")))
            _llm_slots = threading.BoundedSemaphore(size)
        return _llm_slots


def reset_llm_slots() -> None:
    """Recreate the semaphore (used by tests after changing the env var)."""
    global _llm_slots
    with _llm_slots_lock:
        _llm_slots = None


class ServerBusyError(RuntimeError):
    """All LLM/agent slots are in use."""


@contextlib.contextmanager
def heavy_work_slot() -> Iterator[None]:
    """Hold one shared slot for the duration, or raise ``ServerBusyError`` at once."""
    slots = _slots()
    if not slots.acquire(blocking=False):
        raise ServerBusyError("The server is busy with other heavy requests. Please retry shortly.")
    try:
        yield
    finally:
        slots.release()
