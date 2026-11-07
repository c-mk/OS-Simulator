"""FIFO vs LRU on the locality trace, worked by hand (independent of the memory manager's own tests).

Trace inputs/trace_locality.txt as pages (4096-byte pages): 0 1 0 1 2 0 1 3 0 1 4 0 1 2 0 1 3 0 1 4, three frames.
LRU (front = least recently used):  F F H H F H H F(evict 2) H H F(evict 3) H H F(evict 4) H H F(evict 2) H H F(evict 3)
  -> faults at references 1, 2, 5, 8, 11, 14, 17, 20 = 8 faults, 12 hits, 5 evictions (the first 3 faults fill the frames).
FIFO (front = oldest load):         F F H H F H H F(evict 0) F(evict 1) F(evict 2) F(evict 3) H H F(evict 0) F(evict 1)
                                    F(evict 4) F(evict 2) H H F(evict 0)
  -> faults at references 1, 2, 5, 8, 9, 10, 11, 14, 15, 16, 17, 20 = 12 faults, 8 hits, 9 evictions.
Cost: hit 1 tick, fault 50 ticks -> LRU 12*1 + 8*50 = 412 ticks (2.06 ms avg); FIFO 8*1 + 12*50 = 608 ticks (3.04 ms avg)."""
from ossim.managers.memory import MemoryManager

LRU_RESULTS = list("FFHHFHHFHHFHHFHHFHHF")
FIFO_RESULTS = list("FFHHFHHFFFFHHFFFFHHF")
LRU_EVICTED = [None, None, None, None, None, None, None, 2, None, None, 3, None, None, 4, None, None, 2, None, None, 3]
FIFO_EVICTED = [None, None, None, None, None, None, None, 0, 1, 2, 3, None, None, 0, 1, 4, 2, None, None, 0]


def run(policy):
    mm = MemoryManager()
    assert mm.configure({"policy": policy}) == []
    assert mm.load("inputs/trace_locality.txt") == []
    mm.run()
    return mm


def test_lru_on_the_locality_trace():
    mm = run("lru")
    s, m = mm.snapshot(), mm.metrics()
    assert s["results"] == LRU_RESULTS and s["evicted"] == LRU_EVICTED
    assert (m["hits"]["value"], m["faults"]["value"], m["evictions"]["value"]) == (12, 8, 5)
    assert m["avg_access_time"]["value"] == 2.06 and s["clock"] == 412


def test_fifo_on_the_locality_trace():
    mm = run("fifo")
    s, m = mm.snapshot(), mm.metrics()
    assert s["results"] == FIFO_RESULTS and s["evicted"] == FIFO_EVICTED
    assert (m["hits"]["value"], m["faults"]["value"], m["evictions"]["value"]) == (8, 12, 9)
    assert m["avg_access_time"]["value"] == 3.04 and s["clock"] == 608


def test_lru_keeps_the_hot_pages_resident_and_fifo_does_not():
    lru, fifo = run("lru").snapshot(), run("fifo").snapshot()
    hot = {0, 1}
    assert not any(e in hot for e in lru["evicted"] if e is not None)         # LRU never evicts the re-used pages 0 and 1
    assert sum(e in hot for e in fifo["evicted"] if e is not None) == 5      # FIFO evicts them 5 times
