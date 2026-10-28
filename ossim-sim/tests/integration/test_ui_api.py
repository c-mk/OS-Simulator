"""Dashboard server API: runs the real engine over HTTP on localhost (T-UI-02, T-INT-01)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from ossim.ui.__main__ import make_server

BASELINE_CSV = "pid,arrival,burst,priority\nP1,0,8,3\nP2,1,4,1\nP3,2,9,4\nP4,3,5,2\n"


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


def test_status_reports_engine(base):
    assert call(base, "/api/status") == (200, {"engine": True, "detail": "Process Manager loaded"})


def test_run_baseline_srtf_matches_hand_calculation(base):
    body = {"csv": BASELINE_CSV, "policy": "srtf", "preemptive": True, "q": 4, "cs": 0, "aging": 0, "seed": 42}
    code, out = call(base, "/api/process/run", body)
    assert code == 200
    snap = out["snapshot"]
    gantt = [(g["pid"], g["start"] // 10, g["end"] // 10) for g in snap["gantt"]]
    assert gantt == [("P1", 0, 1), ("P2", 1, 5), ("P4", 5, 10), ("P1", 10, 17), ("P3", 17, 26)]
    assert snap["averages"] == {"turnaround": 130.0, "waiting": 65.0, "response": 42.5}
    assert out["events"][0]["event_type"] == "SIM_START" and out["metrics"]["makespan"]["value"] == 26


def test_step_returns_only_the_first_events(base):
    code, out = call(base, "/api/process/step", {"csv": BASELINE_CSV, "policy": "fcfs", "steps": 3})
    assert code == 200 and [e["event_type"] for e in out["events"]] == ["SIM_START", "ARRIVE", "DISPATCH"]
    assert out["snapshot"]["running"] == "P1"


@pytest.mark.parametrize("csv,fragment", [
    ("pid,arrival,burst\nP1,0,5\n", "header must be pid,arrival,burst,priority"),
    (BASELINE_CSV + "P1,9,9,9\n", "duplicate pid P1"),
    ("pid,arrival,burst,priority\nP1,0,-5,1\n", "burst > 0"),
    ("pid,arrival,burst,priority\nP1,zero,5,1\n", "must be integers"),
    ("", "header must be"),
])
def test_bad_workloads_get_specific_errors_with_line_numbers(base, csv, fragment):
    code, out = call(base, "/api/process/run", {"csv": csv})
    assert code == 422 and any(fragment in e for e in out["errors"]), out
    assert "/tmp" not in json.dumps(out)


def test_bad_settings_are_rejected(base):
    code, out = call(base, "/api/process/run", {"csv": BASELINE_CSV, "policy": "rr", "q": 0, "cs": -1})
    assert code == 422 and len(out["errors"]) == 2


def test_bad_requests(base):
    assert call(base, "/api/process/run", raw=b"not json")[0] == 400
    assert call(base, "/api/process/run", raw=b"[1]")[0] == 400
    assert call(base, "/api/nope", {})[0] == 404
    assert call(base, "/api/process/step", {"csv": BASELINE_CSV, "steps": 0})[0] == 422
    assert call(base, "/api/process/run", {"csv": 5})[0] == 422


def test_dashboard_page_is_served(base):
    with urllib.request.urlopen(base + "/index.html") as r:
        assert b"OS Simulator" in r.read()


def test_stop_condition_ends_the_run_early(base):
    code, out = call(base, "/api/process/run", {"csv": BASELINE_CSV, "policy": "fcfs", "stop": {"max_time": 100}})
    assert code == 200 and out["snapshot"]["finished"] is False
    assert out["snapshot"]["per_process"]["P1"]["completion"] == 80 and out["snapshot"]["per_process"]["P2"]["completion"] is None
    code, out = call(base, "/api/process/run", {"csv": BASELINE_CSV, "stop": {"max_events": 4}})
    assert code == 200 and len(out["events"]) == 4


@pytest.mark.parametrize("stop", [{}, {"max_time": 0}, {"max_events": -1}, {"speed": 3}, "now", {"max_time": 1.5}])
def test_bad_stop_conditions_are_rejected(base, stop):
    code, out = call(base, "/api/process/run", {"csv": BASELINE_CSV, "stop": stop})
    assert code == 422 and "stop must be" in out["errors"][0]
