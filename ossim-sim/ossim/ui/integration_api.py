"""Integration endpoint for the dashboard server (same shape as memory_api.py).

  POST /api/integration/run
    {csv, policy, preemptive, q, cs, aging, seed,                       the process workload (as /api/process/run)
     memory: {traces: {PID: "addresses text"}, page_size, frames, policy, hit_ticks, fault_ticks, interval_ticks},
     files:  {requests: [{pid, cmd, args, at_ms}], principals: {PID: user}, users, admins, setup: [{path, mode, owner?, group?}]}}
    -> {events, process, memory, file, blocked, per_process, warnings, limitation}
Problems come back as (422, {"errors": [...]}) and change nothing. See ossim/integration.py for what is and is not modeled.
"""
from __future__ import annotations

from typing import Any

from ossim.integration import run_integration


def handle(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if path != "/api/integration/run":
        return 404, {"errors": ["unknown endpoint"]}
    out, errors = run_integration(body)
    if errors:
        return 422, {"errors": errors}
    return 200, out
