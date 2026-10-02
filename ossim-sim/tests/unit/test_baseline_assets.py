"""Milestone 1: baseline inputs parse and expected results are internally consistent.

Algorithm tests (T-PR-*, T-MM-*, T-FS-*) compare manager output to these same files from Milestone 2 on.
"""
import json
from pathlib import Path

from ossim.io.loaders import load_fs_script, load_processes_csv, load_trace

ROOT = Path(__file__).resolve().parents[2]


def test_process_baseline_matches_spec():
    rows = load_processes_csv(ROOT / "inputs/process_baseline.csv")
    assert [(r["pid"], r["arrival"], r["burst"], r["priority"]) for r in rows] == [
        ("P1", 0, 8, 3), ("P2", 1, 4, 1), ("P3", 2, 9, 4), ("P4", 3, 5, 2)]


def test_process_expected_is_consistent():
    exp = json.loads((ROOT / "expected_results/process_baseline.json").read_text())
    procs = {r["pid"]: r for r in load_processes_csv(ROOT / "inputs/process_baseline.csv")}
    for alg, res in exp["algorithms"].items():
        gantt = res["gantt"]
        for a, b in zip(gantt, gantt[1:], strict=False):           # contiguous, no overlap (cs = 0, no idle)
            assert a["end"] == b["start"], alg
        assert res["makespan"] == sum(p["burst"] for p in procs.values())
        for pid, m in res["per_process"].items():
            p = procs[pid]
            ran = sum(s["end"] - s["start"] for s in gantt if s["pid"] == pid)
            assert ran == p["burst"], (alg, pid)
            assert m["completion"] >= m["start"] >= p["arrival"]
            assert m["turnaround"] == m["completion"] - p["arrival"]
            assert m["waiting"] == m["turnaround"] - p["burst"]
            assert m["response"] == m["start"] - p["arrival"]


def test_memory_expected_is_consistent():
    exp = json.loads((ROOT / "expected_results/memory_baseline.json").read_text())
    trace = load_trace(ROOT / "inputs/trace_baseline.txt")
    assert trace[:4] == [0x0040, 0x10A0, 0x0044, 0x20B0]
    assert [a // exp["page_size"] for a in trace] == exp["pages"]
    for pol in ("FIFO", "LRU"):
        r = exp[pol]
        assert r["hits"] + r["faults"] == r["references"] == len(trace)
        assert r["results"].count("H") == r["hits"]
        assert r["evictions"] == r["faults"] - exp["frames"]
        avg = (r["hits"] * exp["hit_cost_ms"] + r["faults"] * exp["fault_cost_ms"]) / r["references"]
        assert abs(avg - r["avg_access_ms"]) < 1e-9


def test_file_script_has_required_commands():
    cmds = load_fs_script(ROOT / "inputs/fs_baseline.txt")
    assert len(cmds) >= 12
    assert {c for c, _ in cmds} == {"mkdir", "ls", "mkfile", "write", "append", "cat", "rm", "rmdir"}
    exp = json.loads((ROOT / "expected_results/file_baseline.json").read_text())
    assert len(exp["steps"]) == len(cmds)
    assert sum(not s["ok"] for s in exp["steps"]) == exp["totals"]["failed"] >= 3
