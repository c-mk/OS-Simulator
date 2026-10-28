"""Process manager implementation. Owner: Copernic. Spec 4.1 / Appendix A."""

# imports
from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


from ossim.core.clock import ms_to_ticks
from ossim.core.events import Event
from ossim.io.loaders import InputError, load_processes_csv
from ossim.managers.base import Manager
from ossim.managers.process.scheduler import POLICIES, resolve_policy, result_in_ms, schedule, ticks_to_ms

DEFAULT_CONFIG = {
    "policy": "fcfs",
    "quantum_ms": 4,
    "context_switch_ms": 0,
    "aging": False,
    "aging_interval_ms": 1,
    "scenario_id": "default",
}


# class implementation
class ProcessManager(Manager):
    """CPU scheduler."""

    name = "process"

    #constructor
    def __init__(self) -> None:
        self._config: dict[str, Any] = dict(DEFAULT_CONFIG)
        self._loaded: list[dict[str, Any]] = []
        self._result: dict[str, Any] | None = None
        self._events: list[Event] = []
        self._time = 0
        self._seq = 0

    #methods
    def configure(self, config: dict[str, Any]) -> list[str]:
        errors = self._check_config(config)
        if errors:
            return errors
        new = dict(self._config)
        new.update(config)
        new["policy"] = resolve_policy(str(new["policy"]))
        aging = new.get("aging", False)
        if isinstance(aging, str):
            aging = aging.strip().lower() in {"1", "true", "yes", "on"}
        new["aging"] = bool(aging)
        self._config = new
        self._clear_run()
        return []

    def load(self, data: Any) -> list[str]:
        errors, rows = self._parse_load(data)
        if errors:
            return errors
        self._loaded = rows
        self._clear_run()
        return []

    def reset(self) -> None:
        self._clear_run()

    def step(self, event: Event) -> list[Event]:
        if not self._loaded:
            return []
        if event.event_type in {"RUN", "ADVANCE", "TICK"}:
            return self.run({"max_time": event.time} if event.time else None)
        self._time = event.time
        self._seq = max(self._seq, event.seq)
        return []

    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        if not self._loaded:
            return []
        policy = resolve_policy(str(self._config["policy"]))
        quantum = ms_to_ticks(float(self._config["quantum_ms"]))
        cs = ms_to_ticks(float(self._config["context_switch_ms"]))
        age_iv = ms_to_ticks(float(self._config.get("aging_interval_ms", 1)))
        tick_rows = []
        for row in self._loaded:
            tick_rows.append({
                "pid": row["pid"],
                "arrival": ms_to_ticks(row["arrival"]),
                "burst": ms_to_ticks(row["burst"]),
                "priority": row["priority"],
                "order": row["order"],
            })

        raw = schedule(
            tick_rows,
            policy,
            quantum,
            cs,
            stop,
            aging=bool(self._config.get("aging", False)),
            aging_interval_ticks=age_iv,
        )

        self._result = raw
        self._time = raw["time"]
        scenario = str(self._config.get("scenario_id", "default"))
        self._events = []
        for rec in raw["events"]:
            ev = Event(
                seq=rec["seq"],
                time=rec["time"],
                scenario_id=scenario,
                correlation_id=rec["entity_id"],
                manager="process",
                event_type=rec["event_type"],
                entity_id=rec["entity_id"],
                action=rec["action"],
                prev_state=rec["prev_state"],
                new_state=rec["new_state"],
                outcome=rec["outcome"],
                cost=rec["cost"],
                severity=rec["severity"],
                message=rec["message"],
                phase=rec["phase"],
            )

            self._events.append(ev)
        self._seq = len(self._events)
        return list(self._events)

    def snapshot(self) -> dict[str, Any]:

        ms = result_in_ms(self._result) if self._result else None
        processes = []
        for row in self._loaded:
            extra = {}
            if self._result:
                extra = self._result["per_process"].get(row["pid"], {})
            processes.append({
                "pid": row["pid"],
                "arrival_ms": row["arrival"],
                "burst_ms": row["burst"],
                "priority": row["priority"],
                "order": row["order"],
                "state": extra.get("state", "new"),
                "remaining_ticks": extra.get("remaining"),
            })

        return {
            "manager": self.name,
            "policy": resolve_policy(str(self._config["policy"])),
            "quantum_ms": self._config["quantum_ms"],
            "context_switch_ms": self._config["context_switch_ms"],
            "aging": self._config["aging"],
            "aging_interval_ms": self._config.get("aging_interval_ms", 1),
            "scenario_id": self._config.get("scenario_id", "default"),
            "time_ticks": self._time,
            "time_ms": ticks_to_ms(self._time),
            "loaded": deepcopy(self._loaded),
            "processes": processes,
            "ready": list(self._result["ready"]) if self._result else [],
            "running": self._result["running"] if self._result else None,
            "gantt": ms["gantt"] if ms else [],
            "per_process": ms["per_process"] if ms else {},
            "averages": ms["averages"] if ms else {},
            "makespan": ms["makespan"] if ms else 0,
            "idle": ms["idle"] if ms else 0,
            "cpu_utilization_pct": ms["cpu_utilization_pct"] if ms else 0,
            "context_switch_time": ms["context_switch_time"] if ms else 0,
            "event_count": len(self._events),
        }

    def metrics(self) -> dict[str, dict[str, Any]]:

        snap = self.snapshot()
        avg = snap.get("averages") or {}
        n = len(self._loaded)
        finished = 0
        if self._result:
            finished = sum(1 for m in self._result["per_process"].values() if m["completion"] is not None)
        makespan_ms = snap["makespan"] or 0
        throughput = (finished / makespan_ms) if makespan_ms else 0
        return {
            "avg_turnaround": {"value": avg.get("turnaround", 0), "unit": "ms"},
            "avg_waiting": {"value": avg.get("waiting", 0), "unit": "ms"},
            "avg_response": {"value": avg.get("response", 0), "unit": "ms"},
            "makespan": {"value": snap["makespan"], "unit": "ms"},
            "cpu_utilization": {"value": snap["cpu_utilization_pct"], "unit": "percent"},
            "idle_time": {"value": snap["idle"], "unit": "ms"},
            "context_switch_time": {"value": snap["context_switch_time"], "unit": "ms"},
            "throughput": {"value": throughput, "unit": "processes/ms"},
            "dispatches": {
                "value": sum((self._result["per_process"][p["pid"]]["dispatches"] if self._result else 0) for p in self._loaded),
                "unit": "count",
            },
            "process_count": {"value": n, "unit": "count"},
            "completed": {"value": finished, "unit": "count"},
        }

    def validate(self) -> list[str]:

        msgs: list[str] = []
        msgs.extend(self._check_config(self._config))
        if not self._loaded:
            msgs.append("warning: no processes loaded")
        seen = set()
        for i, row in enumerate(self._loaded):
            pid = row.get("pid")
            if pid in seen:
                msgs.append(f"error: duplicate pid {pid}")
            seen.add(pid)
            if row.get("arrival", 0) < 0:
                msgs.append(f"error: process {pid} arrival must be >= 0")
            if row.get("burst", 0) <= 0:
                msgs.append(f"error: process {pid} burst must be > 0")
            if row.get("priority", 0) < 0:
                msgs.append(f"error: process {pid} priority must be >= 0")
            if i != row.get("order", i):
                msgs.append(f"warning: process {pid} order {row.get('order')} does not match input position {i}")
        if self._config.get("aging"):
            msgs.append("warning: aging is not implemented; priority stays fixed")
        if resolve_policy(str(self._config["policy"])) == "rr" and float(self._config["quantum_ms"]) <= 0:
            msgs.append("error: round-robin quantum_ms must be > 0")
        return msgs

    def export(self, fmt: str = "json") -> str:

        kind = fmt.lower().strip()
        snap = self.snapshot()
        mets = self.metrics()
        if kind == "json":
            payload = {
                "snapshot": snap,
                "metrics": mets,
                "events": [e.to_dict() for e in self._events],
            }
            return json.dumps(payload, indent=2)
        if kind == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "pid", "arrival_ms", "burst_ms", "priority", "start_ms",
                "completion_ms", "turnaround_ms", "waiting_ms", "response_ms", "dispatches",
            ])
            per = snap["per_process"]
            for row in self._loaded:
                m = per.get(row["pid"], {})
                writer.writerow([
                    row["pid"], row["arrival"], row["burst"], row["priority"],
                    m.get("start"), m.get("completion"), m.get("turnaround"),
                    m.get("waiting"), m.get("response"), m.get("dispatches"),
                ])
            return buf.getvalue()
        raise ValueError("export format must be 'json' or 'csv'")

    def _clear_run(self) -> None:

        self._result = None
        self._events = []
        self._time = 0
        self._seq = 0

    def _check_config(self, config: dict[str, Any]) -> list[str]:

        errors: list[str] = []
        if not isinstance(config, dict):
            return ["error: config must be a dictionary"]
        if "policy" in config:
            policy = resolve_policy(str(config["policy"]))
            if policy not in POLICIES:
                errors.append(f"error: unknown policy {config['policy']!r}; expected one of {', '.join(POLICIES)}")
        for key in ("quantum_ms", "context_switch_ms"):
            if key not in config:
                continue
            try:
                value = float(config[key])
            except (TypeError, ValueError):
                errors.append(f"error: {key} must be a number")
                continue
            if value < 0:
                errors.append(f"error: {key} must be >= 0")
                continue
            try:
                ms_to_ticks(value)
            except ValueError as exc:
                errors.append(f"error: {key}: {exc}")
        if "quantum_ms" in config:
            try:
                if float(config["quantum_ms"]) <= 0 and resolve_policy(str(config.get("policy", self._config["policy"]))) == "rr":
                    errors.append("error: quantum_ms must be > 0 for round-robin")
            except (TypeError, ValueError):
                pass
        return errors

    def _parse_load(self, data: Any) -> tuple[list[str], list[dict[str, Any]]]:

        if data is None:
            return ["error: load input is empty"], []
        if isinstance(data, (str, Path)):
            try:
                rows = load_processes_csv(data)
            except (OSError, InputError, ValueError) as exc:
                return [f"error: {exc}"], []
            return [], rows
        if isinstance(data, dict) and "processes" in data:
            data = data["processes"]
        if not isinstance(data, list):
            return ["error: load input must be a CSV path or a list of process records"], []
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, raw in enumerate(data):
            if not isinstance(raw, dict):
                return [f"error: process {i} is not a record"], []
            pid = str(raw.get("pid", "")).strip()
            if not pid:
                return [f"error: process {i} missing pid"], []
            if pid in seen:
                return [f"error: duplicate pid {pid}"], []
            try:
                arrival = int(raw["arrival"])
                burst = int(raw["burst"])
                priority = int(raw.get("priority", 0))
            except (KeyError, TypeError, ValueError):
                return [f"error: process {pid} needs integer arrival, burst, priority"], []
            if arrival < 0 or burst <= 0 or priority < 0:
                return [f"error: process {pid}: arrival >= 0, burst > 0, priority >= 0 required"], []
            seen.add(pid)
            rows.append({"pid": pid, "arrival": arrival, "burst": burst, "priority": priority, "order": int(raw.get("order", len(rows)))})
        if not rows:
            return ["error: no processes"], []
        return [], rows
