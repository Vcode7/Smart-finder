"""
app/search/activity.py
~~~~~~~~~~~~~~~~~~~~~~
Searches take priority over background indexing. A search marks itself active; the
indexing pipeline calls `yield_to_searches()` between model batches and waits (briefly)
while any search is running, so queries don't queue behind a batch of keyframes.
"""
from __future__ import annotations

import contextlib
import threading
import time
from typing import Iterator

_active = 0
_lock = threading.Lock()
_idle = threading.Event()
_idle.set()


@contextlib.contextmanager
def search_activity() -> Iterator[None]:
    global _active
    with _lock:
        _active += 1
        _idle.clear()
    try:
        yield
    finally:
        with _lock:
            _active -= 1
            if _active <= 0:
                _active = 0
                _idle.set()


def searches_active() -> bool:
    return not _idle.is_set()


def yield_to_searches(max_wait: float = 3.0) -> None:
    """Called by indexing between batches: pause while searches run (bounded)."""
    if _idle.is_set():
        return
    deadline = time.time() + max_wait
    _idle.wait(timeout=max(0.0, deadline - time.time()))
