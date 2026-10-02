# ADR-0002: Central controller with a common manager interface

Status: Proposed (Milestone 1) · Owner: Rasheed

## Decision
Managers never call each other. The controller owns the clock and event queue and routes cross-manager requests
(memory, file, device, network). Security.authorize() runs before any file, device or network state change. Every
manager implements the nine Appendix A methods in managers/base.py and emits the shared Event record.

## Why
Each manager can be unit-tested alone and swapped without touching others; integrated runs are reproducible because
only the controller orders events.

## Consequences
Cross-manager features (blocking, cleanup) are integration work owned by Rasheed, scheduled for Week 9.
