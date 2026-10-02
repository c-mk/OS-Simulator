"""Discrete-event clock (spec 3, ADR-0001). Owner: Rasheed. Implementation due Milestone 2."""
from ossim.core.events import TICKS_PER_MS


def ms_to_ticks(ms: float) -> int:
    """Convert milliseconds to integer ticks; rejects values that are not a whole number of ticks."""
    ticks = round(ms * TICKS_PER_MS)
    if abs(ticks - ms * TICKS_PER_MS) > 1e-9 or ticks < 0:
        raise ValueError(f"{ms} ms is not a non-negative multiple of 0.1 ms")
    return ticks
