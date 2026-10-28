"""Simulation controller: clock, event queue, seed, run state, event log, request router.

Owner: Rasheed. Milestone 2 implementation written with Claude; see README Sourced Tools.

The controller owns time. Managers never read a clock or call each other: they receive one event at a time through
Manager.step(event) and return the new events they want scheduled. Events pop in (time, phase, push order) order, so
same-tick events always run in the order fixed by ADR-0001.
"""
from __future__ import annotations

import heapq
import random
from dataclasses import replace
from typing import Any

from ossim.core.events import PHASES, Event
from ossim.managers.base import Manager

DEFAULT_EVENT_LIMIT = 100_000   # hard stop for runaway runs (spec 3, ADR-0001)

READY, RUNNING, PAUSED, FINISHED, ERROR = "ready", "running", "paused", "finished", "error"


class Controller:
    def __init__(self, seed: int = 0, scenario_id: str = "default", event_limit: int = DEFAULT_EVENT_LIMIT) -> None:
        self.seed = seed
        self.scenario_id = scenario_id
        self.event_limit = event_limit
        self.time = 0
        self.managers: dict[str, Manager] = {}
        self.log: list[Event] = []
        self.state = READY
        self._queue: list[tuple[int, int, int, Event]] = []
        self._push_count = 0
        self._processed = 0
        self._pause_requested = False
        self._started = False

    # ----- setup -----
    def register(self, name: str, manager: Manager) -> None:
        self.managers[name] = manager
        manager.controller = self          # lets a manager cancel its own queued events (e.g. after a preemption)

    def cancel(self, predicate) -> int:
        """Remove queued events for which predicate(event) is true. Returns how many were removed."""
        keep = [item for item in self._queue if not predicate(item[3])]
        removed = len(self._queue) - len(keep)
        heapq.heapify(keep)
        self._queue = keep
        return removed

    def rng(self, manager: str) -> random.Random:
        """Per-manager generator so randomness in one manager never changes another's results (ADR-0001)."""
        return random.Random(f"{self.seed}:{manager}")

    def schedule(self, event: Event) -> None:
        if event.time < self.time:
            raise ValueError(f"event {event.event_type} at {event.time} is in the past (now {self.time})")
        phase = PHASES.index(event.phase)
        heapq.heappush(self._queue, (event.time, phase, self._push_count, event))
        self._push_count += 1

    def reset(self) -> None:
        """Back to time 0 with an empty log. Managers go back to their loaded state and a SIM_START event is queued."""
        self.time = 0
        self.log = []
        self.state = READY
        self._queue = []
        self._push_count = 0
        self._processed = 0
        self._pause_requested = False
        for m in self.managers.values():
            m.reset()
        self.schedule(Event(0, 0, self.scenario_id, "sim", "controller", "SIM_START", "controller", "start", None, None, "ok",
                            message=f"seed {self.seed}", phase="other"))
        self._started = True

    # ----- running -----
    def request(self, pid: str, kind: str, payload: dict) -> str:
        """Route a cross-manager request; returns 'granted', 'blocked' or 'denied'. Needs the other managers (Milestone 3+)."""
        raise NotImplementedError("Milestone 3: cross-manager routing")

    def step(self) -> list[Event]:
        """Process the next queued event. Returns the events added to the log (empty if nothing was queued)."""
        if not self._started:
            self.reset()
        if self.state in (FINISHED, ERROR):
            return []
        if not self._queue:
            self.state = FINISHED
            return []
        if self._processed >= self.event_limit:
            self.state = ERROR
            err = Event(len(self.log) + 1, self.time, self.scenario_id, "sim", "controller", "EVENT_LIMIT", "controller", "stop",
                        None, None, "error", severity="critical", message=f"stopped after {self.event_limit} events")
            self.log.append(err)
            return [err]
        time, _, _, ev = heapq.heappop(self._queue)
        self.time = time
        self._processed += 1
        logged: list[Event] = []
        if ev.action != "internal":                       # internal bookkeeping events are processed but not logged
            ev = replace(ev, seq=len(self.log) + 1)
            self.log.append(ev)
            logged.append(ev)
        targets = list(self.managers.values()) if ev.manager == "controller" else [self.managers[ev.manager]]
        for m in targets:
            for new in m.step(ev):
                self.schedule(new)
        self.state = PAUSED if self._pause_requested else RUNNING
        if not self._queue or self._all_done():
            self.state = FINISHED
            self._queue = []
        return logged

    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        """Step until finished, paused, or a stop condition: {'max_time': ticks, 'max_events': count}. Returns new log entries."""
        stop = stop or {}
        max_time, max_events = stop.get("max_time"), stop.get("max_events")
        start_len = len(self.log)
        self._pause_requested = False
        if self.state == PAUSED:
            self.state = RUNNING
        while self.state not in (FINISHED, ERROR, PAUSED):
            if max_events is not None and len(self.log) - start_len >= max_events:
                break
            if max_time is not None and self._queue and self._queue[0][0] > max_time:
                break
            self.step()
        return self.log[start_len:]

    def pause(self) -> None:
        """Ask a running loop to stop after the current event. The run continues with run() or step()."""
        self._pause_requested = True
        if self.state == RUNNING:
            self.state = PAUSED

    def _all_done(self) -> bool:
        flags = [getattr(m, "is_done", None) for m in self.managers.values()]
        return bool(flags) and all(f is not None and f() for f in flags)

    def snapshot(self) -> dict[str, Any]:
        return {"time": self.time, "state": self.state, "seed": self.seed, "scenario_id": self.scenario_id,
                "events_logged": len(self.log), "events_queued": len(self._queue),
                "managers": {n: m.snapshot() for n, m in self.managers.items()}}
