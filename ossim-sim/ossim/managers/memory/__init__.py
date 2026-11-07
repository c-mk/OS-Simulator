"""memory manager. Owner: Copernic. Implements ossim.managers.base.Manager (see RTM rows for this manager)."""


from .paging import POLICIES, Pager
from .manager import MemoryManager, mem_ref, parse_address, refs_from_gantt