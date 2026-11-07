import json

from ossim.ui.memory_api import handle

TRACE = open("inputs/trace_baseline.txt").read()

import sys
sys.path.append("os-sim/OS-Simulator/ossim-sim")

def test_run_returns_events_snapshot_metrics():
    code, out = handle("/api/memory/run", {"trace": TRACE, "policy": "fifo", "page_size": 4096, "frames": 3})
    assert code == 200 and out["metrics"]["faults"]["value"] == 8
    assert out["events"][0]["event_type"] == "PAGE_FAULT" and out["events"][0]["time_ms"] == 0.0
    assert out["snapshot"]["results"][:3] == ["F", "F", "H"]
    json.dumps(out)


def test_compare_uses_identical_trace_for_both_policies():
    code, out = handle("/api/memory/compare", {"trace": TRACE, "policy": "ignored"})
    assert code == 200 and set(out["runs"]) == {"fifo", "lru"}
    assert out["runs"]["fifo"]["metrics"]["faults"]["value"] == 8
    assert out["runs"]["lru"]["metrics"]["faults"]["value"] == 7


def test_stop_limits_and_errors_use_422():
    code, out = handle("/api/memory/run", {"trace": TRACE, "stop": {"max_events": 3}})
    assert code == 200 and len(out["events"]) == 3
    for body in ({"trace": 5}, {"trace": TRACE, "frames": 0}, {"trace": "zzz\n"},
                 {"trace": TRACE, "stop": {"max_events": 0}}, {"trace": TRACE, "policy": "mru"}):
        code, out = handle("/api/memory/run", body)
        assert code == 422 and out["errors"]
    assert handle("/api/memory/nope", {})[0] == 404
    code, out = handle("/api/memory/run", {"trace": "0x10\nzzz\n"})
    assert out["errors"] == ["trace:2: not a decimal or hex address: 'zzz'"]
