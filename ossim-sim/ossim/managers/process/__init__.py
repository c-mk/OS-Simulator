"""Process manager: CPU scheduling simulation (spec 4.1). Owner: Copernic.

Milestone 2 implementation written with Claude (see README Sourced Tools). Implements ossim.managers.base.Manager.
Policies: FCFS, SJF, SRTF, Round-Robin (q, cs), Priority (non-preemptive / preemptive, optional aging).
Rules and tie-breakers are documented in docs/tie_breakers.md.
"""
from ossim.managers.process.manager import ProcessManager

__all__ = ["ProcessManager"]
