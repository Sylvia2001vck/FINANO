from __future__ import annotations

import contextvars
import time
from typing import Any, Callable

_SINK: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    "mafb_runtime_event_sink",
    default=None,
)


def set_event_sink(sink: Callable[[dict[str, Any]], None] | None):
    return _SINK.set(sink)


def reset_event_sink(token) -> None:
    _SINK.reset(token)


def emit_agent_event(kind: str, message: str, **extra: Any) -> None:
    sink = _SINK.get()
    if sink is None:
        return
    payload = {
        "ts": time.time(),
        "kind": kind,
        "message": message,
        **extra,
    }
    try:
        sink(payload)
    except Exception:
        # 观测链路不得影响主流程
        return
