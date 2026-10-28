"""IN-01, EX-03: the M2 input files load through the validated loader and run on every policy."""
from pathlib import Path

import pytest

from ossim.io.loaders import load_processes_csv
from ossim.managers.process import ProcessManager

INPUTS = Path(__file__).resolve().parents[2] / "inputs"


def test_processes_csv_has_six_or_more_processes_and_an_idle_gap():
    rows = load_processes_csv(INPUTS / "processes.csv")
    assert len(rows) >= 6
    pm = ProcessManager()
    assert pm.load(rows) == []
    pm.run()
    assert pm.snapshot()["idle"] > 0            # P7 arrives after everything else has finished


@pytest.mark.parametrize("policy", ["fcfs", "sjf", "srtf", "rr", "priority"])
def test_every_policy_finishes_the_larger_workload(policy):
    pm = ProcessManager()
    assert pm.configure({"policy": policy, "q": 3, "cs": 0.5}) == []
    assert pm.load(load_processes_csv(INPUTS / "processes.csv")) == []
    pm.run()
    s = pm.snapshot()
    assert s["finished"] and s["finished_count"] == 7
    useful = sum(q.burst for q in pm.procs.values())
    assert useful + s["idle"] + s["context_switch_time"] == s["makespan"]


def test_starvation_file_shows_the_aging_effect():
    def finish_of_L(aging):
        pm = ProcessManager()
        pm.configure({"policy": "priority", "aging": aging})
        pm.load(load_processes_csv(INPUTS / "starvation.csv"))
        pm.run()
        return pm.snapshot()["per_process"]["L"]["completion"] / 10
    assert finish_of_L(0) == 10 and finish_of_L(2) == 4
