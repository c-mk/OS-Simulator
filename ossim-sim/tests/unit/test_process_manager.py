"""Process manager algorithm test."""
import json
from pathlib import Path

import pytest

from ossim.io.loaders import load_processes_csv
from ossim.managers.base import INTERFACE_METHODS, Manager
from ossim.managers.process import ProcessManager

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((ROOT / "expected_results/process_baseline.json").read_text())
BASELINE = ROOT / "inputs/process_baseline.csv"


def _run(policy: str, **cfg) -> ProcessManager:
    mgr = ProcessManager()
    errors = mgr.configure({"policy": policy, "quantum_ms": 4, "context_switch_ms": 0, "scenario_id": "baseline-01", **cfg})
    assert errors == []
    assert mgr.load(BASELINE) == []
    mgr.run()
    return mgr


def _almost(a, b) -> None:
    assert a == pytest.approx(b)


@pytest.mark.parametrize("policy", list(EXPECTED["algorithms"]))
def test_T_PR_02_baseline_algorithms(policy):
    mgr = _run(policy)
    snap = mgr.snapshot()
    exp = EXPECTED["algorithms"][policy]
    assert snap["gantt"] == exp["gantt"]
    for pid, row in exp["per_process"].items():
        got = snap["per_process"][pid]
        assert got["start"] == row["start"]
        assert got["completion"] == row["completion"]
        assert got["turnaround"] == row["turnaround"]
        assert got["waiting"] == row["waiting"]
        assert got["response"] == row["response"]
        assert got["dispatches"] == row["dispatches"]
    _almost(snap["averages"]["turnaround"], exp["averages"]["turnaround"])
    _almost(snap["averages"]["waiting"], exp["averages"]["waiting"])
    _almost(snap["averages"]["response"], exp["averages"]["response"])
    assert snap["makespan"] == exp["makespan"]
    _almost(snap["cpu_utilization_pct"], exp["cpu_utilization_pct"])
    assert snap["idle"] == exp["idle"]


def test_T_PR_01_implements_manager_interface():
    mgr = ProcessManager()
    assert isinstance(mgr, Manager)
    for name in INTERFACE_METHODS:
        assert callable(getattr(mgr, name))


def test_configure_rejects_bad_policy_without_mutation():
    mgr = ProcessManager()
    mgr.configure({"policy": "fcfs"})
    before = mgr.snapshot()["policy"]
    errors = mgr.configure({"policy": "lottery"})
    assert errors and "lottery" in errors[0]
    assert mgr.snapshot()["policy"] == before


def test_load_does_not_keep_partial_rows_on_error():
    mgr = ProcessManager()
    assert mgr.load(load_processes_csv(BASELINE)) == []
    errors = mgr.load([{"pid": "P1", "arrival": 0, "burst": 1, "priority": 0}, {"pid": "P1", "arrival": 1, "burst": 1, "priority": 0}])
    assert errors
    assert [p["pid"] for p in mgr.snapshot()["loaded"]] == ["P1", "P2", "P3", "P4"]


def test_reset_returns_to_loaded_initial_state():
    mgr = _run("fcfs")
    assert mgr.snapshot()["gantt"]
    mgr.reset()
    snap = mgr.snapshot()
    assert snap["gantt"] == []
    assert snap["event_count"] == 0
    mgr.run()
    assert mgr.snapshot()["makespan"] == 26


def test_metrics_have_units():
    mets = _run("sjf").metrics()
    assert mets["avg_waiting"]["unit"] == "ms"
    assert mets["cpu_utilization"]["unit"] == "percent"
    assert mets["completed"]["value"] == 4


def test_export_json_and_csv():
    mgr = _run("fcfs")
    data = json.loads(mgr.export("json"))
    assert data["snapshot"]["gantt"][0]["pid"] == "P1"
    csv_text = mgr.export("csv")
    assert csv_text.splitlines()[0].startswith("pid,")
    assert "P3" in csv_text


def test_validate_warns_when_empty():
    mgr = ProcessManager()
    msgs = mgr.validate()
    assert any("no processes" in m for m in msgs)


def test_run_stop_max_time():
    mgr = ProcessManager()
    mgr.configure({"policy": "fcfs"})
    mgr.load(BASELINE)
    mgr.run({"max_time_ms": 8})
    snap = mgr.snapshot()
    assert snap["time_ms"] == 8
    assert snap["per_process"]["P1"]["completion"] == 8
    assert snap["per_process"]["P2"]["completion"] is None
