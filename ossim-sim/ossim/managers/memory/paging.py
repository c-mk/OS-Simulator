"""Page replacement: FIFO and LRU. Owner: Copernic.

Data structures: lists, dicts, and loops only.

One list, `order`, holds the resident pages. The front is always evicted next.
  FIFO: a page is appended when it is loaded and never moves.
  LRU:  the same, but a hit moves the page to the back.
That single `if` is the whole difference between the two policies.
"""
from __future__ import annotations

POLICIES = ("fifo", "lru")


class Pager:
    def __init__(self, page_size: int, frames: int, policy: str) -> None:
        self.page_size = page_size
        self.policy = policy
        self.frames: list = [None] * frames   # frame number -> (pid, page) or None
        self.tables: dict = {}                # pid -> {page: frame}   (the page tables)
        self.order: list = []                 # resident (pid, page) keys, next victim first

    def access(self, pid: str, address: int) -> dict:
        page, offset = divmod(address, self.page_size)
        key = (pid, page)
        table = self.tables.setdefault(pid, {})
        if page in table:                                       # hit
            if self.policy == "lru":
                self.order.remove(key)
                self.order.append(key)
            return {"page": page, "offset": offset, "hit": True, "frame": table[page], "evicted": None}
        evicted = None                                          # page fault
        if None in self.frames:
            frame = self.frames.index(None)
        else:
            evicted = self.order.pop(0)
            frame = self.tables[evicted[0]].pop(evicted[1])
        self.frames[frame] = key
        table[page] = frame
        self.order.append(key)
        return {"page": page, "offset": offset, "hit": False, "frame": frame, "evicted": evicted}

    def frames_view(self) -> list:
        """Frame contents as JSON-friendly dicts (None = free)."""
        return [None if k is None else {"pid": k[0], "page": k[1]} for k in self.frames]