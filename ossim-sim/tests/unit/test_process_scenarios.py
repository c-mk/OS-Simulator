"""Hand-worked scenarios beyond the baseline: context switches, aging, ties, idle time, boundaries.
Every expected value below was worked out by hand first (the working is in the comments)."""
import pytest

from tests.unit.helpers import BASELINE, gantt_ms, per_process_ms, simulate


# ---------------------------------------------------------------- context switch cost (T-PR-05, T-PR-08)
def test_fcfs_baseline_with_one_ms_context_switch():
    # First dispatch is free. P1 0-8, switch 8-9, P2 9-13, switch 13-14, P3 14-23, switch 23-24, P4 24-29.
    pm, _ = simulate(BASELINE, policy="fcfs", cs=1)
    assert gantt_ms(pm) == [("P1", 0, 8), ("CS", 8, 9), ("P2", 9, 13), ("CS", 13, 14), ("P3", 14, 23), ("CS", 23, 24), ("P4", 24, 29)]
    s = pm.snapshot()
    assert s["makespan"] == 290 and s["context_switch_time"] == 30 and s["switches"] == 3     # cs time = switches x cs
    assert s["averages"]["turnaround"] / 10 == 16.75     # (8 + 12 + 21 + 26) / 4
    assert s["averages"]["waiting"] / 10 == 10.25        # (0 + 8 + 12 + 21) / 4
    assert s["cpu_utilization_pct"] == pytest.approx(100 * 26 / 29)


def test_round_robin_with_context_switches():
    # P1(0,5) P2(0,3), q=2, cs=1.  P1 0-2 | CS 2-3 | P2 3-5 | CS 5-6 | P1 6-8 | CS 8-9 | P2 9-10 (done) | CS 10-11 | P1 11-12 (done)
    pm, _ = simulate([("P1", 0, 5, 1), ("P2", 0, 3, 1)], policy="rr", q=2, cs=1)
    assert gantt_ms(pm) == [("P1", 0, 2), ("CS", 2, 3), ("P2", 3, 5), ("CS", 5, 6), ("P1", 6, 8), ("CS", 8, 9), ("P2", 9, 10),
                            ("CS", 10, 11), ("P1", 11, 12)]
    p1, p2 = per_process_ms(pm, "P1"), per_process_ms(pm, "P2")
    assert (p1["completion"], p1["turnaround"], p1["waiting"], p1["response"], p1["dispatches"]) == (12, 12, 7, 0, 3)
    assert (p2["completion"], p2["turnaround"], p2["waiting"], p2["response"], p2["dispatches"]) == (10, 10, 7, 3, 2)
    s = pm.snapshot()
    assert s["switches"] == 4 and s["context_switch_time"] == 40 and s["makespan"] == 120


def test_smallest_context_switch_is_one_tick():
    pm, _ = simulate(BASELINE, policy="fcfs", cs=0.1)       # 3 switches x 0.1 ms = 0.3 ms = 3 ticks
    assert pm.snapshot()["context_switch_time"] == 3


def test_context_switch_is_charged_after_an_idle_gap():
    # P1 0-2, idle 2-5, P2 arrives at 5: previous user was P1, so switch 5-6, P2 6-8.
    pm, _ = simulate([("P1", 0, 2, 1), ("P2", 5, 2, 1)], policy="fcfs", cs=1)
    assert gantt_ms(pm) == [("P1", 0, 2), ("IDLE", 2, 5), ("CS", 5, 6), ("P2", 6, 8)]
    s = pm.snapshot()
    assert (s["idle"], s["context_switch_time"], s["makespan"]) == (30, 10, 80)


def test_zero_context_switch_cost_adds_no_cs_segments():
    pm, _ = simulate(BASELINE, policy="rr", q=4, cs=0)
    assert all(g["pid"] != "CS" for g in pm.snapshot()["gantt"])


# ---------------------------------------------------------------- aging (T-PR-06)
SPEC_NP_AGING = [("P1", 0, 10, 1), ("P2", 1, 2, 4), ("P3", 8, 2, 3)]


def test_priority_without_aging_picks_the_better_base_priority():
    # P1 runs 0-10. At 10, P3 (priority 3) beats P2 (priority 4): P3 10-12, P2 12-14.
    pm, _ = simulate(SPEC_NP_AGING, policy="priority")
    assert gantt_ms(pm) == [("P1", 0, 10), ("P3", 10, 12), ("P2", 12, 14)]
    assert per_process_ms(pm, "P2")["waiting"] == 11


def test_priority_with_aging_lets_the_long_waiter_win():
    # Aging every 3 ms (ticks at 3, 6, 9). P2: 4 -> 3 (t=3) -> 2 (t=6) -> 1 (t=9). P3 arrives at 8 with 3 -> 2 (t=9).
    # At t=10 P2 (1) beats P3 (2): P2 10-12, P3 12-14.
    pm, _ = simulate(SPEC_NP_AGING, policy="priority", aging=3)
    assert gantt_ms(pm) == [("P1", 0, 10), ("P2", 10, 12), ("P3", 12, 14)]
    assert per_process_ms(pm, "P2")["waiting"] == 9 and per_process_ms(pm, "P3")["waiting"] == 4


def test_preemptive_priority_aging_preempts_only_when_strictly_better():
    # P1(0,10,prio 2) runs; P2(1,2,prio 5) ages every 2 ms: 5 -> 4 (t=2) -> 3 (t=4) -> 2 (t=6: equal, no preempt) -> 1 (t=8).
    # At t=8 P2 is strictly better and preempts: P1 0-8 (2 ms left), P2 8-10 (done), P1 10-12.
    pm, _ = simulate([("P1", 0, 10, 2), ("P2", 1, 2, 5)], policy="priority", preemptive=True, aging=2)
    assert gantt_ms(pm) == [("P1", 0, 8), ("P2", 8, 10), ("P1", 10, 12)]
    p1, p2 = per_process_ms(pm, "P1"), per_process_ms(pm, "P2")
    assert (p1["completion"], p1["waiting"], p1["dispatches"], p1["preemptions"]) == (12, 2, 2, 1)
    assert (p2["start"], p2["completion"], p2["turnaround"], p2["waiting"], p2["response"]) == (8, 10, 9, 7, 7)


def test_without_aging_the_same_preemptive_workload_never_preempts():
    pm, _ = simulate([("P1", 0, 10, 2), ("P2", 1, 2, 5)], policy="priority", preemptive=True)
    assert gantt_ms(pm) == [("P1", 0, 10), ("P2", 10, 12)]


STARVE = [("L", 0, 1, 2), ("A", 0, 3, 1), ("B", 3, 3, 1), ("C", 6, 3, 1)]


def test_without_aging_low_priority_process_runs_last():
    pm, _ = simulate(STARVE, policy="priority")
    assert gantt_ms(pm) == [("A", 0, 3), ("B", 3, 6), ("C", 6, 9), ("L", 9, 10)]


def test_with_aging_low_priority_process_gets_the_cpu_sooner():
    # Aging every 2 ms. L waits behind A: 2 -> 1 at t=2. At t=3 L (1, arrived 0) ties B (1, arrived 3): earlier arrival wins.
    # A 0-3, L 3-4, B 4-7, C 7-10.
    pm, _ = simulate(STARVE, policy="priority", aging=2)
    assert gantt_ms(pm) == [("A", 0, 3), ("L", 3, 4), ("B", 4, 7), ("C", 7, 10)]


# ---------------------------------------------------------------- tie-breakers (docs/tie_breakers.md)
def test_fcfs_same_arrival_uses_input_order_not_pid_order():
    pm, _ = simulate([("C", 0, 3, 1), ("A", 0, 3, 1), ("B", 0, 3, 1)], policy="fcfs")
    assert gantt_ms(pm) == [("C", 0, 3), ("A", 3, 6), ("B", 6, 9)]


def test_sjf_equal_bursts_use_earlier_arrival_then_input_order():
    # P1 runs 0-1... all three equal bursts; B arrives earlier than A, so B goes first; then A and C by input order.
    pm, _ = simulate([("P0", 0, 2, 1), ("A", 2, 3, 1), ("B", 1, 3, 1), ("C", 2, 3, 1)], policy="sjf")
    assert gantt_ms(pm) == [("P0", 0, 2), ("B", 2, 5), ("A", 5, 8), ("C", 8, 11)]


def test_srtf_equal_remaining_time_does_not_preempt():
    # At t=1 P1 has 3 ms left and P2 needs 3 ms: equal, so P1 keeps the CPU.
    pm, _ = simulate([("P1", 0, 4, 1), ("P2", 1, 3, 1)], policy="srtf")
    assert gantt_ms(pm) == [("P1", 0, 4), ("P2", 4, 7)]


def test_srtf_strictly_shorter_remaining_time_preempts():
    pm, _ = simulate([("P1", 0, 5, 1), ("P2", 1, 3, 1)], policy="srtf")       # t=1: P1 has 4 left, P2 needs 3
    assert gantt_ms(pm) == [("P1", 0, 1), ("P2", 1, 4), ("P1", 4, 8)]


def test_round_robin_requeues_expired_process_after_same_time_arrival():
    # q=2. P1's quantum expires at t=2, the same tick P2 arrives; P2 is queued first, so P2 runs next.
    pm, _ = simulate([("P1", 0, 4, 1), ("P2", 2, 4, 1)], policy="rr", q=2)
    assert gantt_ms(pm) == [("P1", 0, 2), ("P2", 2, 4), ("P1", 4, 6), ("P2", 6, 8)]


def test_priority_equal_priority_uses_arrival_then_input_order():
    pm, _ = simulate([("P1", 0, 2, 5), ("B", 1, 2, 3), ("A", 1, 2, 3), ("C", 0, 2, 3)], policy="priority")
    # P1 runs first (only one at t=0 after C? C also arrives at 0 with better priority 3, listed after P1): C beats P1.
    assert [g[0] for g in gantt_ms(pm)] == ["C", "B", "A", "P1"]


def test_priority_preemption_requires_a_strictly_better_priority():
    pm, _ = simulate([("P1", 0, 4, 2), ("P2", 1, 2, 2)], policy="priority", preemptive=True)
    assert gantt_ms(pm) == [("P1", 0, 4), ("P2", 4, 6)]


def test_completion_is_handled_before_arrival_at_the_same_tick():
    # P1 ends at t=2 exactly when P2 arrives: no idle gap, P2 starts at 2. The log shows COMPLETE before ARRIVE.
    pm, events = simulate([("P1", 0, 2, 1), ("P2", 2, 2, 1)], policy="fcfs")
    assert gantt_ms(pm) == [("P1", 0, 2), ("P2", 2, 4)]
    at_2 = [e.event_type for e in events if e.time == 20]
    assert at_2.index("COMPLETE") < at_2.index("ARRIVE")


# ---------------------------------------------------------------- idle time and boundaries
def test_idle_gap_between_processes():
    pm, _ = simulate([("P1", 0, 2, 1), ("P2", 5, 2, 1)], policy="fcfs")
    assert gantt_ms(pm) == [("P1", 0, 2), ("IDLE", 2, 5), ("P2", 5, 7)]
    s = pm.snapshot()
    assert s["idle"] == 30 and s["makespan"] == 70 and s["cpu_utilization_pct"] == pytest.approx(100 * 4 / 7)


def test_idle_before_first_arrival_counts_as_idle():
    pm, _ = simulate([("P1", 3, 2, 1)], policy="fcfs")
    assert gantt_ms(pm) == [("IDLE", 0, 3), ("P1", 3, 5)]
    assert per_process_ms(pm, "P1")["response"] == 0


@pytest.mark.parametrize("policy", ["fcfs", "sjf", "srtf", "rr", "priority"])
def test_single_process_of_one_ms(policy):
    pm, events = simulate([("P1", 0, 1, 0)], policy=policy)
    assert gantt_ms(pm) == [("P1", 0, 1)]
    m = per_process_ms(pm, "P1")
    assert (m["turnaround"], m["waiting"], m["response"], m["dispatches"]) == (1, 0, 0, 1)
    assert [e.event_type for e in events] == ["SIM_START", "ARRIVE", "DISPATCH", "COMPLETE"]


def test_round_robin_burst_equal_to_quantum_finishes_without_expiry():
    pm, events = simulate([("P1", 0, 4, 1)], policy="rr", q=4)
    assert gantt_ms(pm) == [("P1", 0, 4)] and "QUANTUM_EXPIRE" not in [e.event_type for e in events]


def test_round_robin_lone_process_longer_than_quantum_keeps_running():
    pm, _ = simulate([("P1", 0, 10, 1)], policy="rr", q=4)
    assert gantt_ms(pm) == [("P1", 0, 10)]                       # back-to-back runs shown as one bar
    m = per_process_ms(pm, "P1")
    assert (m["dispatches"], m["preemptions"]) == (3, 2)         # 0-4, 4-8, 8-10; each ready->running counts as a dispatch


def test_round_robin_huge_quantum_behaves_like_fcfs():
    a, _ = simulate(BASELINE, policy="rr", q=1000)
    b, _ = simulate(BASELINE, policy="fcfs")
    assert gantt_ms(a) == gantt_ms(b)


def test_large_arrival_and_burst_values():
    pm, _ = simulate([("P1", 1_000_000, 1_000_000, 0)], policy="fcfs")
    assert pm.snapshot()["makespan"] == 20_000_000


def test_throughput_and_queue_length_metrics():
    pm, _ = simulate([("P1", 0, 2, 1), ("P2", 0, 2, 1)], policy="fcfs")
    m = pm.metrics()
    assert m["throughput"]["value"] == pytest.approx(0.5)        # 2 processes in 4 ms
    assert m["avg_queue_length"]["value"] == pytest.approx(0.5)  # P2 waits 2 of 4 ms, P1 never waits
    assert m["max_queue_length"]["value"] == 2                   # both are in the ready queue at t=0 before the first dispatch
    assert m["avg_turnaround"]["unit"] == "ms"
