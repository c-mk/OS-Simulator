"""Simulation controller: clock, event queue, seed, run state, snapshots, request router.

Owner: Rasheed. Interface only for Milestone 1; implementation is Milestone 2 work (backlog S2-01..S2-05).
"""
from __future__ import annotations

from ossim.managers.base import Manager


class Controller:
    def __init__(self, seed: int = 0, scenario_id: str = "default") -> None:
        self.seed = seed
        self.scenario_id = scenario_id
        self.time = 0
        self.managers: dict[str, Manager] = {}

    def register(self, name: str, manager: Manager) -> None:
        self.managers[name] = manager

    def request(self, pid: str, kind: str, payload: dict) -> str:
        """Route a cross-manager request; returns 'granted', 'blocked' or 'denied'."""
        raise NotImplementedError("Milestone 2")

    def step(self):
        raise NotImplementedError("Milestone 2")

    def run(self, stop=None):
        raise NotImplementedError("Milestone 2")
