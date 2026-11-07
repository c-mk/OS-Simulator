"""Memory manager tests. The baseline expectations come from expected_results/memory_baseline.json."""
import csv
import io
import json

import pytest

from ossim.core.events import PHASES, REQUIRED_FIELDS
from ossim.managers.base import INTERFACE_METHODS, Manager
from ossim.managers.memory import MemoryManager, mem_ref, parse_address, refs_from_gantt

BASELINE = [0x0040, 0x10A0, 0x0044, 0x20B0, 0x3010, 0x0048, 0x10A4, 0x4000, 0x0050, 0x20B4]


def make(policy, trace, **cfg):
    mm = MemoryManager()
    assert mm.configure({"policy": policy, **cfg}) == []
    assert mm.load(trace) == []
    mm.run()
    return mm


def pages(seq):                      # page_size=1 so address == page number
    return {"page_size": 1}, seq


def test_baseline_fifo_matches_expected_results():
    mm = make("fifo", BASELINE)
    s = mm.snapshot()
    assert "".join(s["results"]) == "FFHFFFFFHF"
    assert s["evicted"] == [None, None, None, None, 0, 1, 2, 3, None, 0]
    m = mm.metrics()
    assert (m["hits"]["value"], m["faults"]["value"], m["evictions"]["value"]) == (2, 8, 5)
    assert m["avg_access_time"]["value"] == pytest.approx(4.02)
    assert m["fault_rate"] == {"value": 80.0, "unit": "percent"}
    # By frame number. (The JSON's FIFO final_frames [1,4,2] is queue order, not frame order.)
    assert [f["page"] for f in s["frames"]] == [4, 2, 1]


def test_baseline_lru_matches_expected_results():
    mm = make("lru", BASELINE)
    s = mm.snapshot()
    assert "".join(s["results"]) == "FFHFFHFFHF"
    assert s["evicted"] == [None, None, None, None, 1, None, 2, 3, None, 1]
    m = mm.metrics()
    assert (m["hits"]["value"], m["faults"]["value"], m["evictions"]["value"]) == (3, 7, 4)
    assert m["avg_access_time"]["value"] == pytest.approx(3.53)
    assert [f["page"] for f in s["frames"]] == [0, 4, 2]


def test_textbook_and_belady():
    t = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
    assert make("fifo", t, page_size=1, frames=3).metrics()["faults"]["value"] == 15
    assert make("lru", t, page_size=1, frames=3).metrics()["faults"]["value"] == 12
    b = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    f3 = make("fifo", b, page_size=1, frames=3).metrics()["faults"]["value"]
    f4 = make("fifo", b, page_size=1, frames=4).metrics()["faults"]["value"]
    assert (f3, f4) == (9, 10)


def test_page_and_offset():
    mm = make("fifo", [8200], page_size=4096)
    h = mm.history[0]
    assert (h["page"], h["offset"]) == (2, 8)


def test_address_parsing():
    assert parse_address("0x1A3F") == 6719 and parse_address("010") == 10 and parse_address(7) == 7
    for bad in ("-5", "zz", "0xZZ"):
        with pytest.raises(ValueError):
            parse_address(bad)


def test_configure_errors_change_nothing():
    mm = MemoryManager()
    before = dict(mm.config)
    errs = mm.configure({"frames": 0, "policy": "mru", "bogus": 1, "fault_ticks": -1})
    assert len(errs) == 4 and mm.config == before
    assert MemoryManager().configure({"policy": "LRU"}) == []          # case-insensitive


def test_load_uses_the_shared_trace_loader(tmp_path):
    mm = MemoryManager()
    assert mm.load([1, 2]) == []
    bad = tmp_path / "bad.txt"
    bad.write_text("0x10\nnope\n")
    assert mm.load(str(bad)) == [f"{bad}:2: not a decimal or hex address: 'nope'"]
    assert len(mm.trace) == 2                                  # nothing changed
    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n")
    assert mm.load(str(empty)) == ["Trace is empty"]
    assert "No such file" in mm.load(str(tmp_path / "missing.txt"))[0]
    assert mm.load([1, "zz", (2,)]) == ["Reference 2: invalid entry 'zz'", "Reference 3: invalid entry (2,)"]


def test_load_path_uses_configured_pid(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("0x20\n0x30  # inline\n")
    mm = MemoryManager()
    mm.configure({"pid": "P7"})
    assert mm.load(f) == [] and mm.trace == [("P7", 32, None), ("P7", 48, None)]


def test_hit_is_one_event_fault_blocks_and_unblocks():
    mm = MemoryManager()
    mm.configure({"page_size": 1, "frames": 1, "fault_ticks": 50})
    mm.load([5, 5, 6])
    ev = mm.step()
    assert [e.event_type for e in ev] == ["PAGE_FAULT", "BLOCK", "UNBLOCK"]
    assert (ev[1].prev_state, ev[1].new_state) == ("running", "waiting")
    assert (ev[2].prev_state, ev[2].new_state) == ("waiting", "ready")
    assert ev[2].time - ev[1].time == 50
    assert [e.event_type for e in mm.step()] == ["PAGE_HIT"]
    assert [e.event_type for e in mm.step()] == ["PAGE_FAULT", "PAGE_EVICT", "BLOCK", "UNBLOCK"]
    assert mm.step() == []
    assert all(e.manager == "memory" and e.correlation_id == "P1" and e.phase in PHASES for e in mm.events)
    assert [e.seq for e in mm.events] == list(range(1, len(mm.events) + 1))
    assert mm.clock == 50 + 1 + 50


def test_run_is_restartable_and_stop_limits_work():
    mm = make("lru", BASELINE)
    first = [e.seq for e in mm.run()]
    assert [e.seq for e in mm.run()] == first
    assert mm.run({"max_events": 1})[0].event_type == "PAGE_FAULT" and len(mm.events) == 3     # a reference is never cut in half
    mm.run({"max_time": 0})                      # only the reference starting at t=0
    assert len(mm.history) == 1
    mm.run({"max_time_ms": 5.0})
    assert [h["time"] for h in mm.history] == [0, 50]            # 5.0 ms = 50 ticks, inclusive
    mm.run()
    assert len(mm.history) == 10


def test_processes_have_separate_page_tables():
    mm = MemoryManager()
    mm.configure({"page_size": 10, "frames": 4})
    mm.load([("P1", 5), ("P2", 5), ("P1", 6), ("P2", 6)])
    mm.run()
    assert mm.metrics()["faults"]["value"] == 2
    assert set(mm.snapshot()["page_tables"]) == {"P1", "P2"}


def test_timed_references_never_overlap():
    mm = MemoryManager()
    mm.configure({"page_size": 1, "frames": 2, "fault_ticks": 50})
    mm.load([("P1", 1, 0), ("P2", 1, 10), ("P1", 1, 500)])
    mm.run()
    assert [h["time"] for h in mm.history] == [0, 50, 500]      # P2 waits for the fault in service


def test_refs_from_gantt_skips_cs_and_idle():
    gantt = [{"pid": "P1", "start": 0, "end": 30}, {"pid": "CS", "start": 30, "end": 40},
             {"pid": "P2", "start": 40, "end": 60}, {"pid": "P1", "start": 60, "end": 100}]
    refs = refs_from_gantt(gantt, {"P1": [0, 1, 2, 3, 4], "P2": [9]}, interval_ticks=10)
    assert refs == [("P1", 0, 0), ("P1", 1, 10), ("P1", 2, 20), ("P2", 9, 40), ("P1", 3, 60), ("P1", 4, 70)]


def test_validate_snapshot_and_exports():
    mm = MemoryManager()
    assert mm.validate() == ["No trace loaded"]
    mm.configure({"frames": 8})
    mm.load(BASELINE)
    assert any("no evictions" in w for w in mm.validate())
    mm.run()
    json.dumps(mm.snapshot())
    data = json.loads(mm.export("json"))
    assert set(data) == {"snapshot", "metrics", "events"}
    rows = list(csv.DictReader(io.StringIO(mm.export("csv"))))
    assert rows[0]["pid"] == "P1" and rows[0]["references"] == "10"
    with pytest.raises(ValueError):
        mm.export("xml")
    with pytest.raises(ValueError):
        mm.export("references_csv")                       # only json and csv are approved


def test_events_match_the_shared_record():
    mm = make("lru", BASELINE)
    for e in mm.events:
        assert REQUIRED_FIELDS <= set(e.to_dict())
        assert e.outcome == "ok" and e.manager == "memory" and e.severity == "info"
    unblock = [e for e in mm.events if e.event_type == "UNBLOCK"][0]
    assert unblock.phase == "service_done"


def test_controller_ordering_puts_unblock_before_next_reference():
    mm = MemoryManager()
    mm.configure({"page_size": 1, "frames": 1, "fault_ticks": 50})
    mm.load([5, 6])
    mm.run()
    ordered = sorted(mm.events, key=lambda e: e.sort_key())
    at_50 = [e.event_type for e in ordered if e.time == 50]
    assert at_50[0] == "UNBLOCK" and at_50[1] == "PAGE_FAULT"


def test_real_trace_files_load_with_their_header_comments():
    for name in ("baseline", "locality"):
        mm = MemoryManager()
        assert mm.load(f"inputs/trace_{name}.txt") == []
        assert mm.validate() == []                        # more pages than frames: evictions happen


def test_locality_trace_lru_beats_fifo():
    def run(policy):
        mm = MemoryManager()
        mm.configure({"policy": policy})
        mm.load("inputs/trace_locality.txt")
        mm.run()
        return mm
    fifo, lru = run("fifo"), run("lru")
    assert "".join(fifo.snapshot()["results"]) == "FFHHFHHFFFFHHFFFFHHF"
    assert "".join(lru.snapshot()["results"]) == "FFHHFHHFHHFHHFHHFHHF"
    assert (fifo.metrics()["faults"]["value"], lru.metrics()["faults"]["value"]) == (12, 8)
    assert (fifo.metrics()["fault_rate"]["value"], lru.metrics()["fault_rate"]["value"]) == (60.0, 40.0)
    assert fifo.metrics()["avg_access_time"]["value"] == pytest.approx(3.04)
    assert lru.metrics()["avg_access_time"]["value"] == pytest.approx(2.06)


def test_implements_the_manager_interface():
    mm = MemoryManager()
    assert isinstance(mm, Manager) and mm.name == "memory"
    assert all(callable(getattr(mm, name)) for name in INTERFACE_METHODS)
    mm.load([1, 2])
    mm.run()
    assert mm.export() == mm.export(fmt="json")                # fmt defaults to json


def test_step_handles_a_mem_ref_event_and_ignores_others():
    mm = MemoryManager()
    mm.configure({"page_size": 4096})
    mm.load([0x1000])
    ev = mm.step(mem_ref("P3", 0x2010, 500))
    assert ev[0].event_type == "PAGE_FAULT" and ev[0].time == 500 and ev[0].correlation_id == "P3"
    assert mm.history[0]["page"] == 2 and mm.history[0]["pid"] == "P3"
    other = mm.events[0].__class__(seq=1, time=0, scenario_id="", correlation_id="P1", manager="process",
                                   event_type="DISPATCH", entity_id="P1", action="dispatch",
                                   prev_state="ready", new_state="running", outcome="ok")
    assert mm.step(other) == []
    mm.run()                                                   # live references are not part of the trace
    assert [h["pid"] for h in mm.history] == ["P1"]
