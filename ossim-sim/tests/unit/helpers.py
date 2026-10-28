"""Shared helpers for process-manager tests. Times in these helpers are ms; the engine works in ticks (1 ms = 10 ticks)."""
from ossim.managers.process import ProcessManager

BASELINE = [("P1", 0, 8, 3), ("P2", 1, 4, 1), ("P3", 2, 9, 4), ("P4", 3, 5, 2)]


def rows(spec):
    return [{"pid": p, "arrival": a, "burst": b, "priority": pr} for p, a, b, pr in spec]


def simulate(spec, **config):
    """Configure + load + run to the end. Returns (manager, logged events)."""
    pm = ProcessManager()
    assert pm.configure(config) == []
    assert pm.load(rows(spec)) == []
    return pm, pm.run()


def gantt_ms(pm):
    """Snapshot Gantt as [(pid, start_ms, end_ms)], including IDLE and CS segments."""
    return [(g["pid"], g["start"] / 10, g["end"] / 10) for g in pm.snapshot()["gantt"]]


def per_process_ms(pm, pid):
    m = pm.snapshot()["per_process"][pid]
    return {k: (v / 10 if k in ("start", "completion", "turnaround", "waiting", "response") else v) for k, v in m.items()}
