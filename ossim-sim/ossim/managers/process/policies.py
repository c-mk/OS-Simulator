"""CPU scheduling policies (spec 4.1; RTM PR-02..PR-06). Written with Claude; see README Sourced Tools.

Each policy is a rule for picking the next process from the ready list and, for the preemptive ones, for deciding
whether a ready process should take the CPU from the running one. Tie-breakers are in docs/tie_breakers.md.
"""
from __future__ import annotations

from ossim.model.process import Process

POLICIES = ("fcfs", "sjf", "srtf", "rr", "priority")


def pick(policy: str, ready: list[Process]) -> Process:
    """Choose the next process. `ready` is in queue order (oldest entry first); it must not be empty."""
    if policy == "rr":
        return ready[0]                                            # queue order; expired process was appended last
    if policy == "fcfs":
        return min(ready, key=lambda p: (p.arrival, p.order))
    if policy == "sjf":
        return min(ready, key=lambda p: (p.burst, p.arrival, p.order))
    if policy == "srtf":
        return min(ready, key=lambda p: (p.remaining, p.arrival, p.order))
    if policy == "priority":                                       # lower number = higher priority
        return min(ready, key=lambda p: (p.eff_priority, p.arrival, p.order))
    raise ValueError(f"unknown policy {policy!r}")


def preempts(policy: str, preemptive: bool, candidate: Process, running: Process, running_remaining: int) -> bool:
    """True only when `candidate` is strictly better than the running process (equal never preempts)."""
    if policy == "srtf":
        return candidate.remaining < running_remaining
    if policy == "priority" and preemptive:
        return candidate.eff_priority < running.eff_priority
    return False
