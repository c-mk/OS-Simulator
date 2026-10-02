"""Interface and event-schema contracts (T-API-01, T-EV-01)."""
import pytest

from ossim.core.clock import ms_to_ticks
from ossim.core.events import REQUIRED_FIELDS, Event
from ossim.managers.base import INTERFACE_METHODS, Manager


def test_manager_interface_has_appendix_a_methods():
    assert set(INTERFACE_METHODS) <= set(Manager.__abstractmethods__)


def test_event_has_required_fields_and_orders_deterministically():
    e1 = Event(2, 50, "s", "c", "device", "REQUEST_COMPLETE", "disk0:R1", "complete", "active", "completed", "ok", phase="service_done")
    e2 = Event(1, 50, "s", "c", "process", "DISPATCH", "P1", "dispatch", "ready", "running", "ok", phase="dispatch")
    assert REQUIRED_FIELDS <= set(e1.to_dict())
    assert e1.time_ms == 5.0
    assert sorted([e2, e1], key=Event.sort_key) == [e1, e2]   # completion phase before dispatch


@pytest.mark.parametrize("ms,ticks", [(0, 0), (0.1, 1), (0.5, 5), (1, 10), (16, 160)])
def test_ms_to_ticks(ms, ticks):
    assert ms_to_ticks(ms) == ticks


def test_ms_to_ticks_rejects_bad_values():
    with pytest.raises(ValueError):
        ms_to_ticks(0.05)
    with pytest.raises(ValueError):
        ms_to_ticks(-1)
