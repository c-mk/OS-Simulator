"""Error and boundary cases for configure()/load() (T-PR-01, T-PR-07, T-INV-*). A rejected call changes nothing."""
import pytest

from ossim.managers.process import ProcessManager
from ossim.model.process import NEW, READY, RUNNING, TERMINATED, IllegalTransition, Process
from tests.unit.helpers import BASELINE, gantt_ms, rows, simulate


def fresh():
    pm = ProcessManager()
    assert pm.load(rows(BASELINE)) == []
    return pm


@pytest.mark.parametrize("bad,fragment", [
    ({"policy": "lottery"}, "policy must be one of"),
    ({"q": 0}, "q must be at least 0.1 ms"),
    ({"q": -2}, "q must be a non-negative multiple"),
    ({"q": 0.05}, "q must be a non-negative multiple"),
    ({"q": "4"}, "q must be a number"),
    ({"cs": -1}, "cs must be a non-negative multiple"),
    ({"cs": 0.25}, "cs must be a non-negative multiple"),
    ({"aging": -1}, "aging must be a non-negative multiple"),
    ({"seed": 1.5}, "seed must be an integer"),
    ({"seed": True}, "seed must be an integer"),
    ({"preemptive": "yes"}, "preemptive must be true or false"),
    ({"speed": 3}, "unknown setting"),
])
def test_configure_rejects_bad_values_with_a_specific_message(bad, fragment):
    pm = fresh()
    errors = pm.configure(bad)
    assert errors and any(fragment in e for e in errors), errors


def test_rejected_configure_changes_nothing():
    pm = fresh()
    assert pm.configure({"policy": "rr", "q": 2}) == []
    before = dict(pm.config)
    assert pm.configure({"policy": "sjf", "q": -1})
    assert pm.config == before


def test_configure_reports_every_problem_at_once():
    assert len(fresh().configure({"policy": "x", "q": -1, "cs": -1})) == 3


@pytest.mark.parametrize("data,fragment", [
    ([], "non-empty list"),
    ("not-a-list-or-path-that-exists.csv", "No such file"),
    ([{"pid": "P1", "arrival": 0, "burst": 5}], "needs pid, arrival, burst and priority"),
    ([{"pid": "P 1", "arrival": 0, "burst": 5, "priority": 1}], "invalid pid"),
    ([{"pid": "P1", "arrival": 0, "burst": 5, "priority": 1}, {"pid": "P1", "arrival": 1, "burst": 5, "priority": 1}], "duplicate pid P1"),
    ([{"pid": "P1", "arrival": -1, "burst": 5, "priority": 1}], "arrival >= 0, burst > 0, priority >= 0"),
    ([{"pid": "P1", "arrival": 0, "burst": 0, "priority": 1}], "burst > 0"),
    ([{"pid": "P1", "arrival": 0, "burst": 5, "priority": -1}], "priority >= 0"),
    ([{"pid": "P1", "arrival": 0.5, "burst": 5, "priority": 1}], "must be integers"),
    ([{"pid": "P1", "arrival": "0", "burst": 5, "priority": 1}], "must be integers"),
    ([{"pid": "P1", "arrival": 0, "burst": 2_000_000, "priority": 1}], "at most 1000000 ms"),
])
def test_load_rejects_bad_workloads(data, fragment):
    pm = ProcessManager()
    errors = pm.load(data)
    assert errors and any(fragment in e for e in errors), errors


def test_too_many_processes_rejected():
    errors = ProcessManager().load([{"pid": f"P{i}", "arrival": 0, "burst": 1, "priority": 0} for i in range(1001)])
    assert errors and "at most 1000" in errors[0]


def test_rejected_load_keeps_the_previous_workload():
    pm = fresh()
    assert pm.load([{"pid": "X", "arrival": 0, "burst": -3, "priority": 1}])
    assert sorted(pm.procs) == ["P1", "P2", "P3", "P4"]


def test_load_from_csv_path_uses_the_validated_loader(tmp_path):
    good = tmp_path / "w.csv"
    good.write_text("pid,arrival,burst,priority\nP1,0,2,1\n")
    pm = ProcessManager()
    assert pm.load(str(good)) == []
    bad = tmp_path / "bad.csv"
    bad.write_text("pid,arrival,burst\nP1,0,2\n")
    assert "header must be pid,arrival,burst,priority" in pm.load(str(bad))[0]


def test_running_with_nothing_loaded_does_not_crash_and_validate_says_so():
    pm = ProcessManager()
    events = pm.run()
    assert [e.event_type for e in events] == ["SIM_START"]
    assert "error: no workload loaded" in pm.validate()


def test_validate_warns_about_ignored_or_risky_settings():
    pm = fresh()
    pm.configure({"policy": "fcfs", "aging": 5})
    assert any("aging only applies" in m for m in pm.validate())
    pm.configure({"policy": "priority", "aging": 0})
    assert any("starve" in m for m in pm.validate())


def test_export_formats():
    pm, events = simulate(BASELINE, policy="fcfs")
    import csv as csvmod
    import io
    import json
    data = json.loads(pm.export("json"))
    assert len(data["events"]) == len(events) and data["snapshot"]["makespan"] == 260
    table = list(csvmod.DictReader(io.StringIO(pm.export("csv"))))
    assert len(table) == len(events) and table[0]["event_type"] == "SIM_START"
    with pytest.raises(ValueError, match="unknown export format"):
        pm.export("xml")


# ---------------------------------------------------------------- state machine (T-PR-07)
def test_legal_state_path():
    p = Process("P1", 0, 10, 1, 0)
    assert p.state == NEW
    assert p.transition(READY) == NEW
    p.transition(RUNNING)
    p.transition(READY)
    p.transition(RUNNING)
    p.transition(TERMINATED)
    assert p.state == TERMINATED


@pytest.mark.parametrize("path,bad", [
    ([], RUNNING),                       # new -> running
    ([READY], TERMINATED),               # ready -> terminated
    ([READY, RUNNING, TERMINATED], READY),  # terminated is final
    ([READY], READY),                    # no self loop
])
def test_illegal_transitions_are_rejected_and_leave_state_unchanged(path, bad):
    p = Process("P1", 0, 10, 1, 0)
    for s in path:
        p.transition(s)
    before = p.state
    with pytest.raises(IllegalTransition):
        p.transition(bad)
    assert p.state == before


def test_blocked_state_is_reachable_for_later_milestones():
    p = Process("P1", 0, 10, 1, 0)
    for s in (READY, RUNNING, "blocked", READY):
        p.transition(s)
    assert p.state == READY


def test_every_logged_state_change_follows_the_state_machine():
    from ossim.model.process import VALID_TRANSITIONS
    _, events = simulate(BASELINE, policy="rr", q=4, cs=1)
    last = {}
    for e in events:
        if e.manager != "process" or e.prev_state is None or e.event_type in ("CONTEXT_SWITCH", "PRIORITY_AGED"):
            continue
        assert e.new_state in VALID_TRANSITIONS[e.prev_state]
        assert last.get(e.entity_id, e.prev_state) == e.prev_state      # each change starts where the last one ended
        last[e.entity_id] = e.new_state
    assert set(last.values()) == {TERMINATED}


def test_gantt_never_overlaps_and_runs_sum_to_burst():
    pm, _ = simulate(BASELINE, policy="rr", q=3, cs=0.5)
    segs = pm.snapshot()["gantt"]
    for a, b in zip(segs, segs[1:], strict=False):
        assert a["end"] <= b["start"] or a["end"] == b["start"]
    for pid, burst in (("P1", 8), ("P2", 4), ("P3", 9), ("P4", 5)):
        assert sum(s["end"] - s["start"] for s in segs if s["pid"] == pid) == burst * 10
    assert gantt_ms(pm)[0][0] == "P1"
