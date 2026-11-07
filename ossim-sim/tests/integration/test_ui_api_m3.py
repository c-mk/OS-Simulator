"""Dashboard server, Milestone 3 routes: memory, file and integration over real HTTP on localhost (T-UI-03, T-INT-03)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from ossim.ui.__main__ import make_server

TRACE_BASE = open("inputs/trace_baseline.txt").read()
TRACE_LOC = open("inputs/trace_locality.txt").read()
FS_SCRIPT = open("inputs/fs_script.txt").read()
CSV = "pid,arrival,burst,priority\nP1,0,8,3\nP2,1,4,1\nP3,2,9,4\nP4,3,5,2\n"


@pytest.fixture(scope="module")
def base():
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_status_names_the_three_managers(base):
    assert call(base, "/api/status") == (200, {"engine": True, "detail": "Process, Memory and File managers loaded"})


def test_memory_compare_over_http_matches_the_hand_worked_trace_results(base):
    code, out = call(base, "/api/memory/compare", {"trace": TRACE_BASE, "page_size": 4096, "frames": 3})
    assert code == 200
    assert (out["runs"]["fifo"]["metrics"]["faults"]["value"], out["runs"]["lru"]["metrics"]["faults"]["value"]) == (8, 7)
    code, out = call(base, "/api/memory/compare", {"trace": TRACE_LOC, "page_size": 4096, "frames": 3})
    assert (out["runs"]["fifo"]["metrics"]["faults"]["value"], out["runs"]["lru"]["metrics"]["faults"]["value"]) == (12, 8)


def test_file_run_over_http(base):
    code, out = call(base, "/api/file/run", {"script": FS_SCRIPT})
    assert code == 200 and out["metrics"]["succeeded"]["value"] == 15 and out["metrics"]["failed"]["value"] == 5
    assert out["csv"].splitlines()[0].startswith("index,time_ms,user")


def test_integration_run_over_http(base):
    body = {"csv": CSV, "policy": "fcfs",
            "memory": {"traces": {"P1": "0x0\n0x1000\n0x0"}, "page_size": 4096, "frames": 2, "policy": "lru", "fault_ticks": 10},
            "files": {"requests": [{"pid": "P2", "cmd": "mkdir", "args": ["/x"], "at_ms": 9}], "principals": {"P2": "guest"}}}
    code, out = call(base, "/api/integration/run", body)
    assert code == 200 and out["per_process"]["P1"]["faults"] == 2 and out["per_process"]["P2"]["file_denied"] == 1


def test_bad_bodies_are_rejected_on_every_new_route(base):
    for path, body, frag in [("/api/memory/run", {"trace": "zzz"}, "not a decimal or hex"),
                             ("/api/memory/compare", {"trace": TRACE_BASE, "frames": 0}, "frames must be"),
                             ("/api/file/run", {"script": "format /"}, "unknown command"),
                             ("/api/integration/run", {"csv": "bad"}, "header must be")]:
        code, out = call(base, path, body)
        assert code == 422 and frag in out["errors"][0], (path, out)
        assert call(base, path, raw=b"not json")[0] == 400
        assert call(base, path, raw=b"[1]")[0] == 400
        assert call(base, path, raw=b"x" * (65 * 1024))[0] == 413
    assert call(base, "/api/memory/other", {})[0] == 404


def test_process_routes_still_work_after_the_refactor(base):
    code, out = call(base, "/api/process/run", {"csv": CSV, "policy": "fcfs"})
    assert code == 200 and out["snapshot"]["makespan"] == 260
