"""Common manager interface (spec Appendix A). Owner: Rasheed. Every manager subclasses Manager."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ossim.core.events import Event


class Manager(ABC):
    name: str = "manager"

    @abstractmethod
    def configure(self, config: dict[str, Any]) -> list[str]:
        """Validate and apply config. Return error messages; on any error, change nothing."""

    @abstractmethod
    def load(self, data: Any) -> list[str]:
        """Import this manager's own input asset without touching other managers."""

    @abstractmethod
    def reset(self) -> None:
        """Return to the state right after load()."""

    @abstractmethod
    def step(self, event: Event) -> list[Event]:
        """Handle one event at the current time; deterministic."""

    @abstractmethod
    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        """Step until finished or the stop condition (max time / max events) is reached."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable current state for dashboard and tests."""

    @abstractmethod
    def metrics(self) -> dict[str, dict[str, Any]]:
        """{'metric_name': {'value': ..., 'unit': ...}}"""

    @abstractmethod
    def validate(self) -> list[str]:
        """Configuration/state warnings and errors."""

    @abstractmethod
    def export(self, fmt: str = "json") -> str:
        """Results and events as 'json' or 'csv'."""


INTERFACE_METHODS = ("configure", "load", "reset", "step", "run", "snapshot", "metrics", "validate", "export")
