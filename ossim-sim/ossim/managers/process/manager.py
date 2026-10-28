"""ProcessManager: event-driven CPU scheduler. All times inside are integer ticks (1 tick = 0.1 ms)."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from ossim.core.clock import ms_to_ticks
from ossim.core.controller import Controller
from ossim.core.events import REQUIRED_FIELDS, TICKS_PER_MS, Event
from ossim.io.loaders import PID_RE, InputError, load_processes_csv
from ossim.managers.base import Manager
from ossim.managers.process.policies import POLICIES, pick, preempts
from ossim.model.process import READY, RUNNING, TERMINATED, Process

DEFAULT_CONFIG: dict[str, Any] = {"policy": "fcfs", "preemptive": False, "q": 4, "cs": 0, "aging": 0, "seed": 0}
MAX_PROCESSES = 1000
MAX_TIME_MS = 1_000_000          # largest arrival or burst accepted, in ms


def _num_to_ticks(name: str, value: Any, minimum: int) -> tuple[int | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"{name} must be a number"
    try:
        ticks = ms_to_ticks(value)
    except ValueError:
        return None, f"{name} must be a non-negative multiple of 0.1 ms (got {value})"
    if ticks < minimum:
        return None, f"{name} must be at least {minimum / TICKS_PER_MS:g} ms (got {value})"
    return ticks, None


class ProcessManager(Manager):
    name = "process"
    controller: Controller | None = None

    def __init__(self) -> None:
        self.config: dict[str, Any] = dict(DEFAULT_CONFIG)
        self._specs: list[dict[str, int | str]] = []
        self.scenario_id = "default"
        self._init_state()

    # ------------------------------------------------------------------ state
    def _init_state(self) -> None:
        self.procs: dict[str, Process] = {
            s["pid"]: Process(s["pid"], s["arrival"], s["burst"], s["priority"], s["order"]) for s in self._specs}
        self.ready: list[Process] = []
        self.running: Process | None = None
        self.run_start = 0
        self.last_pid: str | None = None
        self.switches = 0
        self.segments: list[dict[str, Any]] = []
        self._pending = False                  # a dispatch/preempt is already scheduled for this tick
        self._done = 0
        self._t = 0
        self._mode, self._mode_since = "idle", 0
        self._acc = {"idle": 0, "run": 0, "switch": 0}
        self._q_area, self._q_last, self._q_max = 0, 0, 0

    @property
    def _policy(self) -> str:
        return self.config["policy"]

    @property
    def _cs(self) -> int:
        return ms_to_ticks(self.config["cs"])

    @property
    def _quantum(self) -> int:
        return ms_to_ticks(self.config["q"])

    @property
    def _aging(self) -> int:
        return ms_to_ticks(self.config["aging"])

    # --------------------------------------------------------------- Manager API
    def configure(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        unknown = sorted(set(config) - set(DEFAULT_CONFIG))
        if unknown:
            errors.append(f"unknown setting(s): {', '.join(unknown)}")
        new = {**self.config, **{k: v for k, v in config.items() if k in DEFAULT_CONFIG}}
        if new["policy"] not in POLICIES:
            errors.append(f"policy must be one of {', '.join(POLICIES)} (got {new['policy']!r})")
        if not isinstance(new["preemptive"], bool):
            errors.append("preemptive must be true or false")
        _, e = _num_to_ticks("q", new["q"], 1)
        errors += [e] if e else []
        _, e = _num_to_ticks("cs", new["cs"], 0)
        errors += [e] if e else []
        _, e = _num_to_ticks("aging", new["aging"], 0)
        errors += [e] if e else []
        if isinstance(new["seed"], bool) or not isinstance(new["seed"], int):
            errors.append("seed must be an integer")
        if errors:
            return errors                      # nothing changed
        self.config = new
        self.reset()
        return []

    def load(self, data: Any) -> list[str]:
        if isinstance(data, (str, Path)):
            try:
                data = load_processes_csv(data)
            except (InputError, OSError) as e:
                return [str(e)]
        if not isinstance(data, list) or not data:
            return ["workload must be a non-empty list of processes"]
        if len(data) > MAX_PROCESSES:
            return [f"at most {MAX_PROCESSES} processes are supported (got {len(data)})"]
        errors, specs, seen = [], [], set()
        for i, row in enumerate(data):
            where = f"process {i + 1}"
            if not isinstance(row, dict) or not {"pid", "arrival", "burst", "priority"} <= set(row):
                errors.append(f"{where}: needs pid, arrival, burst and priority")
                continue
            pid = row["pid"]
            if not isinstance(pid, str) or not PID_RE.match(pid):
                errors.append(f"{where}: invalid pid {pid!r}")
                continue
            if pid in seen:
                errors.append(f"{where}: duplicate pid {pid}")
                continue
            seen.add(pid)
            vals = [row["arrival"], row["burst"], row["priority"]]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in vals):
                errors.append(f"{pid}: arrival, burst and priority must be integers")
                continue
            arrival, burst, prio = vals
            if arrival < 0 or burst <= 0 or prio < 0:
                errors.append(f"{pid}: arrival >= 0, burst > 0, priority >= 0 required")
                continue
            if arrival > MAX_TIME_MS or burst > MAX_TIME_MS:
                errors.append(f"{pid}: arrival and burst must be at most {MAX_TIME_MS} ms")
                continue
            specs.append({"pid": pid, "arrival": ms_to_ticks(arrival), "burst": ms_to_ticks(burst), "priority": prio,
                          "order": int(row.get("order", i))})
        if errors:
            return errors                      # nothing changed
        self._specs = specs
        self.reset()
        return []

    def reset(self) -> None:
        self._init_state()

    def step(self, event: Event) -> list[Event]:
        self._t = event.time
        handler = getattr(self, "_on_" + event.event_type.lower(), None)
        return handler(event) if handler else []

    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        """Run this manager on its own controller (used by unit tests and the dashboard server)."""
        if self.controller is None:
            ctl = Controller(seed=self.config["seed"], scenario_id=self.scenario_id)
            ctl.register(self.name, self)
            ctl.reset()
        return self.controller.run(stop)

    def is_done(self) -> bool:
        return self._done == len(self.procs)

    def snapshot(self) -> dict[str, Any]:
        s = self._summary()
        return {"policy": self._policy, "config": dict(self.config), "time": self._t, "finished": self.is_done() and bool(self.procs),
                "running": self.running.pid if self.running else None, "ready": [p.pid for p in self.ready],
                "cpu_mode": self._mode, "states": {p.pid: p.state for p in self.procs.values()}, **s}

    def metrics(self) -> dict[str, dict[str, Any]]:
        s = self._summary()
        a = s["averages"]
        ms = lambda v: None if v is None else v / TICKS_PER_MS   # noqa: E731
        return {
            "avg_turnaround": {"value": ms(a["turnaround"]), "unit": "ms"},
            "avg_waiting": {"value": ms(a["waiting"]), "unit": "ms"},
            "avg_response": {"value": ms(a["response"]), "unit": "ms"},
            "makespan": {"value": ms(s["makespan"]), "unit": "ms"},
            "cpu_utilization": {"value": s["cpu_utilization_pct"], "unit": "%"},
            "idle_time": {"value": ms(s["idle"]), "unit": "ms"},
            "context_switch_time": {"value": ms(s["context_switch_time"]), "unit": "ms"},
            "context_switches": {"value": s["switches"], "unit": "count"},
            "throughput": {"value": s["throughput_per_ms"], "unit": "processes/ms"},
            "avg_queue_length": {"value": s["avg_queue_length"], "unit": "processes"},
            "max_queue_length": {"value": s["max_queue_length"], "unit": "processes"},
            "processes_finished": {"value": s["finished_count"], "unit": "count"},
        }

    def validate(self) -> list[str]:
        out = []
        if not self.procs:
            out.append("error: no workload loaded")
        if self._policy != "priority" and self.config["aging"] > 0:
            out.append("warning: aging only applies to the priority policy and is ignored")
        if self._policy != "rr":
            out.append("info: quantum q is only used by round-robin")
        if self._policy == "priority" and not self.config["preemptive"]:
            out.append("info: priority is non-preemptive; aging can still change the pick")
        if self._policy == "priority" and self.config["aging"] == 0:
            out.append("warning: aging is off, so low-priority processes can starve")
        return out

    def export(self, fmt: str = "json") -> str:
        events = list(self.controller.log) if self.controller else []
        if fmt == "json":
            return json.dumps({"config": self.config, "snapshot": self.snapshot(), "events": [e.to_dict() for e in events]}, indent=2)
        if fmt == "csv":
            cols = ["seq", "time", "time_ms"] + sorted(REQUIRED_FIELDS - {"seq", "time"})
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for e in events:
                w.writerow({c: e.to_dict()[c] for c in cols})
            return buf.getvalue()
        raise ValueError(f"unknown export format {fmt!r}; use 'json' or 'csv'")

    # ------------------------------------------------------------ event helpers
    def _ev(self, time: int, phase: str, etype: str, entity: str, action: str, prev: str | None, new: str | None,
            msg: str = "", cost: int = 0, corr: str = "") -> Event:
        return Event(0, time, self.scenario_id, corr or entity, "process", etype, entity, action, prev, new, "ok",
                     cost=cost, message=msg, phase=phase)

    def _decide(self, t: int) -> Event:
        return self._ev(t, "dispatch", "DECIDE", "cpu", "internal", None, None, corr="cpu-decide")

    def _set_mode(self, t: int, mode: str) -> None:
        self._acc[self._mode] += t - self._mode_since
        self._mode, self._mode_since = mode, t

    def _qmark(self, t: int) -> None:
        self._q_area += len(self.ready) * (t - self._q_last)
        self._q_last = t

    def _close_run(self, t: int) -> Process:
        p = self.running
        if p is None:
            raise RuntimeError("no running process to take off the CPU")
        p.remaining -= t - self.run_start
        seg = self.segments[-1] if self.segments else None
        if seg and seg["pid"] == p.pid and seg["end"] == self.run_start:
            seg["end"] = t                      # keep back-to-back runs of one process as a single bar
        else:
            self.segments.append({"pid": p.pid, "start": self.run_start, "end": t})
        self.running = None
        self._set_mode(t, "idle")
        return p

    def _needs_switch(self, cand: Process) -> bool:
        return self._cs > 0 and self.last_pid is not None and self.last_pid != cand.pid

    def _dispatch_event(self, t: int, p: Process, *, switch: bool) -> Event:
        if switch:
            return self._ev(t, "dispatch", "CONTEXT_SWITCH", p.pid, "switch", READY, READY, cost=self._cs, corr=f"{p.pid}-cs",
                            msg=f"CPU switches from {self.last_pid} to {p.pid} ({self._cs / TICKS_PER_MS:g} ms)")
        return self._ev(t, "dispatch", "DISPATCH", p.pid, "dispatch", READY, RUNNING, corr=f"{p.pid}-run-{p.dispatches + 1}",
                        msg=f"{p.pid} starts on the CPU ({p.remaining / TICKS_PER_MS:g} ms left)")

    # ------------------------------------------------------------ event handlers
    def _on_sim_start(self, event: Event) -> list[Event]:
        self.scenario_id = event.scenario_id
        out = [self._ev(p.arrival, "arrival", "ARRIVE", p.pid, "arrive", "new", READY, corr=f"{p.pid}-arrive",
                        msg=f"{p.pid} arrives (burst {p.burst / TICKS_PER_MS:g} ms, priority {p.priority})")
               for p in sorted(self.procs.values(), key=lambda q: (q.arrival, q.order))]
        if self._policy == "priority" and self._aging > 0 and self.procs:
            out.append(self._ev(self._aging, "preemption", "AGE_TICK", "cpu", "internal", None, None, corr="cpu-age"))
        return out

    def _on_arrive(self, event: Event) -> list[Event]:
        p = self.procs[event.entity_id]
        self._qmark(event.time)
        p.transition(READY)
        self.ready.append(p)
        self._q_max = max(self._q_max, len(self.ready))
        return [self._decide(event.time)]

    def _on_decide(self, event: Event) -> list[Event]:
        t = event.time
        if self._pending or self._mode == "switch" or not self.ready:
            return []
        cand = pick(self._policy, self.ready)
        if self.running is None:
            self._pending = True
            return [self._dispatch_event(t, cand, switch=self._needs_switch(cand))]
        remaining_now = self.running.remaining - (t - self.run_start)
        if preempts(self._policy, self.config["preemptive"], cand, self.running, remaining_now):
            self._pending = True
            token = f"{self.running.pid}-run-{self.running.dispatches}"
            return [self._ev(t, "preemption", "PREEMPT", self.running.pid, "preempt", RUNNING, READY, corr=token,
                             msg=f"{self.running.pid} preempted by {cand.pid}")]
        return []

    def _on_context_switch(self, event: Event) -> list[Event]:
        t, p = event.time, self.procs[event.entity_id]
        self._set_mode(t, "switch")
        self.segments.append({"pid": "CS", "start": t, "end": t + self._cs})
        return [self._ev(t + self._cs, "dispatch", "DISPATCH", p.pid, "dispatch", READY, RUNNING, corr=f"{p.pid}-run-{p.dispatches + 1}",
                         msg=f"{p.pid} starts on the CPU ({p.remaining / TICKS_PER_MS:g} ms left)")]

    def _on_dispatch(self, event: Event) -> list[Event]:
        t, p = event.time, self.procs[event.entity_id]
        self._qmark(t)
        self.ready.remove(p)
        p.transition(RUNNING)
        p.dispatches += 1
        if p.start is None:
            p.start = t
        p.eff_priority = p.priority              # any aging boost is used up once the process runs
        if self.last_pid is not None and self.last_pid != p.pid:
            self.switches += 1
        self.last_pid = p.pid
        self._set_mode(t, "run")
        self.running, self.run_start = p, t
        self._pending = False
        if self._policy == "rr" and self._quantum < p.remaining:
            return [self._ev(t + self._quantum, "quantum_expiry", "QUANTUM_EXPIRE", p.pid, "quantum_expire", RUNNING, READY,
                             corr=event.correlation_id, msg=f"{p.pid} used its {self._quantum / TICKS_PER_MS:g} ms quantum")]
        return [self._ev(t + p.remaining, "completion", "COMPLETE", p.pid, "complete", RUNNING, TERMINATED, corr=event.correlation_id,
                         msg=f"{p.pid} finishes")]

    def _on_complete(self, event: Event) -> list[Event]:
        p = self._close_run(event.time)
        if p.remaining != 0:
            raise RuntimeError(f"{p.pid} completed with {p.remaining} ticks left")
        p.transition(TERMINATED)
        p.completion = event.time
        self._done += 1
        return [self._decide(event.time)]

    def _on_quantum_expire(self, event: Event) -> list[Event]:
        return self._leave_cpu(event)

    def _on_preempt(self, event: Event) -> list[Event]:
        self._pending = False
        if self.controller is not None:           # the old COMPLETE / QUANTUM_EXPIRE for this run no longer applies
            self.controller.cancel(lambda e: e.correlation_id == event.correlation_id and e.event_type in ("COMPLETE", "QUANTUM_EXPIRE"))
        return self._leave_cpu(event)

    def _leave_cpu(self, event: Event) -> list[Event]:
        p = self._close_run(event.time)
        self._qmark(event.time)
        p.transition(READY)
        p.preemptions += 1
        self.ready.append(p)                      # after any same-tick arrivals, which ran in an earlier phase
        self._q_max = max(self._q_max, len(self.ready))
        return [self._decide(event.time)]

    def _on_age_tick(self, event: Event) -> list[Event]:
        t = event.time
        out = [self._ev(t, "preemption", "PRIORITY_AGED", p.pid, "age", READY, READY, corr=f"{p.pid}-age",
                        msg=f"{p.pid} priority {p.eff_priority} -> {p.eff_priority - 1}")
               for p in self.ready if p.eff_priority > 0]
        if self._done < len(self.procs):
            out.append(self._ev(t + self._aging, "preemption", "AGE_TICK", "cpu", "internal", None, None, corr="cpu-age"))
        out.append(self._decide(t))
        return out

    def _on_priority_aged(self, event: Event) -> list[Event]:
        p = self.procs[event.entity_id]
        p.eff_priority = max(0, p.eff_priority - 1)
        return []

    # ------------------------------------------------------------------ results
    def _summary(self) -> dict[str, Any]:
        finished = [p for p in self.procs.values() if p.completion is not None]
        all_done = bool(self.procs) and len(finished) == len(self.procs)
        end = max(p.completion for p in finished) if all_done else self._t
        acc = dict(self._acc)
        acc[self._mode] += max(0, end - self._mode_since)
        q_area = self._q_area + len(self.ready) * max(0, end - self._q_last)
        per = {}
        for p in self.procs.values():
            done = p.completion is not None
            tat = p.completion - p.arrival if done else None
            per[p.pid] = {"start": p.start, "completion": p.completion, "turnaround": tat,
                          "waiting": tat - p.burst if done else None,
                          "response": p.start - p.arrival if p.start is not None else None,
                          "dispatches": p.dispatches, "preemptions": p.preemptions, "final_state": p.state}
        def avg(key: str) -> float | None:
            vals = [m[key] for m in per.values() if m[key] is not None]
            return sum(vals) / len(vals) if vals else None
        gantt, cursor = [], 0
        for seg in self.segments:                 # make idle time visible as its own segment
            if seg["start"] > cursor:
                gantt.append({"pid": "IDLE", "start": cursor, "end": seg["start"]})
            gantt.append(dict(seg))
            cursor = seg["end"]
        return {"gantt": gantt, "per_process": per,
                "averages": {"turnaround": avg("turnaround"), "waiting": avg("waiting"), "response": avg("response")},
                "makespan": end, "cpu_utilization_pct": 100.0 * acc["run"] / end if end else 0.0,
                "idle": acc["idle"], "context_switch_time": acc["switch"], "switches": self.switches,
                "throughput_per_ms": len(finished) / end * TICKS_PER_MS if end else 0.0,
                "avg_queue_length": q_area / end if end else 0.0, "max_queue_length": self._q_max,
                "finished_count": len(finished)}
