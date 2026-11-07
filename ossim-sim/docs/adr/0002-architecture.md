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

## Milestone 3 update

| Component | Files | Notes |
| --- | --- | --- |
| Memory manager | `ossim/managers/memory/` | Paging, FIFO and LRU, page/frame tables, BLOCK/UNBLOCK on a fault |
| File manager | `ossim/managers/file/fs.py`, `manager.py` | Tree, eight commands, permissions, latency, CSV/JSON export; rules in `docs/file_manager.md` |
| Integration | `ossim/integration.py` | Process Gantt to memory references, authorized file requests, merged event log (ADR-0004) |
| Server routes | `ossim/ui/process_api.py`, `memory_api.py`, `file_api.py`, `integration_api.py`, `__main__.py` | `/api/process/*`, `/api/memory/*`, `/api/file/run`, `/api/integration/run` |
| Dashboard | `ossim/ui/prototype/index.html` | Memory, File and Integration pages; Testing center runs memory, file and integration checks |

Data flow for the integration demo: workload CSV -> Process Manager -> Gantt -> `refs_from_gantt` -> Memory Manager;
file requests -> File Manager; the three event lists merge into one log and a blocked-interval list for the dashboard.
