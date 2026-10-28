"""CPU scheduling. Owner: Copernic.

Data structures: lists, dicts, and loops only.
Simulated time is integer ticks
(1 tick = 0.1 ms). Policies: fcfs, sjf, srtf, rr, priority_np, priority_p.
"""
from __future__ import annotations

from ossim.core.events import TICKS_PER_MS

POLICIES = ("fcfs", "sjf", "srtf", "rr", "priority_np", "priority_p")

POLICY_ALIASES = {
    "rr_q4": "rr",
    "priority_p_no_aging": "priority_p",
    "round_robin": "rr",
}

PREEMPTIVE = {"srtf", "priority_p"}


class PCB:

    def __init__(self, pid: str, arrival: int, burst: int, priority: int, order: int) -> None:
        self.pid = pid
        self.arrival = arrival
        self.burst = burst
        self.priority = priority
        self.order = order
        self.remaining = burst
        self.start = None
        self.completion = None
        self.dispatches = 0
        self.state = "new"
        self.wait_ticks = 0

    def copy(self) -> PCB:
        return PCB(self.pid, self.arrival, self.burst, self.priority, self.order)

    def effective_priority(self, aging: bool, interval: int) -> int:
        if not aging or interval <= 0:
            return self.priority
        return max(0, self.priority - (self.wait_ticks // interval))


def ticks_to_ms(ticks: int) -> int | float:

    if ticks % TICKS_PER_MS == 0:
        return ticks // TICKS_PER_MS
    return ticks / TICKS_PER_MS


def resolve_policy(name: str) -> str:
    key = name.strip().lower()
    return POLICY_ALIASES.get(key, key)


def pick_ready(
    ready: list[str],
    pcbs: dict[str, PCB],
    policy: str,
    aging: bool = False,
    aging_interval: int = 0,
) -> str | None:
    if not ready:
        return None
    if policy in ("fcfs", "rr"):
        return ready[0]
    best = ready[0]
    for pid in ready[1:]:
        if _better_for_pick(pcbs[pid], pcbs[best], policy, aging, aging_interval):
            best = pid
    return best


def _prio(p: PCB, aging: bool, interval: int) -> int:
    return p.effective_priority(aging, interval)


def _better_for_pick(a: PCB, b: PCB, policy: str, aging: bool = False, interval: int = 0) -> bool:
    if policy in ("sjf", "srtf"):
        if a.remaining != b.remaining:
            return a.remaining < b.remaining
    elif policy in ("priority_np", "priority_p"):
        pa, pb = _prio(a, aging, interval), _prio(b, aging, interval)
        if pa != pb:
            return pa < pb  # lower number = higher priority
    if a.arrival != b.arrival:
        return a.arrival < b.arrival
    return a.order < b.order


def _strictly_better_running(
    cand: PCB, current: PCB, policy: str, aging: bool = False, interval: int = 0
) -> bool:

    if policy == "srtf":
        return cand.remaining < current.remaining
    if policy == "priority_p":
        return _prio(cand, aging, interval) < _prio(current, aging, interval)
    return False


def _next_time(*values: int | None) -> int | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return min(present)


def schedule(
    processes: list[dict],
    policy: str,
    quantum_ticks: int,
    cs_ticks: int,
    stop: dict | None = None,
    aging: bool = False,
    aging_interval_ticks: int = TICKS_PER_MS,
) -> dict:
    policy = resolve_policy(policy)
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    if policy == "rr" and quantum_ticks <= 0:
        raise ValueError("round-robin quantum must be a positive number of ticks")
    if cs_ticks < 0:
        raise ValueError("context-switch cost cannot be negative")

    pcbs: dict[str, PCB] = {}
    for row in processes:
        pcb = PCB(row["pid"], int(row["arrival"]), int(row["burst"]), int(row["priority"]), int(row["order"]))
        pcbs[pcb.pid] = pcb
    arrival_order = sorted(pcbs.values(), key=lambda p: (p.arrival, p.order))

    max_time = None
    max_events = None
    if stop:
        if stop.get("max_time") is not None:
            max_time = int(stop["max_time"])
        elif stop.get("max_time_ms") is not None:
            max_time = int(round(float(stop["max_time_ms"]) * TICKS_PER_MS))
        if stop.get("max_events") is not None:
            max_events = int(stop["max_events"])

    t = 0
    ready: list[str] = []
    running: str | None = None
    slice_used = 0
    last_user_pid: str | None = None
    switching_until: int | None = None
    arrive_i = 0
    idle_ticks = 0
    cs_busy_ticks = 0
    gantt: list[dict] = []
    events: list[dict] = []
    seq = 0

    def emit(event_type: str, pid: str, action: str, prev: str | None, new: str | None, phase: str, message: str = "") -> None:
        nonlocal seq
        seq += 1
        events.append({
            "seq": seq,
            "time": t,
            "event_type": event_type,
            "entity_id": pid,
            "action": action,
            "prev_state": prev,
            "new_state": new,
            "outcome": "ok",
            "cost": 0,
            "severity": "info",
            "message": message,
            "phase": phase,
        })

    def close_gantt() -> None:
        if gantt and gantt[-1]["end"] is None:
            gantt[-1]["end"] = t
            if gantt[-1]["end"] == gantt[-1]["start"]:
                gantt.pop()

    def open_gantt(pid: str) -> None:
        gantt.append({"pid": pid, "start": t, "end": None})

    def admit_arrivals() -> None:
        nonlocal arrive_i
        while arrive_i < len(arrival_order) and arrival_order[arrive_i].arrival <= t:
            p = arrival_order[arrive_i]
            arrive_i += 1
            if p.arrival < t:
                pass
            p.state = "ready"
            ready.append(p.pid)
            emit("ARRIVE", p.pid, "arrive", "new", "ready", "arrival")

    def all_finished() -> bool:
        return all(p.remaining == 0 and p.completion is not None for p in pcbs.values())

    def hit_event_limit() -> bool:
        return max_events is not None and len(events) >= max_events


    if arrival_order:
        t = arrival_order[0].arrival

    safety = 0
    while safety < 1_000_000:
        safety += 1
        if max_time is not None and t > max_time:
            t = max_time
            close_gantt()
            break
        if hit_event_limit():
            close_gantt()
            break

        admit_arrivals()
        if hit_event_limit():
            close_gantt()
            break


        if switching_until is not None:
            if t < switching_until:
                nxt = _next_time(
                    switching_until,
                    arrival_order[arrive_i].arrival if arrive_i < len(arrival_order) else None,
                    max_time,
                )
                if nxt is None or nxt <= t:
                    break
                dt = nxt - t
                for pid in ready:
                    pcbs[pid].wait_ticks += dt
                cs_busy_ticks += dt
                t = nxt
                continue
            close_gantt()
            switching_until = None


        if running is not None and pcbs[running].remaining == 0:
            p = pcbs[running]
            close_gantt()
            p.completion = t
            p.state = "terminated"
            emit("COMPLETE", p.pid, "complete", "running", "terminated", "completion")
            last_user_pid = running
            running = None
            slice_used = 0
            if hit_event_limit():
                break


        if (
            policy == "rr"
            and running is not None
            and pcbs[running].remaining > 0
            and slice_used >= quantum_ticks
        ):
            p = pcbs[running]
            close_gantt()
            p.state = "ready"
            ready.append(p.pid)
            emit("QUANTUM_EXPIRY", p.pid, "requeue", "running", "ready", "quantum_expiry")
            last_user_pid = running
            running = None
            slice_used = 0
            if hit_event_limit():
                break

        if policy in PREEMPTIVE and running is not None and ready:
            cand = pick_ready(ready, pcbs, policy, aging, aging_interval_ticks)
            if cand is not None and _strictly_better_running(
                pcbs[cand], pcbs[running], policy, aging, aging_interval_ticks
            ):
                p = pcbs[running]
                close_gantt()
                p.state = "ready"
                ready.append(p.pid)
                emit("PREEMPT", p.pid, "preempt", "running", "ready", "preemption", f"preempted by {cand}")
                last_user_pid = running
                running = None
                slice_used = 0
                if hit_event_limit():
                    break


        if running is None and ready:
            pid = pick_ready(ready, pcbs, policy, aging, aging_interval_ticks)
            if pid is None:
                break
            if cs_ticks > 0 and last_user_pid is not None and last_user_pid != pid:
                switching_until = t + cs_ticks
                open_gantt("CS")
                emit("CONTEXT_SWITCH", pid, "switch", None, None, "other", f"from {last_user_pid} to {pid}")
                continue
            ready.remove(pid)
            p = pcbs[pid]
            prev = p.state
            p.state = "running"
            p.dispatches += 1
            if p.start is None:
                p.start = t
            running = pid
            slice_used = 0
            open_gantt(pid)
            emit("DISPATCH", pid, "dispatch", prev, "running", "dispatch")
            last_user_pid = pid
            if hit_event_limit():
                close_gantt()
                break

        if all_finished() and running is None:
            close_gantt()
            break

        next_arrival = arrival_order[arrive_i].arrival if arrive_i < len(arrival_order) else None
        next_done = t + pcbs[running].remaining if running is not None else None
        next_quantum = None
        if policy == "rr" and running is not None:
            left = quantum_ticks - slice_used
            if left < 0:
                left = 0
            next_quantum = t + left
        next_age = None
        if aging and policy == "priority_p" and running is not None and ready and aging_interval_ticks > 0:
            run_eff = pcbs[running].effective_priority(True, aging_interval_ticks)
            for pid in ready:
                p = pcbs[pid]
                if p.effective_priority(True, aging_interval_ticks) < run_eff:
                    next_age = t
                    break
                if run_eff <= 0:
                    continue
                need = (p.priority - run_eff + 1) * aging_interval_ticks
                extra = need - p.wait_ticks
                if extra > 0:
                    cand_t = t + extra
                    next_age = cand_t if next_age is None else min(next_age, cand_t)
        nxt = _next_time(next_arrival, next_done, next_quantum, next_age, max_time)
        if nxt is None:
            close_gantt()
            break
        if nxt < t:
            close_gantt()
            break
        if nxt == t:
            if running is None and next_arrival is None:
                close_gantt()
                break
            if running is None and not ready and next_arrival is not None and next_arrival > t:
                t = next_arrival
                continue
            close_gantt()
            break

        dt = nxt - t
        for pid in ready:
            pcbs[pid].wait_ticks += dt
        if running is not None:
            pcbs[running].remaining -= dt
            slice_used += dt
        else:
            idle_ticks += dt
        t = nxt
    else:
        close_gantt()

    makespan = t
    per_process = {}
    for p in pcbs.values():
        if p.start is None or p.completion is None:
            waiting = None
            turnaround = None
            response = None
        else:
            turnaround = p.completion - p.arrival
            waiting = turnaround - p.burst
            response = p.start - p.arrival
        per_process[p.pid] = {
            "start": p.start,
            "completion": p.completion,
            "turnaround": turnaround,
            "waiting": waiting,
            "response": response,
            "dispatches": p.dispatches,
            "remaining": p.remaining,
            "state": p.state,
            "wait_ticks": p.wait_ticks,
            "effective_priority": p.effective_priority(aging, aging_interval_ticks),
        }

    finished = [m for m in per_process.values() if m["completion"] is not None]
    n = len(finished)
    avg = {
        "turnaround": (sum(m["turnaround"] for m in finished) / n) if n else 0,
        "waiting": (sum(m["waiting"] for m in finished) / n) if n else 0,
        "response": (sum(m["response"] for m in finished) / n) if n else 0,
    }
    busy = makespan - idle_ticks
    util = (100.0 * busy / makespan) if makespan else 0.0

    return {
        "policy": policy,
        "time": t,
        "gantt": gantt,
        "per_process": per_process,
        "averages": avg,
        "makespan": makespan,
        "idle": idle_ticks,
        "context_switch_time": cs_busy_ticks,
        "cpu_utilization_pct": util,
        "events": events,
        "ready": list(ready),
        "running": running,
        "pcbs": pcbs,
    }


def result_in_ms(raw: dict) -> dict:


    def conv_seg(seg: dict) -> dict:
        return {"pid": seg["pid"], "start": ticks_to_ms(seg["start"]), "end": ticks_to_ms(seg["end"])}

    per = {}
    for pid, m in raw["per_process"].items():
        per[pid] = {
            "start": None if m["start"] is None else ticks_to_ms(m["start"]),
            "completion": None if m["completion"] is None else ticks_to_ms(m["completion"]),
            "turnaround": None if m["turnaround"] is None else ticks_to_ms(m["turnaround"]),
            "waiting": None if m["waiting"] is None else ticks_to_ms(m["waiting"]),
            "response": None if m["response"] is None else ticks_to_ms(m["response"]),
            "dispatches": m["dispatches"],
        }
    avg = raw["averages"]
    return {
        "gantt": [conv_seg(s) for s in raw["gantt"]],
        "per_process": per,
        "averages": {
            "turnaround": avg["turnaround"] / TICKS_PER_MS,
            "waiting": avg["waiting"] / TICKS_PER_MS,
            "response": avg["response"] / TICKS_PER_MS,
        },
        "makespan": ticks_to_ms(raw["makespan"]),
        "cpu_utilization_pct": raw["cpu_utilization_pct"],
        "idle": ticks_to_ms(raw["idle"]),
        "context_switch_time": ticks_to_ms(raw["context_switch_time"]),
    }
