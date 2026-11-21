"""HTTP integration coverage for security and the six-manager scenario endpoint."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from ossim.ui.__main__ import make_server


@pytest.fixture(scope="module")
def base():
    server = make_server(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def post(base, path, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                    headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def scenario():
    return {
        "csv": "pid,arrival,burst,priority\nP1,0,3,1",
        "policy": "fcfs", "q": 4, "cs": 0, "aging": 0, "seed": 0,
        "memory": {"traces": {"P1": "0x0\n0x1000"}, "page_size": 4096, "frames": 2,
                    "policy": "lru", "hit_ticks": 1, "fault_ticks": 10, "interval_ticks": 10},
        "files": {"requests": [{"pid": "P1", "cmd": "mkdir", "args": ["/work"], "at_ms": 0}],
                  "principals": {"P1": "alice"}, "setup": [{"path": "/", "mode": "775", "group": "staff"}]},
        "security": {"operations": [{"action": "login", "user": "alice", "at": 0},
                                     {"action": "access", "user": "alice", "resource": "files", "permission": "read", "at": 1}]},
        "device": {"requests": [{"id": "disk-1", "device": "disk", "pid": "P1", "cylinder": 60}]},
        "network": {"nodes": ["A", "B"], "links": [{"from": "A", "to": "B", "delay": 3}],
                    "packets": [{"id": "pkt-1", "source": "A", "destination": "B"}]},
    }


def test_security_and_six_manager_scenario_endpoints(base):
    code, security = post(base, "/api/security/run", {"operations": [{"action": "login", "user": "alice"}]})
    assert code == 200 and security["snapshot"]["active_sessions"] == ["alice"]
    code, result = post(base, "/api/scenario/run", scenario())
    assert code == 200
    assert set(result["managers"]) == {"process", "memory", "file", "security", "device", "network"}
    assert {event["manager"] for event in result["events"]} >= {"process", "memory", "file", "security", "device", "network"}
    assert result["events"] == sorted(result["events"], key=lambda e: (e["time"], e["seq"]))
