"""File-manager endpoint for the dashboard server (same shape as memory_api.py).

  POST /api/file/run   {script, user?, users?, admins?, setup?, stop?}
                       -> {events, snapshot, metrics, warnings, csv}
`script` is command text, one command per line ('#' comments), read with ossim.io.loaders.load_fs_script.
`user` is who runs the script (default admin); `users` maps user -> group; `admins` lists privileged users.
`setup` = [{"path", "mode", "owner"?, "group"?}] applies a chmod/chown before the script runs.
stop = {"max_time": ticks} and/or {"max_events": count}. Times are integer ticks (1 tick = 0.1 ms).
Problems come back as (422, {"errors": [...]}) and change nothing.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ossim.managers.file import FileManager
from ossim.ui.memory_api import valid_stop

CONFIG_KEYS = ("user", "users", "admins")
MAX_SCRIPT_LINES = 2000


def build(body: dict[str, Any]) -> tuple[FileManager | None, list[str]]:
    text = body.get("script")
    if not isinstance(text, str):
        return None, ["script must be text"]
    if text.count("\n") > MAX_SCRIPT_LINES:
        return None, [f"script is too long (limit {MAX_SCRIPT_LINES} lines)"]
    fm = FileManager()
    errors = fm.configure({k: body[k] for k in CONFIG_KEYS if k in body})
    if errors:
        return None, errors
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        errors = [e.replace(path, "script") for e in fm.load(path)]
    finally:
        os.unlink(path)
    if errors:
        return None, errors
    setup = body.get("setup", [])
    if not isinstance(setup, list):
        return None, ["setup must be a list"]
    for item in setup:
        if not isinstance(item, dict) or "path" not in item or "mode" not in item:
            return None, ["each setup entry needs a path and a mode"]
        errors = fm.set_mode(item["path"], str(item["mode"]), item.get("owner"), item.get("group"))
        if errors:
            return None, errors
    return fm, []


def handle(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if path != "/api/file/run":
        return 404, {"errors": ["unknown endpoint"]}
    stop = body.get("stop")
    if stop is not None and not valid_stop(stop):
        return 422, {"errors": ["stop must be {max_time: ticks} and/or {max_events: count}, whole numbers of at least 1"]}
    fm, errors = build(body)
    if errors:
        return 422, {"errors": errors}
    events = fm.run(stop)
    return 200, {"events": [e.to_dict() for e in events], "snapshot": fm.snapshot(), "metrics": fm.metrics(),
                 "warnings": fm.validate(), "csv": fm.export("csv")}
