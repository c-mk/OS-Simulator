"""Input loaders with validation (spec 3, 5.2). Owner: Derrick. Errors are specific and non-destructive."""
from __future__ import annotations

import csv
import re
from pathlib import Path

PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,31}$")


class InputError(ValueError):
    pass


def load_processes_csv(path: str | Path) -> list[dict]:
    rows, seen = [], set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["pid", "arrival", "burst", "priority"]:
            raise InputError(f"{path}: header must be pid,arrival,burst,priority")
        for line_no, r in enumerate(reader, start=2):
            if None in r.values() or None in r:
                raise InputError(f"{path}:{line_no}: wrong number of fields")
            pid = r["pid"].strip()
            if not PID_RE.match(pid):
                raise InputError(f"{path}:{line_no}: invalid pid {pid!r}")
            if pid in seen:
                raise InputError(f"{path}:{line_no}: duplicate pid {pid}")
            try:
                arrival, burst, prio = int(r["arrival"]), int(r["burst"]), int(r["priority"])
            except ValueError:
                raise InputError(f"{path}:{line_no}: arrival, burst and priority must be integers") from None
            if arrival < 0 or burst <= 0 or prio < 0:
                raise InputError(f"{path}:{line_no}: arrival >= 0, burst > 0, priority >= 0 required")
            seen.add(pid)
            rows.append({"pid": pid, "arrival": arrival, "burst": burst, "priority": prio, "order": len(rows)})
    if not rows:
        raise InputError(f"{path}: no processes")
    return rows


def load_trace(path: str | Path) -> list[int]:
    out = []
    for line_no, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        s = raw.split("#", 1)[0].strip()
        if not s:
            continue
        try:
            value = int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            raise InputError(f"{path}:{line_no}: not a decimal or hex address: {s!r}") from None
        if value < 0:
            raise InputError(f"{path}:{line_no}: negative address")
        out.append(value)
    return out


FS_COMMANDS = {"mkdir", "ls", "mkfile", "write", "append", "cat", "rm", "rmdir"}


def load_fs_script(path: str | Path) -> list[tuple[str, list[str]]]:
    cmds = []
    for line_no, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        name, _, rest = s.partition(" ")
        if name not in FS_COMMANDS:
            raise InputError(f"{path}:{line_no}: unknown command {name!r}")
        if name in ("write", "append"):
            target, _, text = rest.partition(" ")
            args = [target, text.strip().strip('"')]
        else:
            args = [rest.strip()] if rest.strip() else []
        cmds.append((name, args))
    return cmds
