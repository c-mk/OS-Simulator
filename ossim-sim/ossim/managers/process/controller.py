"""Simulation controller: clock, event queue, seed, run state, snapshots, request router.

Managers calculate their event timelines; the controller merges those timelines and
releases events in deterministic order. Subscribers can stream released events to a
UI, log, or websocket without making the controller depend on any transport.
"""
from __future__ import annotations

import heapq
import random
from dataclasses import replace
from typing import Any, Callable

from ossim.core.clock import ms_to_ticks
from ossim.core.events import Event, PHASES, TICKS_PER_MS
from ossim.managers.base import Manager

EventCallback = Callable[[Event], None]


class Controller:
    """Coordinate managers and provide deterministic, live simulation playback."""

    def __init__(self, seed: int = 0, scenario_id: str = "default") -> None:
        self.seed = seed
        self.scenario_id = scenario_id
        self.time = 0
        self.managers: dict[str, Manager] = {}
        self.rng = random.Random(seed)

        self._queue: list[tuple[int, int, int, Event]] = []
        self._events: list[Event] = []
        self._subscribers: list[EventCallback] = []
        self._prepared = False
        self._pause_requested = False
        self._state = "ready"

    @property
    def state(self) -> str:
        """Current run state: ready, running, paused, finished, or error."""
        return self._state

    @property
    def time_ms(self) -> int | float:
        if self.time % TICKS_PER_MS == 0:
            return self.time // TICKS_PER_MS
        return self.time / TICKS_PER_MS

    @property
    def events(self) -> tuple[Event, ...]:
        """Released events, in release order."""
        return tuple(self._events)

    def register(self, name: str, manager: Manager) -> None:
        """Register a manager before playback starts."""
        if self._state == "running":
            raise RuntimeError("cannot register a manager while the controller is running")
        if self._prepared or self._events:
            raise RuntimeError("reset the controller before changing manager registrations")
        if not name or not isinstance(name, str):
            raise ValueError("manager name must be a non-empty string")
        self.managers[name] = manager

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        """Call ``callback(event)`` whenever an event is released.

        Returns a function that removes the subscription. Exceptions from callbacks
        are not hidden: the controller enters the error state and the exception is
        re-raised so a broken live consumer cannot silently corrupt a run.
        """
        if not callable(callback):
            raise TypeError("subscriber must be callable")
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def events_since(self, seq: int = 0) -> list[Event]:
        """Return released events with global sequence numbers greater than ``seq``."""
        return [event for event in self._events if event.seq > seq]

    def request(self, pid: str, kind: str, payload: dict | None = None) -> str:
        """Route a cross-manager request; return granted, blocked, or denied.

        A request kind may be prefixed with its target, for example
        ``"memory.allocate"``. Alternatively, ``payload["manager"]`` can name the
        target. Target managers may expose ``handle_request(pid, kind, payload)``;
        this optional method is separate from the baseline Manager interface.
        """
        data = dict(payload or {})
        target_name = data.pop("manager", None)
        if target_name is None and "." in kind:
            candidate = kind.split(".", 1)[0]
            if candidate in self.managers:
                target_name = candidate
        if target_name not in self.managers:
            return "denied"

        target = self.managers[target_name]
        handler = getattr(target, "handle_request", None)
        if not callable(handler):
            return "denied"
        try:
            outcome = handler(pid, kind, data)
        except (KeyError, TypeError, ValueError):
            return "denied"
        return outcome if outcome in {"granted", "blocked", "denied"} else "denied"

    def step(self) -> Event | None:
        """Release exactly one event and advance the clock to that event's time."""
        if self._state == "error":
            raise RuntimeError("controller is in the error state; reset before continuing")
        if self._state == "running":
            raise RuntimeError("step cannot be called from inside run; use pause instead")
        if self._state == "finished":
            return None

        try:
            self._prepare()
        except Exception:
            self._state = "error"
            raise

        if not self._queue:
            self._state = "finished"
            return None

        self._pause_requested = False
        event = self._release_one()
        self._state = "finished" if not self._queue else "paused"
        return event

    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        """Release events until completion, pause, or an inclusive stop limit.

        Supported stop keys are ``max_time`` (ticks), ``max_time_ms``, and
        ``max_events``. The event limit applies to this call, making it suitable
        for bounded UI updates as well as pause/resume operation.
        """
        if self._state == "error":
            raise RuntimeError("controller is in the error state; reset before continuing")
        if self._state == "finished":
            return []

        max_time, max_events = self._parse_stop(stop)
        try:
            self._prepare()
        except Exception:
            self._state = "error"
            raise

        self._state = "running"
        self._pause_requested = False
        released: list[Event] = []

        while self._queue and not self._pause_requested:
            if max_events is not None and len(released) >= max_events:
                break
            if max_time is not None and self._queue[0][0] > max_time:
                break
            released.append(self._release_one())

        self._state = "finished" if not self._queue else "paused"
        return released

    def pause(self) -> None:
        """Request a pause between events; an event already being released finishes."""
        self._pause_requested = True
        if self._state == "running":
            self._state = "paused"

    def snapshot(self) -> dict[str, Any]:
        """Return serializable controller and manager state at the current clock.

        Managers are replayed to the controller time so their snapshots do not expose
        the end of a precomputed timeline during a paused or stepped run.
        """
        manager_snapshots: dict[str, dict[str, Any]] = {}
        for name, manager in self.managers.items():
            manager.run({"max_time": self.time})
            manager_snapshots[name] = manager.snapshot()
        return {
            "seed": self.seed,
            "scenario_id": self.scenario_id,
            "state": self._state,
            "time": self.time,
            "time_ticks": self.time,
            "time_ms": self.time_ms,
            "event_count": len(self._events),
            "last_seq": self._events[-1].seq if self._events else 0,
            "managers": manager_snapshots,
            "events": [event.to_dict() for event in self._events],
        }

    def reset(self, seed: int | None = None) -> None:
        """Reset playback and all managers, optionally replacing the random seed."""
        if seed is not None:
            self.seed = seed
        self.rng = random.Random(self.seed)
        self.time = 0
        self._queue.clear()
        self._events.clear()
        self._prepared = False
        self._pause_requested = False
        self._state = "ready"
        for manager in self.managers.values():
            manager.reset()

    def _prepare(self) -> None:
        """Collect and globally order manager timelines once per playback cycle."""
        if self._prepared:
            return

        pending: list[tuple[int, int, int, int, int, Event]] = []
        for manager_order, manager in enumerate(self.managers.values()):
            produced = manager.run() or []
            for event_order, event in enumerate(produced):
                if not isinstance(event, Event):
                    raise TypeError("manager.run() must return Event instances")
                if event.phase not in PHASES:
                    raise ValueError(f"unknown event phase {event.phase!r}")
                pending.append(
                    (event.time, PHASES.index(event.phase), event.seq, manager_order, event_order, event)
                )

        # Python's stable sort preserves registration order for otherwise exact ties.
        pending.sort(key=lambda item: item[:5])
        self._queue.clear()
        for seq, item in enumerate(pending, start=1):
            original = item[-1]
            event = replace(original, seq=seq, scenario_id=self.scenario_id)
            heapq.heappush(self._queue, (event.time, PHASES.index(event.phase), event.seq, event))
        self._prepared = True

    def _release_one(self) -> Event:
        _, _, _, event = heapq.heappop(self._queue)
        self.time = event.time
        self._events.append(event)
        try:
            for callback in tuple(self._subscribers):
                callback(event)
        except Exception:
            self._state = "error"
            raise
        return event

    @staticmethod
    def _parse_stop(stop: dict[str, Any] | None) -> tuple[int | None, int | None]:
        if stop is None:
            return None, None
        if not isinstance(stop, dict):
            raise TypeError("stop must be a dictionary or None")

        max_time: int | None = None
        if stop.get("max_time") is not None:
            max_time = int(stop["max_time"])
        elif stop.get("max_time_ms") is not None:
            max_time = ms_to_ticks(float(stop["max_time_ms"]))
        if max_time is not None and max_time < 0:
            raise ValueError("max_time must be non-negative")

        max_events: int | None = None
        if stop.get("max_events") is not None:
            max_events = int(stop["max_events"])
            if max_events < 0:
                raise ValueError("max_events must be non-negative")
        return max_time, max_events
