"""Serve the dashboard on localhost only: python -m ossim.ui  (then open http://127.0.0.1:8000).

Static files come from ossim/ui/prototype. A small JSON API under /api/ connects the Process page to the Process Manager:
  GET  /api/status                -> {"engine": true, "detail": str}
  POST /api/process/run           {csv, policy, preemptive, q, cs, aging, seed, stop?}  -> {events, snapshot, metrics}
                                  stop = {"max_time": ticks} and/or {"max_events": count}
  POST /api/process/step          same body plus {"steps": n}                   -> first n events
Inputs are validated before anything runs; problems come back as {"errors": [...]} with status 422 and change nothing.
Times in the response are integer ticks (1 tick = 0.1 ms). Written with Claude; see README Sourced Tools.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ossim.core.controller import Controller
from ossim.io.loaders import InputError, load_processes_csv
from ossim.managers.process import ProcessManager

ROOT = Path(__file__).parent / "prototype"
MAX_BODY = 64 * 1024
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/status":
            return self._send(200, {"engine": True, "detail": "Process Manager loaded"})
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path not in ("/api/process/run", "/api/process/step"):
            return self._send(404, {"errors": ["unknown endpoint"]})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"errors": ["request too large"]})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {"errors": ["request body must be a JSON object"]})
        pm, errors = build(body)
        if errors:
            return self._send(422, {"errors": errors})
        steps = body.get("steps", 1)
        if self.path.endswith("/step") and (isinstance(steps, bool) or not isinstance(steps, int) or steps < 1):
            return self._send(422, {"errors": ["steps must be a whole number of at least 1"]})
        stop = {"max_events": steps} if self.path.endswith("/step") else body.get("stop")
        if stop is not None and not valid_stop(stop):
            return self._send(422, {"errors": ["stop must be {max_time: ticks} and/or {max_events: count}, whole numbers of at least 1"]})
        events = pm.run(stop)
        return self._send(200, result(pm, events))

    def log_message(self, *args):
        pass


def make_server(port: int = 8000) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(Handler, directory=str(ROOT))
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


if __name__ == "__main__":
    with make_server() as srv:
        print("Dashboard at http://127.0.0.1:8000  (Ctrl+C to stop)")
        srv.serve_forever()
