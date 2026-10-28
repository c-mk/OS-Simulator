# Process manager: rules and tie-breakers (spec 4.1, RTM PR-02..PR-10)

Written with Claude (see README, Sourced Tools). These are the rules the engine and the tests follow, so a reviewer can
re-derive any expected value by hand. Times are in ms in this document; the engine stores integer ticks (1 ms = 10 ticks).

## Same-tick order
Events at the same tick run in this phase order (ADR-0001): completion, arrival, quantum expiry, preemption, dispatch.
So when a process finishes at the same instant another arrives, the CPU is handed over with no idle gap, and when a
quantum expires at the same instant a process arrives, the arrival joins the ready queue first.

## Choosing the next process
| Policy | Picks | Ties broken by |
| --- | --- | --- |
| FCFS | earliest arrival | input order |
| SJF (non-preemptive) | smallest total burst | earlier arrival, then input order |
| SRTF | smallest remaining time | earlier arrival, then input order |
| Round-Robin | head of the ready queue (oldest entry) | queue order |
| Priority | lowest priority number (aged value if aging is on) | earlier arrival, then input order |

"Input order" is the row order in the CSV, not alphabetical order of the pid.

## Preemption
- Only SRTF and preemptive Priority preempt. A ready process preempts only if it is strictly better: fewer remaining ms
  (SRTF) or a strictly lower priority number (Priority). Equal never preempts.
- Preemptions are checked whenever something arrives, a process leaves the CPU, or an aging tick happens.
- Round-Robin: when a quantum expires the process goes to the back of the queue, after any arrival at the same tick.
  A process whose remaining time equals the quantum finishes instead of expiring. If the queue is empty the same
  process is dispatched again; that counts as another dispatch, and the Gantt chart shows the back-to-back runs as one bar.
- FCFS, SJF and non-preemptive Priority never take the CPU away from a running process.

## Aging (Priority only)
- Aging ticks happen at every multiple of the aging interval (for example every 2 ms: t = 2, 4, 6, ...), starting at one interval.
- At each tick every process in the ready queue has its priority number lowered by 1, never below 0. The running process
  is not aged. A process that arrives on a tick is aged on that tick too (arrivals run first).
- When a process is dispatched, its priority goes back to its original value, so a boost is used up once the process runs.
  In preemptive mode this means a boosted process can be preempted again by a waiting process that has aged past it.
- Aging 0 means off. With aging off a stream of better processes can starve a low-priority one (see `inputs/starvation.csv`).

## Context switches and the dispatcher
- The CPU spends `cs` ms switching whenever a process is about to start and the previous process to use the CPU was a
  different one. The very first dispatch is free. The switch is charged after an idle gap too.
- During a switch nothing else can be dispatched or preempted; the chosen process is committed. It is still in the ready
  queue, so the switch counts as waiting time for it.
- Context-switch time = switches x cs. It is shown as `CS` segments in the Gantt chart and never counted as useful CPU time.
- cs = 0 means no switch segments at all.

## Metrics
- Turnaround = completion - arrival. Waiting = turnaround - burst. Response = first time on the CPU - arrival.
- Dispatches = number of ready-to-running moves. Preemptions = times a process left the CPU before finishing (quantum
  expiry or a better process).
- Makespan = time the last process completes (measured from t = 0).
- CPU utilization = useful run time / makespan. Idle = time the CPU had nothing to do. Useful + idle + context-switch = makespan.
- Throughput = processes finished per ms. Average queue length is time-weighted (ready queue size x time / makespan).

## Seed
The process manager makes no random choices, so every run with the same input and settings is identical whatever the seed.
The seed is still recorded in the first log event (`SIM_START`) and drives the per-manager generators that later
managers will use.

## Limits and validation
Workloads must be 1 to 1000 processes with integer arrival, burst and priority; arrival >= 0, burst > 0, priority >= 0;
values at most 1,000,000 ms. q must be at least 0.1 ms; q, cs and aging must be multiples of 0.1 ms. A rejected
configuration or workload changes nothing. A run stops with an `EVENT_LIMIT` error after 100,000 events.
