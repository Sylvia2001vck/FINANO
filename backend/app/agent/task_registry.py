from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from app.agent.graph import get_mafb_state_after_stream, invoke_mafb, stream_mafb_stages
from app.agent.runtime_trace import reset_event_sink, set_event_sink

_TASKS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def create_mafb_task(initial_state: dict[str, Any], owner_user_id: int) -> str:
    task_id = str(uuid.uuid4())
    rec = {
        "task_id": task_id,
        "owner_user_id": int(owner_user_id),
        "status": "queued",  # queued|running|completed|failed
        "stage_node": None,
        "stage_label": None,
        "error": None,
        "result_state": None,
        "trace_events": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _LOCK:
        _TASKS[task_id] = rec

    th = threading.Thread(target=_run_task_worker, args=(task_id, initial_state), daemon=True)
    th.start()
    return task_id


def get_mafb_task(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        rec = _TASKS.get(task_id)
        return dict(rec) if rec else None


def _patch(task_id: str, **kwargs: Any) -> None:
    with _LOCK:
        rec = _TASKS.get(task_id)
        if not rec:
            return
        rec.update(kwargs)
        rec["updated_at"] = _now()


def _append_event(task_id: str, ev: dict[str, Any]) -> None:
    with _LOCK:
        rec = _TASKS.get(task_id)
        if not rec:
            return
        arr = list(rec.get("trace_events") or [])
        arr.append(ev)
        if len(arr) > 300:
            arr = arr[-300:]
        rec["trace_events"] = arr
        rec["updated_at"] = _now()


def _run_task_worker(task_id: str, initial_state: dict[str, Any]) -> None:
    _patch(task_id, status="running")
    _append_event(task_id, {"kind": "task", "message": "任务已启动，准备执行 MAFB 图…", "ts": _now()})
    token = set_event_sink(lambda ev: _append_event(task_id, ev))
    try:
        for ev in stream_mafb_stages(initial_state, task_id):
            _patch(task_id, stage_node=ev.get("node"), stage_label=ev.get("label"))
            _append_event(
                task_id,
                {"kind": "stage", "message": f"阶段完成：{ev.get('label') or ev.get('node')}", "node": ev.get("node"), "ts": _now()},
            )
        final = get_mafb_state_after_stream(task_id) or invoke_mafb(initial_state)
        _patch(task_id, status="completed", result_state=final)
        _append_event(task_id, {"kind": "task", "message": "任务已完成", "ts": _now()})
    except Exception as e:  # noqa: BLE001
        _patch(task_id, status="failed", error=str(e))
        _append_event(task_id, {"kind": "error", "message": f"任务失败：{e}", "ts": _now()})
    finally:
        reset_event_sink(token)
