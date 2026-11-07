"""Process endpoints shared by the dashboard server and the integration endpoint (moved out of __main__.py in Milestone 3)."""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ossim.core.controller import Controller
from ossim.io.loaders import InputError, load_processes_csv
from ossim.managers.process import ProcessManager

CONFIG_KEYS = ("policy", "preemptive", "q", "cs", "aging", "seed")


def build(body: dict[str, Any]) -> tuple[ProcessManager | None, list[str]]:
    """Validate the request and return a loaded manager, or the list of error messages."""
    text = body.get("csv")
    if not isinstance(text, str):
        return None, ["csv must be text"]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write(text)
        path = f.name
    try:
        rows = load_processes_csv(path)
    except InputError as e:
        return None, [str(e).replace(path, "workload")]
    finally:
        os.unlink(path)
    pm = ProcessManager()
    errors = pm.configure({k: body[k] for k in CONFIG_KEYS if k in body}) + pm.load(rows)
    if errors:
        return None, errors
    ctl = Controller(seed=pm.config["seed"], scenario_id="dashboard")
    ctl.register("process", pm)
    ctl.reset()
    return pm, []


def valid_stop(stop: Any) -> bool:
    return (isinstance(stop, dict) and bool(stop) and set(stop) <= {"max_time", "max_events"}
            and all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in stop.values()))


def result(pm: ProcessManager, events: list) -> dict[str, Any]:
    return {"events": [e.to_dict() for e in events], "snapshot": pm.snapshot(), "metrics": pm.metrics(), "warnings": pm.validate()}
