"""Initial integration of the process, memory and file managers (Milestone 3). Owner: Rasheed (with Copernic and Liberty).

What it does
  1. Runs the Process Manager on the workload and takes its CPU Gantt chart.
  2. Process-generated memory references: while a process holds the CPU it issues its next address every
     `interval_ticks` (ossim.managers.memory.refs_from_gantt). Those references go to the Memory Manager, which
     BLOCKs a process during a page fault and UNBLOCKs it (ready) when the page is loaded.
  3. Authorized process file requests: each request names a process, a command and a time. The File Manager runs it
     as the user mapped to that process ("principals") and answers ok, failed or denied by owner/group/other bits.
     The process is BLOCKed while the request is served, then UNBLOCKed.
  4. All events are merged in time order (same-tick order follows ADR-0001) so the dashboard can correlate them.

What it does not do yet (stated, not hidden): a block does not feed back into CPU scheduling. The process Gantt is the
one the Process Manager produced on its own; the blocked intervals are shown next to it. Memory references and file
requests are independent streams, so a process can show a memory block and a file block at the same time. Each manager serves one
request at a time, so a reference or request that arrives while the previous one is still being served starts when
that one finishes. Feeding blocks back through the shared controller is Milestone 4 work.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from typing import Any

from ossim.core.events import PHASES, TICKS_PER_MS, Event
from ossim.io.loaders import InputError, load_trace
from ossim.managers.file import COMMANDS, FileManager
from ossim.managers.memory import MemoryManager, refs_from_gantt
from ossim.ui.process_api import build as build_process

MEMORY_KEYS = ("page_size", "frames", "policy", "hit_ticks", "fault_ticks")
FILE_KEYS = ("users", "admins", "user")
MAX_REQUESTS = 500
MAX_TRACE_LINES = 5000


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _trace(text: Any, label: str) -> tuple[list[int], list[str]]:
    if not isinstance(text, str):
        return [], [f"trace for {label} must be text"]
    if text.count("\n") > MAX_TRACE_LINES:
        return [], [f"trace for {label} is too long (limit {MAX_TRACE_LINES} lines)"]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return load_trace(path), []
    except InputError as e:
        return [], [str(e).replace(path, f"trace {label}")]
    finally:
        os.unlink(path)


def _running(gantt: list, pid: str, at: int) -> bool:
    return any(g["pid"] == pid and g["start"] <= at < g["end"] for g in gantt)


def run_integration(body: dict[str, Any]) -> tuple[dict | None, list[str]]:
    pm, errors = build_process(body)
    if errors:
        return None, errors
    p_events = pm.run()
    gantt = pm.snapshot()["gantt"]
    pids = set(pm.procs)
    warnings: list[str] = []

    # ---- memory ----
    mm = None
    mem = {} if body.get("memory") is None else body["memory"]
    traces = mem.get("traces", {}) if isinstance(mem, dict) else None
    if not isinstance(mem, dict) or not isinstance(traces, dict):
        return None, ["memory must be an object with a traces object"]
    if traces:
        workloads: dict[str, list[int]] = {}
        for pid, text in traces.items():
            if pid not in pids:
                errors.append(f"memory trace names process {pid!r}, which is not in the workload")
                continue
            addrs, errs = _trace(text, pid)
            errors += errs
            if addrs:
                workloads[pid] = addrs
        interval = mem.get("interval_ticks", 10)
        if not _is_int(interval) or interval < 1:
            errors.append("interval_ticks must be a whole number of at least 1")
        if errors:
            return None, errors
        mm = MemoryManager()
        errors = mm.configure({k: mem[k] for k in MEMORY_KEYS if k in mem})
        if errors:
            return None, errors
        refs = refs_from_gantt(gantt, workloads, interval)
        if not refs:
            return None, ["no memory references were generated (traces are empty or those processes never run)"]
        errors = mm.load(refs)
        if errors:
            return None, errors
        m_events = mm.run()
        done = {pid: sum(1 for r in refs if r[0] == pid) for pid in workloads}
        for pid, n in done.items():
            if n < len(workloads[pid]):
                warnings.append(f"{pid} ran for less time than its trace needs: {n} of {len(workloads[pid])} references issued")
    else:
        m_events = []

    # ---- files ----
    fm = None
    files = {} if body.get("files") is None else body["files"]
    requests = files.get("requests", []) if isinstance(files, dict) else None
    if not isinstance(files, dict) or not isinstance(requests, list):
        return None, ["files must be an object with a requests list"]
    if requests:
        principals = files.get("principals") or {}
        if not isinstance(principals, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in principals.items()):
            return None, ["principals must map each process to a user name"]
        if len(requests) > MAX_REQUESTS:
            return None, [f"too many file requests (limit {MAX_REQUESTS})"]
        entries = []
        for i, r in enumerate(requests, 1):
            if not isinstance(r, dict) or r.get("cmd") not in COMMANDS or r.get("pid") not in pids:
                errors.append(f"Request {i}: needs a pid from the workload and a command ({', '.join(COMMANDS)})")
                continue
            at_ms = r.get("at_ms", 0)
            if isinstance(at_ms, bool) or not isinstance(at_ms, (int, float)) or at_ms < 0:
                errors.append(f"Request {i}: at_ms must be a number of 0 or more")
                continue
            at = int(round(at_ms * TICKS_PER_MS))
            pid = r["pid"]
            if not _running(gantt, pid, at):
                warnings.append(f"Request {i}: {pid} is not on the CPU at {at_ms} ms, so it could not issue this request then")
            entries.append({"cmd": r["cmd"], "args": r.get("args", []), "at": at, "pid": pid,
                            "user": principals.get(pid)})
        if errors:
            return None, errors
        entries.sort(key=lambda e: e["at"])
        fm = FileManager()
        errors = fm.configure({k: files[k] for k in FILE_KEYS if k in files})
        if errors:
            return None, errors
        errors = fm.load(entries)
        if errors:
            return None, errors
        for item in files.get("setup") or []:
            if not isinstance(item, dict) or "path" not in item or "mode" not in item:
                return None, ["each setup entry needs a path and a mode"]
            errors = fm.set_mode(item["path"], str(item["mode"]), item.get("owner"), item.get("group"))
            if errors:
                return None, errors
        f_events = fm.run()
    else:
        f_events = []

    if mm is None and fm is None:
        return None, ["add at least one memory trace or one file request to integrate"]

    # ---- merge, blocked intervals, per-process summary ----
    tagged = [(e, 0, i) for i, e in enumerate(p_events)] + [(e, 1, i) for i, e in enumerate(m_events)] + \
             [(e, 2, i) for i, e in enumerate(f_events)]
    tagged.sort(key=lambda t: (t[0].time, PHASES.index(t[0].phase), t[1], t[2]))
    merged: list[Event] = [replace(e, seq=n) for n, (e, _, _) in enumerate(tagged, 1)]
    blocked, open_ = [], {}
    for e in merged:                       # pair BLOCK/UNBLOCK per process and per manager (two managers can block at once)
        key = (e.entity_id, e.manager)
        if e.event_type == "BLOCK":
            open_[key] = (e.time, "page fault" if e.action == "page_fault" else "file request")
        elif e.event_type == "UNBLOCK" and key in open_:
            start, why = open_.pop(key)
            blocked.append({"pid": e.entity_id, "start": start, "end": e.time, "reason": why, "source": e.manager})
    per = {}
    for pid in sorted(pids):
        rows = [h for h in (mm.history if mm else []) if h["pid"] == pid]
        reqs = [h for h in (fm.history if fm else []) if h["pid"] == pid]
        spans = sorted((b["start"], b["end"]) for b in blocked if b["pid"] == pid)
        union, end = 0, -1
        for a, b in spans:                 # overlapping blocks count once
            union += max(0, b - max(a, end))
            end = max(end, b)
        if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
            warnings.append(f"{pid} has overlapping memory and file blocks: the two request streams are independent in this milestone")
        per[pid] = {"references": len(rows), "faults": sum(not h["hit"] for h in rows),
                    "file_ok": sum(h["outcome"] == "ok" for h in reqs), "file_failed": sum(h["outcome"] == "failed" for h in reqs),
                    "file_denied": sum(h["outcome"] == "denied" for h in reqs), "blocked_ticks": union}
    return {
        "events": [e.to_dict() for e in merged],
        "process": {"snapshot": pm.snapshot(), "metrics": pm.metrics()},
        "memory": {"snapshot": mm.snapshot(), "metrics": mm.metrics()} if mm else None,
        "file": {"snapshot": fm.snapshot(), "metrics": fm.metrics(), "csv": fm.export("csv")} if fm else None,
        "blocked": blocked, "per_process": per, "warnings": warnings,
        "limitation": ("A block does not yet change CPU scheduling; blocked intervals are shown next to the "
                       "Process Manager's own Gantt chart."),
    }, []
