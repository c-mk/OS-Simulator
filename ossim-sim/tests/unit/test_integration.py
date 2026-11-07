"""Initial integration: process-generated memory references and authorized process file requests (T-INT-02).
Hand-worked values (FCFS baseline Gantt P1 0-8, P2 8-12, P3 12-21, P4 21-26 ms; page size 4096, 3 frames, LRU,
hit 1 tick, fault 10 ticks, one reference every 10 ticks while a process is on the CPU):
  P1 trace pages 0,1,0,2,3,0,1,4  -> F F H F F H F F : 6 faults, 2 hits (the fault on 3 evicts page 1, not the re-used 0).
  P2 trace pages 0,1,2,0, sharing the same 3 frames -> F F F H : 3 faults (it evicts P1's pages 0, 1 and 4 in turn).
  Every fault blocks for 10 ticks, so P1 is blocked 6 x 10 = 60 ticks by page faults and P2 3 x 10 = 30.
  Files: root is 775 group staff; alice and bob are staff, guest is not; new files are 640, new directories 750.
  P1/alice mkdir /shared ok, mkfile ok, write ok; P2/bob cat ok (group read), write denied (group has r only);
  P3/guest cat denied (other has nothing), mkfile denied; P4/admin rm ok."""
import json

import pytest

from ossim import integration
from ossim.ui.integration_api import handle

CSV = "pid,arrival,burst,priority\nP1,0,8,3\nP2,1,4,1\nP3,2,9,4\nP4,3,5,2\n"
P1 = "0x0000\n0x1000\n0x0000\n0x2000\n0x3000\n0x0000\n0x1000\n0x4000"
P2 = "0x0000\n0x1000\n0x2000\n0x0000"
REQS = [
    {"pid": "P1", "cmd": "mkdir", "args": ["/shared"], "at_ms": 1},
    {"pid": "P1", "cmd": "mkfile", "args": ["/shared/a.txt"], "at_ms": 2},
    {"pid": "P1", "cmd": "write", "args": ["/shared/a.txt", "report"], "at_ms": 3},
    {"pid": "P2", "cmd": "cat", "args": ["/shared/a.txt"], "at_ms": 9},
    {"pid": "P2", "cmd": "write", "args": ["/shared/a.txt", "edit"], "at_ms": 10},
    {"pid": "P3", "cmd": "cat", "args": ["/shared/a.txt"], "at_ms": 13},
    {"pid": "P3", "cmd": "mkfile", "args": ["/shared/b.txt"], "at_ms": 14},
    {"pid": "P4", "cmd": "rm", "args": ["/shared/a.txt"], "at_ms": 22},
]


def body(**over):
    b = {"csv": CSV, "policy": "fcfs",
         "memory": {"traces": {"P1": P1, "P2": P2}, "page_size": 4096, "frames": 3, "policy": "lru", "hit_ticks": 1, "fault_ticks": 10},
         "files": {"principals": {"P1": "alice", "P2": "bob", "P3": "guest", "P4": "admin"},
                   "setup": [{"path": "/", "mode": "775", "group": "staff"}], "requests": REQS}}
    b.update(over)
    return b


@pytest.fixture(scope="module")
def demo():
    code, out = handle("/api/integration/run", body())
    assert code == 200, out
    return out


def test_process_references_hit_and_fault_as_worked_by_hand(demo):
    refs = demo["memory"]["snapshot"]["references"]
    p1 = [r for r in refs if r["pid"] == "P1"]
    assert [r["result"] for r in p1] == list("FFHFFHFF")
    assert [r["time"] for r in p1] == [0, 10, 20, 30, 40, 50, 60, 70]       # one reference per 10 ticks while P1 runs
    assert [r["result"] for r in refs if r["pid"] == "P2"] == list("FFFH")
    assert demo["per_process"]["P1"]["faults"] == 6 and demo["per_process"]["P2"]["faults"] == 3
    assert demo["per_process"]["P3"]["references"] == 0               # P3 has no trace


def test_page_faults_block_then_ready(demo):
    mem = [b for b in demo["blocked"] if b["source"] == "memory" and b["pid"] == "P1"]
    assert [(b["start"], b["end"]) for b in mem] == [(0, 10), (10, 20), (30, 40), (40, 50), (60, 70), (70, 80)]
    ev = [e for e in demo["events"] if e["entity_id"] == "P1" and e["manager"] == "memory" and e["event_type"] in ("BLOCK", "UNBLOCK")]
    assert ev[0]["new_state"] == "waiting" and ev[1]["new_state"] == "ready" and ev[1]["time"] - ev[0]["time"] == 10


def test_file_requests_are_authorized_by_user(demo):
    got = [(h["pid"], h["cmd"], h["outcome"]) for h in demo["file"]["snapshot"]["log"]]
    assert got == [("P1", "mkdir", "ok"), ("P1", "mkfile", "ok"), ("P1", "write", "ok"), ("P2", "cat", "ok"),
                   ("P2", "write", "denied"), ("P3", "cat", "denied"), ("P3", "mkfile", "denied"), ("P4", "rm", "ok")]
    assert demo["per_process"]["P2"]["file_denied"] == 1 and demo["per_process"]["P3"]["file_denied"] == 2
    assert [e["severity"] for e in demo["events"] if e["outcome"] == "denied"] == ["warning"] * 3
    assert demo["file"]["metrics"]["denied"]["value"] == 3 and demo["file"]["snapshot"]["tree"]["children"][0]["children"] == []


def test_file_block_lasts_the_command_latency(demo):
    mk = next(b for b in demo["blocked"] if b["source"] == "file" and b["pid"] == "P1")
    assert (mk["start"], mk["end"]) == (10, 30)                      # mkdir costs 20 ticks, starting at 1 ms


def test_overlapping_blocks_are_counted_once_and_reported(demo):
    # P1: memory blocks cover 0-20, 30-50, 60-80; file blocks 10-30, 30-50, 50-80 -> the union is all of 0-80
    assert demo["per_process"]["P1"]["blocked_ticks"] == 80
    assert any("P1 has overlapping" in w for w in demo["warnings"])


def test_merged_events_are_in_time_order_with_fresh_sequence_numbers(demo):
    ev = demo["events"]
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
    times = [e["time"] for e in ev]
    assert times == sorted(times)
    assert {"process", "memory", "file"} <= {e["manager"] for e in ev}
    json.dumps(demo)


def test_run_is_deterministic():
    a = handle("/api/integration/run", body())[1]
    b = handle("/api/integration/run", body())[1]
    assert a == b


def test_memory_only_and_files_only_both_work():
    code, out = handle("/api/integration/run", body(files={}))
    assert code == 200 and out["file"] is None and out["memory"]["metrics"]["faults"]["value"] == 9
    code, out = handle("/api/integration/run", body(memory={}))
    assert code == 200 and out["memory"] is None and out["file"]["metrics"]["operations"]["value"] == 8


def test_a_request_while_off_cpu_is_warned_about():
    reqs = [{"pid": "P1", "cmd": "mkdir", "args": ["/x"], "at_ms": 30}]
    code, out = handle("/api/integration/run", body(memory={}, files={"requests": reqs}))
    assert code == 200 and "P1 is not on the CPU at 30 ms" in out["warnings"][0]


def test_trace_longer_than_cpu_time_is_warned_about():
    code, out = handle("/api/integration/run", body(files={}, memory={"traces": {"P2": "\n".join(["0x0"] * 10)}, "fault_ticks": 10}))
    assert code == 200 and "P2 ran for less time than its trace needs: 4 of 10 references issued" in out["warnings"]


def test_errors_are_422_and_change_nothing():
    m = {"traces": {"P1": P1}}
    cases = [
        ({"csv": "bad"}, "header must be"),
        ({"memory": {"traces": {"P9": P1}}, "files": {}}, "memory trace names process 'P9'"),
        ({"memory": {"traces": {"P1": "zzz"}}, "files": {}}, "trace P1:1: not a decimal or hex address: 'zzz'"),
        ({"memory": {"traces": {"P1": 5}}, "files": {}}, "trace for P1 must be text"),
        ({"memory": {**m, "frames": 0}, "files": {}}, "frames must be a whole number of at least 1"),
        ({"memory": {**m, "interval_ticks": 0}, "files": {}}, "interval_ticks must be a whole number of at least 1"),
        ({"memory": {"traces": {"P1": ""}}, "files": {}}, "no memory references were generated"),
        ({"memory": {}, "files": {}}, "add at least one memory trace or one file request"),
        ({"memory": [], "files": {}}, "memory must be an object with a traces object"),
        ({"files": {"requests": "x"}}, "files must be an object with a requests list"),
        ({"files": {"requests": [{"pid": "P1", "cmd": "format", "args": []}]}}, "Request 1: needs a pid from the workload and a command"),
        ({"files": {"requests": [{"pid": "P7", "cmd": "ls", "args": []}]}}, "Request 1: needs a pid"),
        ({"files": {"requests": [{"pid": "P1", "cmd": "ls", "args": [], "at_ms": -1}]}}, "Request 1: at_ms must be a number"),
        ({"files": {"requests": [{"pid": "P1", "cmd": "mkdir", "args": []}]}}, "Command 1: mkdir takes 1 argument(s), got 0"),
        ({"files": {"requests": REQS[:1], "principals": {"P1": 5}}}, "principals must map each process to a user name"),
        ({"files": {"requests": REQS[:1], "setup": [{"path": "/"}]}}, "each setup entry needs a path and a mode"),
    ]
    for over, msg in cases:
        code, out = handle("/api/integration/run", body(**over))
        assert code == 422 and msg in out["errors"][0], (over, out)
    assert handle("/api/integration/nope", {})[0] == 404


def test_too_many_requests_are_refused(monkeypatch):
    monkeypatch.setattr(integration, "MAX_REQUESTS", 2)
    code, out = handle("/api/integration/run", body(memory={}))
    assert code == 422 and out["errors"] == ["too many file requests (limit 2)"]
