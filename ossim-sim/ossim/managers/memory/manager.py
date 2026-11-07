"""Memory manager: paging with FIFO or LRU replacement. Owner: Copernic.

Simulated time is integer ticks (1 tick = 0.1 ms), the same as the process manager.
A hit costs `hit_ticks`; a page fault costs `fault_ticks` in total (service included),
so the defaults (1 and 50) are the 0.1 ms and 5.0 ms in expected_results/memory_baseline.json.

Contract notes
  * configure() and load() return a list of error messages (empty = ok) and change nothing on error.
  * load() takes a trace file path (read with ossim.io.loaders.load_trace, so errors read the same
    as every other loader) or a list of addresses / (pid, address) / (pid, address, at_tick).
  * run() is restartable: it rebuilds the timeline from the loaded trace each call, so
    Controller.snapshot() can replay it to any time.
  * step(event) handles one MEM_REF event (see mem_ref()): entity_id = pid, message = address,
    time = the tick the reference is issued. step() with no event takes the next trace reference.
    A reference handled through step(event) is live: it is not part of the trace, so run() forgets it.
  * Events use outcome "ok" (the shared record has no hit/fault outcome); event_type says which
    happened. The unblock event uses the service_done phase so it sorts before the next
    reference's events at the same tick.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ossim.core.events import Event, TICKS_PER_MS
from ossim.io.loaders import InputError, load_trace
from ossim.managers.base import Manager

from .paging import POLICIES, Pager

DEFAULTS = {"page_size": 4096, "frames": 3, "policy": "fifo", "hit_ticks": 1,
            "fault_ticks": 50, "pid": "P1", "seed": 0}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_address(token) -> int:
    """Hex ('0x10A0') or decimal ('4256'). Raises ValueError."""
    if _is_int(token):
        value = token
    else:
        t = str(token).strip()
        value = int(t, 16) if t.lower().startswith("0x") else int(t, 10)
    if value < 0:
        raise ValueError(f"negative address {token}")
    return value


def mem_ref(pid: str, address: int, at: int) -> Event:
    """The event a process emits to reference memory; pass it to MemoryManager.step()."""
    return Event(seq=0, time=at, scenario_id="", correlation_id=pid, manager="process",
                 event_type="MEM_REF", entity_id=pid, action="access", prev_state=None,
                 new_state=None, outcome="ok", message=hex(address), phase="other")


def refs_from_gantt(gantt: list, workloads: dict, interval_ticks: int = 10) -> list:
    """Process-generated references: while a process holds the CPU (a Gantt segment
    {pid, start, end} in ticks) it issues its next address every `interval_ticks`.
    workloads = {pid: [addresses]}. Returns timed refs (pid, address, at_tick) for load().
    A fault does not delay later dispatches: the process manager has already run."""
    cursor = {pid: 0 for pid in workloads}
    refs = []
    for seg in gantt:
        pid = seg["pid"]
        if pid not in workloads:                    # CS, IDLE, or no memory workload
            continue
        t = seg["start"]
        while t < seg["end"] and cursor[pid] < len(workloads[pid]):
            refs.append((pid, parse_address(workloads[pid][cursor[pid]]), t))
            cursor[pid] += 1
            t += interval_ticks
    return refs


class MemoryManager(Manager):
    name = "memory"

    def __init__(self) -> None:
        self.config = dict(DEFAULTS)
        self.trace: list = []
        self.reset()

    # 1. configure 
    def configure(self, config: dict) -> list[str]:
        merged = {**self.config, **config}
        errors = [f"unknown setting {k!r}" for k in config if k not in DEFAULTS]
        if isinstance(merged["policy"], str):
            merged["policy"] = merged["policy"].strip().lower()
        if not _is_int(merged["page_size"]) or merged["page_size"] < 1:
            errors.append("page_size must be a whole number of at least 1")
        if not _is_int(merged["frames"]) or merged["frames"] < 1:
            errors.append("frames must be a whole number of at least 1")
        if merged["policy"] not in POLICIES:
            errors.append(f"policy must be one of {', '.join(POLICIES)}")
        for k in ("hit_ticks", "fault_ticks"):
            if not _is_int(merged[k]) or merged[k] < 0:
                errors.append(f"{k} cannot be negative")
        if errors:
            return errors
        self.config = merged
        self.reset()
        return []

    # 2. load 
    def load(self, data) -> list[str]:
        """data: path to a trace file, or a list of addresses / (pid, address[, at_tick])."""
        refs, errors = [], []
        if isinstance(data, (str, Path)):
            try:
                refs = [(self.config["pid"], a, None) for a in load_trace(data)]
            except (InputError, OSError) as e:
                return [str(e)]
        else:
            for i, item in enumerate(data, 1):
                try:
                    if isinstance(item, (tuple, list)):
                        pid, addr = str(item[0]), parse_address(item[1])
                        at = item[2] if len(item) > 2 else None
                        if at is not None and (not _is_int(at) or at < 0):
                            raise ValueError("bad time")
                    else:
                        pid, addr, at = self.config["pid"], parse_address(item), None
                    refs.append((pid, addr, at))
                except (ValueError, IndexError):
                    errors.append(f"Reference {i}: invalid entry {item!r}")
        if not errors and not refs:
            errors.append("Trace is empty")
        if errors:
            return errors
        self.trace = refs
        self.reset()
        return []

    # 3. reset 
    def reset(self) -> None:
        c = self.config
        self.pager = Pager(c["page_size"], c["frames"], c["policy"])
        self.clock = 0
        self.cursor = 0
        self.seq = 0
        self.events: list = []
        self.history: list = []

    def _emit(self, t, pid, etype, action, prev, new, outcome, cost, message, phase="other") -> None:
        self.seq += 1
        self.events.append(Event(
            seq=self.seq, time=t, scenario_id="", event_type=etype, entity_id=pid, action=action,
            prev_state=prev, new_state=new, outcome=outcome, cost=cost,
            severity="info", message=message, phase=phase,
            manager="memory", correlation_id=pid))

    # 4. step 
    def step(self, event: Event | None = None) -> list[Event]:
        """Handle one reference; return the events it produced.
        With a MEM_REF event: that reference (other event types are ignored, returning []).
        Without: the next reference of the loaded trace (empty list at the end)."""
        if event is not None:
            if event.event_type != "MEM_REF":
                return []
            return self._access(event.entity_id, parse_address(event.message), event.time)
        if self.cursor >= len(self.trace):
            return []
        pid, address, at = self.trace[self.cursor]
        self.cursor += 1
        return self._access(pid, address, at)

    def _access(self, pid, address, at) -> list[Event]:
        c = self.config
        t = self.clock if at is None else max(self.clock, at)
        before = len(self.events)
        r = self.pager.access(pid, address)
        cost = c["hit_ticks"] if r["hit"] else c["fault_ticks"]
        if r["hit"]:
            self._emit(t, pid, "PAGE_HIT", "access", "resident", "resident", "ok", cost,
                       f"page {r['page']} in frame {r['frame']}")
        else:
            self._emit(t, pid, "PAGE_FAULT", "access", "not_resident", "resident", "ok", cost,
                       f"page {r['page']} -> frame {r['frame']}")
            if r["evicted"]:
                vpid, vpage = r["evicted"]
                self._emit(t, vpid, "PAGE_EVICT", c["policy"], "resident", "evicted", "ok", 0,
                           f"page {vpage} out of frame {r['frame']} ({c['policy']})")
            self._emit(t, pid, "BLOCK", "page_fault", "running", "waiting", "ok", 0,
                       f"waiting {cost} ticks for page {r['page']}")
            self._emit(t + cost, pid, "UNBLOCK", "fault_served", "waiting", "ready", "ok", 0,
                       f"page {r['page']} loaded", "service_done")
        self.clock = t + cost
        self.history.append({
            "index": len(self.history) + 1, "time": t, "pid": pid, "address": address,
            "page": r["page"], "offset": r["offset"], "frame": r["frame"], "hit": r["hit"],
            "result": "H" if r["hit"] else "F", "cost": cost,
            "evicted": r["evicted"][1] if r["evicted"] else None,
            "evicted_pid": r["evicted"][0] if r["evicted"] else None,
            "frames_after": self.pager.frames_view()})
        return self.events[before:]

    # 5. run 
    def run(self, stop: dict | None = None) -> list[Event]:
        """Restart and process the trace. stop: max_time (ticks) / max_time_ms / max_events,
        all inclusive limits like the process manager. A reference is never cut in half.
        Returns every event produced."""
        max_time = max_events = None
        if stop:
            if stop.get("max_time") is not None:
                max_time = int(stop["max_time"])
            elif stop.get("max_time_ms") is not None:
                max_time = int(round(float(stop["max_time_ms"]) * TICKS_PER_MS))
            if stop.get("max_events") is not None:
                max_events = int(stop["max_events"])
        self.reset()
        while self.cursor < len(self.trace):
            if max_events is not None and len(self.events) >= max_events:
                break
            at = self.trace[self.cursor][2]
            if max_time is not None and (self.clock if at is None else max(self.clock, at)) > max_time:
                break
            self.step()
        return list(self.events)

    # 6. snapshot 
    def snapshot(self) -> dict:
        return {"policy": self.config["policy"], "clock": self.clock, "config": dict(self.config),
                "frames": self.pager.frames_view(),
                "page_tables": {pid: {str(pg): fr for pg, fr in t.items()}
                                for pid, t in self.pager.tables.items()},
                "references": list(self.history),
                "results": [h["result"] for h in self.history],
                "evicted": [h["evicted"] for h in self.history],
                "processed": self.cursor, "trace_length": len(self.trace)}

    # 7. metrics
    @staticmethod
    def _stats(rows: list) -> dict:
        n = len(rows)
        faults = sum(1 for h in rows if not h["hit"])
        evictions = sum(1 for h in rows if h["evicted"] is not None)
        total = sum(h["cost"] for h in rows)
        return {"references": n, "hits": n - faults, "faults": faults, "evictions": evictions,
                "fault_rate": round(100.0 * faults / n, 2) if n else 0.0,
                "hit_rate": round(100.0 * (n - faults) / n, 2) if n else 0.0,
                "avg_access_time": round(total / n / TICKS_PER_MS, 3) if n else 0.0}

    def metrics(self) -> dict:
        s = self._stats(self.history)
        units = {"references": "count", "hits": "count", "faults": "count", "evictions": "count",
                 "fault_rate": "percent", "hit_rate": "percent", "avg_access_time": "ms"}
        return {k: {"value": s[k], "unit": units[k]} for k in units}

    # 8. validate 
    def validate(self) -> list[str]:
        """Warnings only; configure() and load() report the errors."""
        warnings = []
        if not self.trace:
            warnings.append("No trace loaded")
        else:
            distinct = {(p, a // self.config["page_size"]) for p, a, _ in self.trace}
            if len(distinct) <= self.config["frames"]:
                warnings.append("frames >= distinct pages, so no evictions will occur")
        if self.config["fault_ticks"] < self.config["hit_ticks"]:
            warnings.append("fault_ticks is smaller than hit_ticks")
        return warnings

    # 9. export 
    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            return json.dumps({"snapshot": self.snapshot(), "metrics": self.metrics(),
                               "events": [e.to_dict() for e in self.events]}, indent=2)
        if fmt == "csv":                         # one metrics row per PID
            buf = io.StringIO()
            cols = ["pid", "references", "hits", "faults", "evictions", "fault_rate", "hit_rate", "avg_access_time"]
            w = csv.writer(buf)
            w.writerow(cols)
            for pid in sorted({h["pid"] for h in self.history}):
                s = self._stats([h for h in self.history if h["pid"] == pid])
                w.writerow([pid] + [s[k] for k in cols[1:]])
            return buf.getvalue()
        raise ValueError("export format must be json or csv")