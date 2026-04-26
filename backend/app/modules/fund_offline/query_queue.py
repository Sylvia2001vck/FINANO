from __future__ import annotations

import concurrent.futures
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="offline-db-queue")
_PENDING = 0
_LOCK = threading.Lock()


def run_serial_db_task(
    fn: Callable[..., Any],
    *args: Any,
    task_name: str = "offline_db_task",
    timeout_sec: float = 40.0,
    **kwargs: Any,
) -> Any:
    """
    Serialize SQLite-heavy read tasks through one queue worker.
    Prevents many concurrent readers from amplifying lock contention with writer jobs.
    """
    global _PENDING
    with _LOCK:
        _PENDING += 1
        pending_now = _PENDING
    if pending_now > 3:
        logger.info("offline-db queue backlog=%s task=%s", pending_now, task_name)
    fut = _EXEC.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=max(3.0, float(timeout_sec)))
    finally:
        with _LOCK:
            _PENDING = max(0, _PENDING - 1)
