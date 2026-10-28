"""T-PR-02..T-PR-06, T-BASE-01: every policy against the hand-calculated baseline (expected_results/process_baseline.json,
inputs/process_baseline.csv). The literal Gantt strings below come from section 9.1 of the Milestone 1 report."""
import json
from pathlib import Path

import pytest

from tests.unit.helpers import BASELINE, gantt_ms, per_process_ms, simulate

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((ROOT / "expected_results" / "process_baseline.json").read_text())["algorithms"]

CASES = {
    "fcfs": {"policy": "fcfs"},
    "sjf": {"policy": "sjf"},
    "srtf": {"policy": "srtf"},
    "rr_q4": {"policy": "rr", "q": 4},
    "priority_np": {"policy": "priority"},
    "priority_p_no_aging": {"policy": "priority", "preemptive": True},
}

HAND_GANTT = {   # (pid, start, end) in ms, worked by hand in the M1 report
    "fcfs": [("P1", 0, 8), ("P2", 8, 12), ("P3", 12, 21), ("P4", 21, 26)],
    "sjf": [("P1", 0, 8), ("P2", 8, 12), ("P4", 12, 17), ("P3", 17, 26)],
    "srtf": [("P1", 0, 1), ("P2", 1, 5), ("P4", 5, 10), ("P1", 10, 17), ("P3", 17, 26)],
    "rr_q4": [("P1", 0, 4), ("P2", 4, 8), ("P3", 8, 12), ("P4", 12, 16), ("P1", 16, 20), ("P3", 20, 24), ("P4", 24, 25), ("P3", 25, 26)],
    "priority_np": [("P1", 0, 8), ("P2", 8, 12), ("P4", 12, 17), ("P3", 17, 26)],
    "priority_p_no_aging": [("P1", 0, 1), ("P2", 1, 5), ("P4", 5, 10), ("P1", 10, 17), ("P3", 17, 26)],
}


@pytest.mark.parametrize("key", CASES)
def test_gantt_matches_hand_calculation(key):
    pm, _ = simulate(BASELINE, **CASES[key])
    assert gantt_ms(pm) == HAND_GANTT[key]
    assert [(g["pid"], g["start"], g["end"]) for g in EXPECTED[key]["gantt"]] == HAND_GANTT[key]   # JSON file agrees too


@pytest.mark.parametrize("key", CASES)
def test_per_process_and_aggregate_metrics_match_expected_file(key):
    pm, _ = simulate(BASELINE, **CASES[key])
    exp = EXPECTED[key]
    snap = pm.snapshot()
    for pid, want in exp["per_process"].items():
        got = per_process_ms(pm, pid)
        for field, value in want.items():
            assert got[field] == value, f"{key} {pid} {field}"
    for name, value in exp["averages"].items():
        assert snap["averages"][name] / 10 == pytest.approx(value)
    assert snap["makespan"] / 10 == exp["makespan"]
    assert snap["cpu_utilization_pct"] == pytest.approx(exp["cpu_utilization_pct"])
    assert snap["idle"] == 0 and snap["context_switch_time"] == 0


def test_round_robin_worked_example_from_report():
    """RR q=4: waiting = turnaround - burst = 12, 3, 15, 17 -> average 11.75 ms."""
    pm, _ = simulate(BASELINE, policy="rr", q=4)
    waits = [per_process_ms(pm, p)["waiting"] for p in ("P1", "P2", "P3", "P4")]
    assert waits == [12, 3, 15, 17]
    assert sum(waits) / 4 == 11.75


@pytest.mark.parametrize("key", CASES)
def test_useful_plus_idle_plus_cs_equals_makespan(key):
    """T-PR-10."""
    pm, _ = simulate(BASELINE, **CASES[key])
    s = pm.snapshot()
    useful = sum(p["burst"] for p in [dict(burst=b * 10) for _, _, b, _ in BASELINE])
    assert useful + s["idle"] + s["context_switch_time"] == s["makespan"]
