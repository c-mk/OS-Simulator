"""Shared event record (spec 3.1). Owner: Rasheed. Changes need an ADR."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

TICKS_PER_MS = 10  # 1 tick = 0.1 ms (ADR-0001)

Manager = Literal["controller", "process", "memory", "file", "security", "device", "network", "parallel"]
Outcome = Literal["ok", "denied", "failed", "error"]
Severity = Literal["info", "warning", "critical"]

# Same-time processing order (ADR-0001). Lower runs first.
PHASES = ("completion", "service_done", "arrival", "quantum_expiry", "preemption", "dispatch", "other")


@dataclass(frozen=True)
class Event:
    seq: int
    time: int                      # ticks
    scenario_id: str
    correlation_id: str
    manager: Manager
    event_type: str
    entity_id: str
    action: str
    prev_state: str | None
    new_state: str | None
    outcome: Outcome
    cost: int = 0                  # ticks
    severity: Severity = "info"
    message: str = ""
    phase: str = field(default="other", compare=False)

    @property
    def time_ms(self) -> float:
        return self.time / TICKS_PER_MS

    def sort_key(self) -> tuple[int, int, int]:
        return (self.time, PHASES.index(self.phase), self.seq)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time_ms"] = self.time_ms
        return d


REQUIRED_FIELDS = {
    "seq", "time", "scenario_id", "correlation_id", "manager", "event_type", "entity_id",
    "action", "prev_state", "new_state", "outcome", "cost", "severity", "message",
}
