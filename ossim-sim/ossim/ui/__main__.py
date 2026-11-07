"""Serve the dashboard on localhost only: python -m ossim.ui  (then open http://127.0.0.1:8000).

Static files come from ossim/ui/prototype. A small JSON API under /api/ connects the dashboard pages to the managers:
  GET  /api/status                -> {"engine": true, "detail": str}
  POST /api/process/run           {csv, policy, preemptive, q, cs, aging, seed, stop?}  -> {events, snapshot, metrics}
                                  stop = {"max_time": ticks} and/or {"max_events": count}
  POST /api/process/step          same body plus {"steps": n}                   -> first n events
  POST /api/memory/run            {trace, policy, page_size, frames, hit_ticks, fault_ticks, pid, stop?}   (memory_api.py)
  POST /api/memory/compare        same body; FIFO and LRU on the identical trace
  POST /api/file/run              {script, user?, users?, admins?, setup?, stop?}                          (file_api.py)
  POST /api/integration/run       process workload + per-process address traces + file requests            (integration_api.py)
Inputs are validated before anything runs; problems come back as {"errors": [...]} with status 422 and change nothing.
Times in the response are integer ticks (1 tick = 0.1 ms). Written with Claude; see README Sourced Tools.
"""
from __future__ import annotations

import functools
import http.server
import json
from pathlib import Path

from ossim.ui import file_api, integration_api, memory_api
from ossim.ui.process_api import build, result, valid_stop

ROOT = Path(__file__).parent / "prototype"
MAX_BODY = 64 * 1024
PROCESS_PATHS = ("/api/process/run", "/api/process/step")
OTHER_ROUTES = {
    "/api/memory/run": memory_api.handle, "/api/memory/compare": memory_api.handle,
    "/api/file/run": file_api.handle, "/api/integration/run": integration_api.handle,
}


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
            return self._send(200, {"engine": True, "detail": "Process, Memory and File managers loaded"})
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path not in PROCESS_PATHS and self.path not in OTHER_ROUTES:
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
        if self.path in OTHER_ROUTES:
            code, payload = OTHER_ROUTES[self.path](self.path, body)
            return self._send(code, payload)
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
