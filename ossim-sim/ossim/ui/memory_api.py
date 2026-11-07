"""Memory endpoints for the dashboard server (mirrors /api/process/run in ossim/ui/__main__.py).

  POST /api/memory/run      {trace, policy, page_size, frames, hit_ticks, fault_ticks, pid, seed, stop?}
                            -> {events, snapshot, metrics, warnings}
  POST /api/memory/compare  same body (policy ignored) -> {runs: {fifo: <as above>, lru: <as above>}}
                            FIFO and LRU run on the identical trace.
`trace` is trace text: one address per line (hex 0x.. or decimal), '#' comments. Read with
ossim.io.loaders.load_trace; every reference belongs to `pid` (default P1).
stop = {"max_time": ticks} and/or {"max_events": count}. Times are integer ticks (1 tick = 0.1 ms).
Problems come back as (422, {"errors": [...]}) and change nothing.

"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ossim.managers.memory import POLICIES, MemoryManager

CONFIG_KEYS = ("policy", "page_size", "frames", "hit_ticks", "fault_ticks", "pid", "seed")


def build(body: dict[str, Any], policy: str | None = None) -> tuple[MemoryManager | None, list[str]]:
    text = body.get("trace")
    if not isinstance(text, str):
        return None, ["trace must be text"]
    config = {k: body[k] for k in CONFIG_KEYS if k in body}
    if policy:
        config["policy"] = policy
    mm = MemoryManager()
    errors = mm.configure(config)
    if errors:
        return None, errors
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        errors = [e.replace(path, "trace") for e in mm.load(path)]   # same loader as the file path route
    finally:
        os.unlink(path)
    return (None, errors) if errors else (mm, [])


def valid_stop(stop: Any) -> bool:
    return (isinstance(stop, dict) and bool(stop) and set(stop) <= {"max_time", "max_events"}
            and all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in stop.values()))


def result(mm: MemoryManager, events: list) -> dict[str, Any]:
    return {"events": [e.to_dict() for e in events], "snapshot": mm.snapshot(),
            "metrics": mm.metrics(), "warnings": mm.validate()}


def handle(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Returns (http_status, json_payload)."""
    if path not in ("/api/memory/run", "/api/memory/compare"):
        return 404, {"errors": ["unknown endpoint"]}
    stop = body.get("stop")
    if stop is not None and not valid_stop(stop):
        return 422, {"errors": ["stop must be {max_time: ticks} and/or {max_events: count}, whole numbers of at least 1"]}
    if path.endswith("/run"):
        mm, errors = build(body)
        if errors:
            return 422, {"errors": errors}
        return 200, result(mm, mm.run(stop))
    runs = {}
    for policy in POLICIES:
        mm, errors = build(body, policy)
        if errors:
            return 422, {"errors": errors}
        runs[policy] = result(mm, mm.run(stop))
    return 200, {"runs": runs}