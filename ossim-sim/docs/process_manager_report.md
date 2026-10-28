# Process Manager Technical Report

**OS Simulator (CSC301) · Owner: Copernic · Milestone 2 (Week of 27 Oct 2026)**  

**Module:** `ossim.managers.process` · **Interface:** `ossim.managers.base.Manager` (Appendix A)

## 1. Purpose

The process manager is a **safe, deterministic, discrete-event CPU scheduler**.

Implements:

- the process control block (PCB) and the five states **new → ready → running → waiting → terminated** (waiting is reserved for later I/O blocking through the controller)

- six CPU policies required by the baseline: **FCFS, SJF, SRTF, Round-Robin, priority non-preemptive, priority preemptive**

- the nine Appendix A methods listed in `managers/base.py`.

## 2. Time, Records, and Determinism

Simulated time is an **integer tick**.
One tick is 0.1 ms.

Preemption happens when process has shorter remaining time, or a  smaller priority number. 

Every state change is an `Event` with the shared fields (`seq`, `time`, `scenario_id`, `correlation_id`, `manager`, `event_type`, `entity_id`, `action`, `prev_state`, `new_state`, `outcome`). 

The process manager sets `manager="process"` and uses the PID as `correlation_id`.

## 3. Minimum Manager Interface 

1. configure(config) - validate and apply manager specific configuration
2. load(input) - import a workload or scneario asset without mutating unrelated managers.
3. reset() - return to a known initial state
4. step(event/time) - advance deterministically and emit zero or more shared events.
5. run(stop_condition) - advance until completion or the requested limit.
6. snapshot() - return serializable current state for dashboard and test.
7. metrics() return defined measurements with units.
8. validate() report configuration/state errors and warnings.
9. export (fortmat) - produce results and event data in an approved format


## 4. Data model

A PCB (process control block) is a plain object with integer fields only:

```python
class PCB:
    def __init__(self, pid, arrival, burst, priority, order):
        self.pid = pid
        self.arrival = arrival      # arrival in ticks
        self.burst = burst          # burst in ticks ticks
        self.priority = priority    
        self.order = order          
        self.remaining = burst
        self.start = None           
        self.completion = None
        self.dispatches = 0
        self.state = "new"
```

**Run-time structures definitions**

`ready` is a **list of PIDs**
`running` is one PID or `None`, `gantt` is a list of `{pid, start, end}` segments.


## 5. Algorithms

1. **admits** every process with `arrival == t` onto `ready`.
2. **completes** the running process if `remaining == 0`
3. **requeues** a round-robin process if its slice used up `quantum` and work remains (QUANTUM_EXPIRY);
4. **preempts** if a waiting process is strictly better.
5. **dispatches** from `ready` if the CPU is idle.
6. **jumps** `t` to the next interesting time: next arrival, remaining burst, or leftover quantum.

If the CPU is idle, time skips to the next arrival (idle ticks are counted). An optional context-switch cost occupies `[t, t + cs)` with no user process running; arrivals during that interval still join `ready`. Baseline cases use `cs = 0`.

**Types** 

**FCFS.** Runs the head of the arrival list to completion. No preemption.

**SJF.** When the CPU becomes free, choose the ready process with the shortest burst. The running process is never interrupted.

**SRTF.** A new arrival preempts only if its remaining time is **strictly less** than the running process.

**Round-Robin (`quantum_ms`, default 4).**

**Priority (non-preemptive).** When the CPU is free, choose the ready process with the smallest priority number.

**Priority (preemptive, aging off).** Same choice; a new arrival preempts only if its priority number is **strictly smaller**. Aging is not implemented; `validate()` warns if `aging=True`.

**Definitions used for every process:**

- turnaround = completion − arrival  
- waiting = turnaround − burst  
- response = first start − arrival  

## 6. Metrics, snapshot, and export

`metrics()` returns a map `{name: {value, unit}}`:

- `avg_turnaround`, `avg_waiting`, `avg_response`, `makespan`, `idle_time`, `context_switch_time` — **ms**
- `cpu_utilization` — **percent**
- `throughput` — **processes/ms**
- `dispatches`, `process_count`, `completed` — **count**

`snapshot()` is the dashboard contract: policy, clock, PCB table, ready list, Gantt, and averages. `export("json")` wraps snapshot, metrics, and the event log. `export("csv")` writes one metrics row per PID.

## 7. Validation, tests, and safety

Unit test are covered in  `tests/unit/test_process_manager.py`  which cover the nine methods and gantt charts.


## 8. Other notes

---

**Implementation map.** `ossim/managers/process/__init__.py` exports `ProcessManager`.
`manager.py` is the main program. 
`scheduler.py` is the list/loop engine. 

Tests: `tests/unit/test_process_manager.py`.
