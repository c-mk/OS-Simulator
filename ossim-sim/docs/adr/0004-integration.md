# ADR-0004: Initial integration of the process, memory and file managers

Milestone 3. Code: `ossim/integration.py`, `ossim/ui/integration_api.py`.

## Decision

* The Process Manager runs first and produces the CPU Gantt chart.
* While a process holds the CPU it issues its next memory address every `interval_ticks` (default 10 ticks = 1 ms),
  using `refs_from_gantt` from the memory manager. The Memory Manager answers hit or fault. A fault emits `BLOCK`
  (running to waiting) and, after the fault time, `UNBLOCK` (waiting to ready).
* A process file request names a process, command, arguments and time. The File Manager runs it as the user mapped to
  that process and answers `ok`, `failed` or `denied` by owner/group/other bits. The process is blocked while the
  request is served and ready again afterwards.
* All events are merged in time order (same-tick order follows ADR-0001) and renumbered so the dashboard can show one
  correlated log. Blocked intervals are paired per process and per manager.

## Why

It exercises the shared event record and the `BLOCK`/`UNBLOCK` states with the two managers that exist, without
waiting for the Security, Device and Network managers.

## Consequences (what is not modeled yet)

* A block does not change CPU scheduling: the process Gantt is the Process Manager's own. Feeding blocks back through
  the shared controller is Milestone 4 work.
* Memory references and file requests are independent streams, so one process can show a memory block and a file
  block at the same time. The result carries a warning when that happens.
* Each manager serves one request at a time; a request that arrives during a service waits for it.
* A request issued while its process is not on the CPU is accepted but produces a warning.
