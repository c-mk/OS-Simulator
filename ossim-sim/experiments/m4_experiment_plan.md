# Final-month experiment plan — Milestone 4

## Goal

Use repeatable, seeded scenarios to measure security decisions, device scheduling, network routing and the first six-manager event integration. Preserve the earlier Process, Memory and File baselines as regression checks.

## Schedule

| Week | Experiment | Variables | Measurements | Evidence / exit condition |
| --- | --- | --- | --- | --- |
| 1 | Security RBAC and alert threshold | user role, enabled/disabled state, resource, action, failed-login threshold | grants, denials, audit record count, alerts by severity | Unit/API tests prove role grants, active-session requirement, disabled-user rejection and threshold alert. |
| 1 | Device queue comparison | FCFS vs Priority; disk FCFS vs SSTF vs SCAN; head position and cylinder sequence | request completion order, average service time, disk head movement, failures | Same workload is replayed for every policy; metrics and timeline exported to CSV/JSON. |
| 2 | Device failure experiment | failure flag and device type | failure count, completion count, event severity, remaining queue | Inject one failure per device type and verify unaffected requests still complete. |
| 2 | Network routing experiment | link delays, topology shape, failed link | chosen route, hop count, end-to-end delay, delivered/dropped count | Compare normal shortest path with alternate route after link failure. |
| 3 | Network queue/buffer experiment | FIFO vs Priority, buffer capacity, packet arrival times | enqueue order, forwarding delay, drops, delivery rate | Run a simultaneous-arrival case and a constrained-buffer case; preserve scenario inputs and exports. |
| 3 | Six-manager early integration | process workload, memory trace, file requests, security operations, device requests, network packets | per-manager metrics, global event ordering, denied operations, event count | One reproducible run includes all six manager names in the shared event timeline. |
| 4 | Regression and demonstration rehearsal | baseline inputs and all injected-failure cases | test pass count, warnings, reproducibility, export validity | `pytest -q`, `ruff check .`, dashboard walkthrough and defect-list review completed. |

## Controlled procedure

1. Use the checked-in baseline JSON/CSV/text inputs and fixed seeds.
2. Change one independent variable per comparison; keep all other settings unchanged.
3. Run the same scenario at least three times when checking determinism. Identical input must produce identical events and metrics.
4. Export event logs and metrics; record policy, seed, and configuration with each result.
5. Compare output to hand-calculated small cases and the independent unit tests.
6. Record deviations in `docs/milestone4_defects.md`; do not adjust expected values merely to make a test pass.

## Expected observations (hypotheses, not claimed results)

- SSTF should reduce total disk head movement for some workloads but may delay far-away requests.
- Priority queues should change service order when priorities differ.
- A failed network link should cause route selection to use an available alternative or drop a packet when no route remains.
- Smaller link buffers should increase the chance of packet drops under competing arrivals.
- More failed login attempts should increase warning/critical alert records at the configured threshold.
- The six-manager scenario should be deterministic, but manager outputs are aggregated rather than coupled through a fully event-driven controller.

## Deliverables

Scenario inputs, CSV/JSON exports, test results, a short interpretation of trade-offs, and an updated unresolved-defect list.
