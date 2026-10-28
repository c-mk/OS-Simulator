"""Process record and state machine (spec 4.1, RTM PR-07). Written with Claude; see README Sourced Tools.

All times are integer ticks (1 tick = 0.1 ms, ADR-0001).
"""
from __future__ import annotations

from dataclasses import dataclass

NEW, READY, RUNNING, BLOCKED, TERMINATED = "new", "ready", "running", "blocked", "terminated"

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    NEW: frozenset({READY}),
    READY: frozenset({RUNNING}),
    RUNNING: frozenset({READY, BLOCKED, TERMINATED}),
    BLOCKED: frozenset({READY}),
    TERMINATED: frozenset(),
}


class IllegalTransition(ValueError):
    """Raised when a process is asked to make a state change the model does not allow."""


@dataclass
class Process:
    pid: str
    arrival: int
    burst: int
    priority: int
    order: int                       # position in the input file; final tie-breaker
    remaining: int = 0
    state: str = NEW
    eff_priority: int = 0            # priority after aging; reset to `priority` when dispatched
    start: int | None = None         # first time on the CPU
    completion: int | None = None
    dispatches: int = 0
    preemptions: int = 0             # times taken off the CPU before finishing (quantum expiry or better process)
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        self.remaining = self.burst
        self.eff_priority = self.priority

    def transition(self, new_state: str) -> str:
        """Move to new_state and return the previous state; reject illegal moves without changing anything."""
        if new_state not in VALID_TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.pid}: {self.state} -> {new_state} is not allowed")
        prev, self.state = self.state, new_state
        return prev
