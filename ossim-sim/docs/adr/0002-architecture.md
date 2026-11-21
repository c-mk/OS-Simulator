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


## Milestone 4 update

| Component | Files | Notes |
| --- | --- | --- |
| Security manager | `ossim/managers/security/manager.py` | Role-based users, active sessions, permission checks, alerts, append-only audit records and exports; see `docs/security_manager.md`. |
| Device manager | `ossim/managers/device/` | Disk, printer and keyboard queues; FCFS/Priority and disk FCFS/SSTF/SCAN; failure injection and metrics. |
| Network manager | `ossim/managers/network/` | Nodes, links, packet routing, FIFO/Priority, delay, finite buffers, link failure and metrics. |
| Server routes | `ossim/ui/security_api.py`, `device_api.py`, `network_api.py`, `scenario_api.py`, `__main__.py` | Security, device and network APIs plus `/api/scenario/run` for the early six-manager scenario. |
| Dashboard | `ossim/ui/prototype/index.html` | Six manager workspaces, security audit/alert view, device/network simulations and six-manager event aggregation. |
| Quality and demo | `tests/unit/test_security_manager.py`, `tests/unit/test_security_api.py`, `tests/integration/test_ui_api_m5.py`, `docs/milestone4_demo.md` | Independent manager/API checks and a repeatable demonstration. |

The six-manager endpoint currently aggregates independently executed manager results into a shared ordered event stream. It does not yet implement full controller-mediated blocking or cross-manager authorization enforcement for device/network mutations; see `docs/milestone4_defects.md`.
