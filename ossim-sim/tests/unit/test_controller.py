"""Controller: clock, event queue, log, seed, run/pause/step/reset (T-CORE-01..05, T-REG-01)."""
import pytest

from ossim.core.controller import ERROR, FINISHED, PAUSED, READY, Controller
from ossim.core.events import REQUIRED_FIELDS, Event
from ossim.managers.process import ProcessManager
from tests.unit.helpers import BASELINE, rows


def make(seed=0, **config):
    pm = ProcessManager()
    assert pm.configure(config) == [] and pm.load(rows(BASELINE)) == []
    ctl = Controller(seed=seed, scenario_id="t")
    ctl.register("process", pm)
    ctl.reset()
    return ctl, pm


def dicts(log):
    return [e.to_dict() for e in log]


def test_run_to_the_end_finishes_and_logs_in_order():
    ctl, _ = make(policy="srtf")
    ctl.run()
    assert ctl.state == FINISHED and ctl.time == 260
    assert [e.seq for e in ctl.log] == list(range(1, len(ctl.log) + 1))          # contiguous sequence numbers
    assert all(a.time <= b.time for a, b in zip(ctl.log, ctl.log[1:], strict=False))   # the clock never goes backwards
    assert all(REQUIRED_FIELDS <= set(e.to_dict()) for e in ctl.log)               # every event matches the schema (T-EV-01)
    assert {e.scenario_id for e in ctl.log} == {"t"}


def test_same_tick_events_run_in_phase_order():
    ctl, _ = make(policy="rr", q=4)
    ctl.run()
    order = {"completion": 0, "arrival": 2, "quantum_expiry": 3, "preemption": 4, "dispatch": 5, "other": 6}
    by_time = {}
    for e in (x for x in ctl.log if x.event_type != "SIM_START"):   # SIM_START only seeds the arrivals
        by_time.setdefault(e.time, []).append(order[e.phase])
    assert all(v == sorted(v) for v in by_time.values())


def test_step_processes_one_event_at_a_time():
    ctl, _ = make(policy="fcfs")
    first = ctl.step()
    assert [e.event_type for e in first] == ["SIM_START"] and ctl.time == 0
    second = ctl.step()
    assert [e.event_type for e in second] == ["ARRIVE"] and second[0].entity_id == "P1"


def test_stepping_one_by_one_matches_a_single_run():
    a, _ = make(policy="rr", q=4)
    b, _ = make(policy="rr", q=4)
    a.run()
    while b.state != FINISHED:
        b.step()
    assert dicts(a.log) == dicts(b.log)


def test_run_with_stop_condition_then_continue():
    full, _ = make(policy="sjf")
    full.run()
    part, _ = make(policy="sjf")
    part.run({"max_events": 5})
    assert len(part.log) == 5 and part.state != FINISHED
    part.run()
    assert dicts(part.log) == dicts(full.log)


def test_max_time_stop_condition():
    ctl, _ = make(policy="fcfs")
    ctl.run({"max_time": 80})             # ticks: stop before anything later than 8 ms
    assert ctl.time <= 80 and ctl.state != FINISHED
    ctl.run()
    assert ctl.state == FINISHED


def test_pause_then_resume():
    ctl, _ = make(policy="fcfs")
    ctl.run({"max_events": 3})
    ctl.pause()
    assert ctl.state == PAUSED
    ctl.step()                            # single-stepping works while paused
    assert len(ctl.log) == 4
    ctl.run()
    assert ctl.state == FINISHED


def test_reset_returns_to_time_zero_and_replays_identically():
    ctl, pm = make(policy="rr", q=4)
    ctl.run()
    first = dicts(ctl.log)
    ctl.reset()
    assert ctl.time == 0 and ctl.log == [] and ctl.state == READY and pm.snapshot()["finished"] is False
    ctl.run()
    assert dicts(ctl.log) == first


def test_same_seed_and_inputs_give_identical_logs():
    a, _ = make(seed=42, policy="priority", preemptive=True)
    b, _ = make(seed=42, policy="priority", preemptive=True)
    a.run()
    b.run()
    assert dicts(a.log) == dicts(b.log)
    assert a.log[0].message == "seed 42"


def test_rng_streams_are_per_manager_and_reproducible():
    c = Controller(seed=7)
    assert c.rng("process").random() == Controller(seed=7).rng("process").random()
    assert c.rng("process").random() != c.rng("memory").random()


def test_event_limit_stops_a_runaway_run_with_an_error():
    ctl = Controller(event_limit=5)
    pm = ProcessManager()
    pm.load(rows(BASELINE))
    ctl.register("process", pm)
    ctl.reset()
    ctl.run()
    assert ctl.state == ERROR and ctl.log[-1].event_type == "EVENT_LIMIT" and ctl.log[-1].severity == "critical"
    assert ctl.step() == []               # stays stopped


def test_scheduling_an_event_in_the_past_is_rejected():
    ctl, _ = make(policy="fcfs")
    ctl.run({"max_events": 6})
    with pytest.raises(ValueError, match="in the past"):
        ctl.schedule(Event(0, 0, "t", "x", "process", "ARRIVE", "P9", "arrive", None, "ready", "ok"))


def test_cross_manager_requests_are_not_part_of_this_milestone():
    with pytest.raises(NotImplementedError):
        Controller().request("P1", "memory", {})


def test_snapshot_is_json_safe():
    import json
    ctl, _ = make(policy="fcfs")
    ctl.run({"max_events": 4})
    json.dumps(ctl.snapshot())
