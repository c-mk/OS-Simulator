"""In-memory hierarchical file system (spec 4.3). Owner: Liberty.

Everything lives in Python objects: no host path is ever opened (spec: do not operate on arbitrary host files).

Rules (also in docs/file_manager.md)
  * Paths are absolute and start with "/". "." and ".." are resolved; ".." above the root and "//" runs are handled
    (a doubled slash collapses; going above the root is an error). Names use letters, digits, "." "_" "-" (max 64).
  * mkdir / mkfile need an existing parent directory (no -p). Duplicate names are rejected.
  * rm removes files only; rmdir removes empty directories only; the root can never be removed.
  * write replaces a file's content, append adds to it; both need an existing file (create it with mkfile first).
  * Sizes are UTF-8 bytes. Limits: 10,000 nodes, 1 MB per file, 10 MB total, depth 32.
  * Permissions: owner/group/other rwx digits (default 640 files, 750 directories, root 755). Traversal (x) is not
    checked. ls and cat need r; write and append need w on the file; mkdir, mkfile, rm and rmdir need w on the parent.
    Users listed as admins bypass every check. user=None means "system" (no checks).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_NODES = 10_000
MAX_FILE_BYTES = 1_000_000
MAX_STORAGE_BYTES = 10_000_000
MAX_DEPTH = 32
MAX_NAME = 64
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MODE_RE = re.compile(r"^[0-7]{3}$")
DEFAULT_FILE_MODE = "640"
DEFAULT_DIR_MODE = "750"


class FsError(Exception):
    """A command failed safely: nothing in the tree changed."""


class FsDenied(FsError):
    """The user lacks the needed permission."""


@dataclass
class Node:
    name: str
    is_dir: bool
    owner: str = "admin"
    group: str = "admin"
    mode: str = DEFAULT_FILE_MODE
    content: str = ""
    created: int = 0
    modified: int = 0
    children: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return 0 if self.is_dir else len(self.content.encode("utf-8"))

    def to_dict(self, path: str = "/") -> dict:
        d = {"name": self.name, "path": path, "is_dir": self.is_dir, "size": self.size, "owner": self.owner,
             "group": self.group, "mode": self.mode, "created": self.created, "modified": self.modified}
        if self.is_dir:
            d["children"] = [c.to_dict(path.rstrip("/") + "/" + c.name) for _, c in sorted(self.children.items())]
        return d


def split_path(path) -> list[str]:
    """Normalize an absolute path to its list of names. Raises FsError."""
    if not isinstance(path, str) or not path:
        raise FsError("path must be a non-empty string")
    if "\x00" in path:
        raise FsError("path contains an invalid character")
    if len(path) > 1024:
        raise FsError("path is too long")
    if not path.startswith("/"):
        raise FsError(f"path must be absolute (start with /): {path}")
    parts: list[str] = []
    for token in path.split("/"):
        if token in ("", "."):
            continue
        if token == "..":
            if not parts:
                raise FsError(f"path escapes the root: {path}")
            parts.pop()
            continue
        if len(token) > MAX_NAME or not NAME_RE.match(token):
            raise FsError(f"invalid name {token!r} in {path}")
        parts.append(token)
    if len(parts) > MAX_DEPTH:
        raise FsError(f"path is too deep (more than {MAX_DEPTH} levels): {path}")
    return parts


def join_path(parts: list[str]) -> str:
    return "/" + "/".join(parts)


class FileSystem:
    def __init__(self, users: dict | None = None, admins: list | None = None) -> None:
        self.users = dict(users or {})
        self.admins = set(admins or [])
        self.root = Node("/", True, "admin", "admin", "755")
        self.node_count = 1
        self.storage = 0

    # ----- lookup / permissions -----
    def _walk(self, parts: list[str]) -> Node:
        """Node at parts. Raises FsError("no such directory|not a directory", ...) for a broken path."""
        node, so_far = self.root, []
        for name in parts:
            so_far.append(name)
            if not node.is_dir:
                raise FsError(f"not a directory: {join_path(so_far[:-1])}")
            if name not in node.children:
                raise FsError(f"no such file or directory: {join_path(so_far)}")
            node = node.children[name]
        return node

    def resolve(self, path):
        """Return the Node at path or raise FsError."""
        return self._walk(split_path(path))

    def _group_of(self, user: str) -> str:
        return self.users.get(user, "")

    def allowed(self, user, node: Node, bit: str) -> bool:
        if user is None or user in self.admins:
            return True
        digit = int(node.mode[0] if user == node.owner else node.mode[1] if self._group_of(user) == node.group else node.mode[2])
        return bool(digit & {"r": 4, "w": 2, "x": 1}[bit])

    def _need(self, user, node: Node, bit: str, path: str) -> None:
        if not self.allowed(user, node, bit):
            word = {"r": "read", "w": "write"}[bit]
            raise FsDenied(f"permission denied: {user} cannot {word} {path}")

    def _parent(self, parts: list[str], path: str) -> tuple[Node, str]:
        if not parts:
            raise FsError("already exists: /")
        try:
            parent = self._walk(parts[:-1])
        except FsError as e:
            if "not a directory" in str(e):
                raise
            raise FsError(f"no such directory: {join_path(parts[:-1])}") from None
        if not parent.is_dir:
            raise FsError(f"not a directory: {join_path(parts[:-1])}")
        return parent, parts[-1]

    def _add(self, parts, path, is_dir, user, now) -> Node:
        parent, name = self._parent(parts, path)
        if name in parent.children:
            raise FsError(f"already exists: {join_path(parts)}")
        self._need(user, parent, "w", join_path(parts[:-1]))
        if self.node_count >= MAX_NODES:
            raise FsError(f"too many files and directories (limit {MAX_NODES})")
        owner = user or "admin"
        node = Node(name, is_dir, owner, self._group_of(owner) or "admin",
                    DEFAULT_DIR_MODE if is_dir else DEFAULT_FILE_MODE, created=now, modified=now)
        parent.children[name] = node
        parent.modified = now
        self.node_count += 1
        return node

    # ----- the eight commands. Each returns a result dict or raises FsError -----
    def mkdir(self, path, user=None, now=0) -> dict:
        self._add(split_path(path), path, True, user, now)
        return {"output": "", "created": "dir"}

    def mkfile(self, path, user=None, now=0) -> dict:
        self._add(split_path(path), path, False, user, now)
        return {"output": "", "created": "file"}

    def ls(self, path="/", user=None, now=0) -> dict:
        parts = split_path(path)
        try:
            node = self._walk(parts)
        except FsError as e:
            if "not a directory" in str(e):
                raise
            raise FsError(f"no such directory: {join_path(parts)}") from None
        self._need(user, node, "r", join_path(parts))
        if not node.is_dir:
            return {"output": node.name}
        names = [n + "/" if c.is_dir else n for n, c in sorted(node.children.items())]
        return {"output": "\n".join(names)}

    def _file(self, path, user, bit, now=0):
        parts = split_path(path)
        try:
            node = self._walk(parts)
        except FsError as e:
            if "not a directory" in str(e):
                raise
            raise FsError(f"no such file: {join_path(parts)}") from None
        if node.is_dir:
            raise FsError(f"is a directory: {join_path(parts)}")
        self._need(user, node, bit, join_path(parts))
        return node

    def cat(self, path, user=None, now=0) -> dict:
        node = self._file(path, user, "r")
        return {"output": node.content, "bytes_read": node.size}

    def _store(self, node: Node, text: str, now: int, path: str) -> int:
        new_size = len(text.encode("utf-8"))
        if new_size > MAX_FILE_BYTES:
            raise FsError(f"file would exceed {MAX_FILE_BYTES} bytes: {path}")
        if self.storage - node.size + new_size > MAX_STORAGE_BYTES:
            raise FsError(f"storage limit of {MAX_STORAGE_BYTES} bytes reached")
        self.storage += new_size - node.size
        node.content = text
        node.modified = now
        return new_size

    def write(self, path, text, user=None, now=0) -> dict:
        node = self._file(path, user, "w")
        before = node.size
        self._store(node, str(text), now, path)
        return {"output": "", "bytes_written": node.size, "size_before": before}

    def append(self, path, text, user=None, now=0) -> dict:
        node = self._file(path, user, "w")
        text = str(text)
        self._store(node, node.content + text, now, path)
        return {"output": "", "bytes_written": len(text.encode("utf-8"))}

    def rm(self, path, user=None, now=0) -> dict:
        parts = split_path(path)
        node = self._file(path, None, "r")   # existence and type; the delete right is the parent's w
        parent = self._walk(parts[:-1])
        self._need(user, parent, "w", join_path(parts[:-1]))
        self.storage -= node.size
        del parent.children[parts[-1]]
        parent.modified = now
        self.node_count -= 1
        return {"output": "", "deleted": "file", "bytes_freed": node.size}

    def rmdir(self, path, user=None, now=0) -> dict:
        parts = split_path(path)
        if not parts:
            raise FsError("cannot remove the root directory: /")
        try:
            node = self._walk(parts)
        except FsError as e:
            if "not a directory" in str(e):
                raise
            raise FsError(f"no such directory: {join_path(parts)}") from None
        if not node.is_dir:
            raise FsError(f"not a directory: {join_path(parts)}")
        if node.children:
            raise FsError(f"directory not empty: {join_path(parts)}")
        parent = self._walk(parts[:-1])
        self._need(user, parent, "w", join_path(parts[:-1]))
        del parent.children[parts[-1]]
        parent.modified = now
        self.node_count -= 1
        return {"output": "", "deleted": "dir"}

    # ----- setup helper (not one of the eight commands) -----
    def set_mode(self, path, mode: str, owner: str | None = None, group: str | None = None) -> None:
        if not MODE_RE.match(str(mode)):
            raise FsError(f"mode must be three octal digits like 640: {mode!r}")
        node = self.resolve(path)
        node.mode = str(mode)
        if owner:
            node.owner = owner
        if group:
            node.group = group

    def tree(self) -> dict:
        return self.root.to_dict("/")
