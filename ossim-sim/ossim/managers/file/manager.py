"""File manager: scripted or process-issued commands on the in-memory file system. Owner: Liberty.

Time is integer ticks (1 tick = 0.1 ms), the same as the process and memory managers. Each command costs its
`latency_ticks` entry (default below); the manager clock moves on by that cost, like MemoryManager.

Contract notes
  * configure() and load() return a list of error messages (empty = ok) and change nothing on error.
  * load() takes a script file path (read with ossim.io.loaders.load_fs_script, so errors read like every other
    loader) or a list of entries: (cmd, args) | (cmd, args, at_tick) | (cmd, args, at_tick, user) or
    {"cmd", "args", "at", "user", "pid"}. Command syntax and argument counts are checked at load; path problems
    are command results (a script may contain expected errors).
  * An entry with a "pid" is a process request: the process is BLOCKed while the command is served, then
    UNBLOCKed (ready again). Entries without a pid are administrator script lines and never block anyone.
  * Results: outcome "ok", "failed" (a safe error) or "denied" (permission). Every command emits one FILE_OP event.
  * run() is restartable: it rebuilds the file system and log from the loaded script each call.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ossim.core.events import TICKS_PER_MS, Event
from ossim.io.loaders import InputError, load_fs_script
from ossim.managers.base import Manager

from .fs import FileSystem, FsDenied, FsError

COMMANDS = ("mkdir", "ls", "mkfile", "write", "append", "cat", "rm", "rmdir")
ARITY = {"mkdir": (1, 1), "ls": (0, 1), "mkfile": (1, 1), "write": (2, 2), "append": (2, 2),
         "cat": (1, 1), "rm": (1, 1), "rmdir": (1, 1)}
DEFAULTS = {
    "user": "admin",                                   # who runs entries that name no user
    "users": {"admin": "admin", "alice": "staff", "bob": "staff", "guest": "guests"},   # user -> group
    "admins": ["admin"],
    "latency_ticks": {"mkdir": 20, "ls": 10, "mkfile": 20, "write": 30, "append": 30, "cat": 10, "rm": 20, "rmdir": 20},
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def file_request(pid: str, cmd: str, args: list, at: int) -> Event:
    """The event a process emits to ask for a file operation; pass it to FileManager.step()."""
    return Event(seq=0, time=at, scenario_id="", correlation_id=pid, manager="process",
                 event_type="FILE_REQUEST", entity_id=pid, action=cmd, prev_state=None, new_state=None,
                 outcome="ok", message=json.dumps(list(args)), phase="other")


class FileManager(Manager):
    name = "file"

    def __init__(self) -> None:
        self.config = json.loads(json.dumps(DEFAULTS))
        self.script: list = []
        self.reset()

    # 1. configure
    def configure(self, config: dict) -> list[str]:
        merged = {**self.config, **config}
        errors = [f"unknown setting {k!r}" for k in config if k not in DEFAULTS]
        users = merged["users"]
        if not isinstance(users, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in users.items()):
            errors.append("users must map each user name to a group name")
        if not isinstance(merged["admins"], list) or not all(isinstance(a, str) for a in merged["admins"]):
            errors.append("admins must be a list of user names")
        if not isinstance(merged["user"], str) or not merged["user"]:
            errors.append("user must be a name")
        lat = merged["latency_ticks"]
        if not isinstance(lat, dict) or set(lat) - set(COMMANDS):
            errors.append("latency_ticks must map command names to ticks")
        elif any(not _is_int(v) or v < 0 for v in lat.values()):
            errors.append("latency_ticks cannot be negative")
        else:
            merged["latency_ticks"] = {**DEFAULTS["latency_ticks"], **lat}
        if errors:
            return errors
        self.config = merged
        self.reset()
        return []

    # 2. load
    def load(self, data) -> list[str]:
        entries, errors = [], []
        if isinstance(data, (str, Path)):
            try:
                raw = load_fs_script(data)
            except (InputError, OSError) as e:
                return [str(e)]
            items = [{"cmd": c, "args": a} for c, a in raw]
        else:
            items = []
            for i, item in enumerate(data, 1):
                if isinstance(item, dict):
                    items.append({"cmd": item.get("cmd"), "args": item.get("args", []), "at": item.get("at"),
                                  "user": item.get("user"), "pid": item.get("pid"), "_n": i})
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    items.append({"cmd": item[0], "args": item[1], "at": item[2] if len(item) > 2 else None,
                                  "user": item[3] if len(item) > 3 else None, "_n": i})
                else:
                    items.append({"_bad": item, "_n": i})
        for n, it in enumerate(items, 1):
            n = it.get("_n", n)
            if "_bad" in it:
                errors.append(f"Command {n}: invalid entry {it['_bad']!r}")
                continue
            cmd, args = it["cmd"], it["args"]
            if cmd not in COMMANDS:
                errors.append(f"Command {n}: unknown command {cmd!r}")
                continue
            if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
                errors.append(f"Command {n}: arguments must be text")
                continue
            lo, hi = ARITY[cmd]
            if not lo <= len(args) <= hi:
                errors.append(f"Command {n}: {cmd} takes {lo if lo == hi else f'{lo} to {hi}'} argument(s), got {len(args)}")
                continue
            at = it.get("at")
            if at is not None and (not _is_int(at) or at < 0):
                errors.append(f"Command {n}: time must be a whole number of ticks, 0 or more")
                continue
            entries.append({"cmd": cmd, "args": list(args), "at": at, "user": it.get("user"), "pid": it.get("pid")})
        if not errors and not entries:
            errors.append("Script is empty")
        if errors:
            return errors
        self.script = entries
        self.reset()
        return []

    # 3. reset
    def reset(self) -> None:
        self.fs = FileSystem(self.config["users"], self.config["admins"])
        self.clock = 0
        self.cursor = 0
        self.seq = 0
        self.events: list = []
        self.history: list = []
        self.setup: list = []

    def set_mode(self, path, mode, owner=None, group=None) -> list[str]:
        """Setup helper (not a file command): chmod/chown a node. Re-applied after reset() through self.setup."""
        try:
            self.fs.set_mode(path, mode, owner, group)
        except FsError as e:
            return [str(e)]
        self.setup.append((path, mode, owner, group))
        return []

    def _emit(self, t, ent, etype, action, prev, new, outcome, cost, message, severity="info", phase="other", corr=None) -> None:
        self.seq += 1
        self.events.append(Event(
            seq=self.seq, time=t, scenario_id="", event_type=etype, entity_id=ent, action=action,
            prev_state=prev, new_state=new, outcome=outcome, cost=cost, severity=severity,
            message=message, phase=phase, manager="file", correlation_id=corr or ent))

    # 4. step
    def step(self, event: Event | None = None) -> list[Event]:
        """One command. With a FILE_REQUEST event: that process request (other event types return []).
        Without: the next loaded script entry (empty list at the end)."""
        if event is not None:
            if event.event_type != "FILE_REQUEST":
                return []
            try:
                args = json.loads(event.message)
            except ValueError:
                args = []
            return self._exec({"cmd": event.action, "args": args, "at": event.time, "user": None, "pid": event.entity_id})
        if self.cursor >= len(self.script):
            return []
        entry = self.script[self.cursor]
        self.cursor += 1
        return self._exec(entry)

    def _exec(self, entry: dict) -> list[Event]:
        cmd, args, pid = entry["cmd"], entry["args"], entry.get("pid")
        user = entry.get("user") or self.config["user"]
        at = entry.get("at")
        t = self.clock if at is None else max(self.clock, at)
        cost = self.config["latency_ticks"][cmd]
        before = len(self.events)
        rec = {"index": len(self.history) + 1, "time": t, "user": user, "pid": pid, "cmd": cmd, "args": list(args),
               "ok": False, "outcome": "failed", "output": "", "error": "", "bytes_read": 0, "bytes_written": 0,
               "created": None, "deleted": None, "latency": cost}
        try:
            res = getattr(self.fs, cmd)(*args, user=user, now=t)
            rec.update(ok=True, outcome="ok", output=res.get("output", ""), bytes_read=res.get("bytes_read", 0),
                       bytes_written=res.get("bytes_written", 0), created=res.get("created"), deleted=res.get("deleted"))
        except FsDenied as e:
            rec.update(outcome="denied", error=str(e))
        except FsError as e:
            rec.update(error=str(e))
        text = f"{cmd} {' '.join(args)}".strip()
        msg = text if rec["ok"] else f"{text}: {rec['error']}"
        ent = pid or user
        if pid:
            self._emit(t, pid, "BLOCK", "file_request", "running", "waiting", "ok", 0, f"waiting {cost} ticks for {text}")
        self._emit(t, ent, "FILE_OP", cmd, None, None, {"ok": "ok", "failed": "failed", "denied": "denied"}[rec["outcome"]],
                   cost, msg, severity="warning" if rec["outcome"] == "denied" else "info", corr=pid or user)
        if pid:
            self._emit(t + cost, pid, "UNBLOCK", "file_served", "waiting", "ready", "ok", 0, f"{text} served",
                       phase="service_done")
        self.clock = t + cost
        self.history.append(rec)
        return self.events[before:]

    # 5. run
    def run(self, stop: dict | None = None) -> list[Event]:
        """Restart and run the script. stop: max_time (ticks) / max_time_ms / max_events (inclusive, like the other
        managers). A command is never cut in half. Returns every event produced."""
        max_time = max_events = None
        if stop:
            if stop.get("max_time") is not None:
                max_time = int(stop["max_time"])
            elif stop.get("max_time_ms") is not None:
                max_time = int(round(float(stop["max_time_ms"]) * TICKS_PER_MS))
            if stop.get("max_events") is not None:
                max_events = int(stop["max_events"])
        setup = list(self.setup)
        self.reset()
        for path, mode, owner, group in setup:
            self.fs.set_mode(path, mode, owner, group)
        self.setup = setup
        while self.cursor < len(self.script):
            if max_events is not None and len(self.events) >= max_events:
                break
            at = self.script[self.cursor].get("at")
            if max_time is not None and (self.clock if at is None else max(self.clock, at)) > max_time:
                break
            self.step()
        return list(self.events)

    # 6. snapshot
    def per_command(self) -> dict:
        out = {}
        for c in COMMANDS:
            rows = [h for h in self.history if h["cmd"] == c]
            if rows:
                total = sum(h["latency"] for h in rows)
                out[c] = {"count": len(rows), "ok": sum(h["outcome"] == "ok" for h in rows),
                          "failed": sum(h["outcome"] == "failed" for h in rows),
                          "denied": sum(h["outcome"] == "denied" for h in rows),
                          "total_ticks": total, "avg_ms": round(total / len(rows) / TICKS_PER_MS, 3)}
        return out

    def snapshot(self) -> dict:
        return {"clock": self.clock, "tree": self.fs.tree(), "storage_bytes": self.fs.storage,
                "node_count": self.fs.node_count, "log": list(self.history), "per_command": self.per_command(),
                "processed": self.cursor, "script_length": len(self.script),
                "users": dict(self.config["users"]), "admins": list(self.config["admins"])}

    # 7. metrics
    def metrics(self) -> dict:
        h = self.history
        ok = [x for x in h if x["outcome"] == "ok"]
        total = sum(x["latency"] for x in h)
        vals = {
            "operations": (len(h), "count"),
            "succeeded": (len(ok), "count"),
            "failed": (sum(x["outcome"] == "failed" for x in h), "count"),
            "denied": (sum(x["outcome"] == "denied" for x in h), "count"),
            "bytes_read": (sum(x["bytes_read"] for x in h), "bytes"),
            "bytes_written": (sum(x["bytes_written"] for x in h), "bytes"),
            "files_created": (sum(x["created"] == "file" for x in ok), "count"),
            "dirs_created": (sum(x["created"] == "dir" for x in ok), "count"),
            "files_deleted": (sum(x["deleted"] == "file" for x in ok), "count"),
            "dirs_deleted": (sum(x["deleted"] == "dir" for x in ok), "count"),
            "storage_used": (self.fs.storage, "bytes"),
            "nodes": (self.fs.node_count, "count"),
            "avg_latency": (round(total / len(h) / TICKS_PER_MS, 3) if h else 0.0, "ms"),
        }
        return {k: {"value": v, "unit": u} for k, (v, u) in vals.items()}

    # 8. validate
    def validate(self) -> list[str]:
        warnings = []
        if not self.script:
            warnings.append("No script loaded")
        known = set(self.config["users"])
        for e in self.script:
            if e.get("user") and e["user"] not in known and e["user"] not in self.config["admins"]:
                warnings.append(f"user {e['user']!r} is not in the user list, so it is treated as 'other'")
                break
        if len(self.script) < 12:
            warnings.append("script has fewer than 12 commands (Milestone 3 asks for 12 or more)")
        return warnings

    # 9. export
    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            return json.dumps({"snapshot": self.snapshot(), "metrics": self.metrics(),
                               "events": [e.to_dict() for e in self.events]}, indent=2)
        if fmt == "csv":                     # the chronological operation log
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["index", "time_ms", "user", "pid", "command", "arguments", "outcome", "output_or_error",
                        "bytes_read", "bytes_written", "latency_ms"])
            for h in self.history:
                w.writerow([h["index"], h["time"] / TICKS_PER_MS, h["user"], h["pid"] or "", h["cmd"],
                            " ".join(h["args"]), h["outcome"], h["output"] if h["ok"] else h["error"],
                            h["bytes_read"], h["bytes_written"], h["latency"] / TICKS_PER_MS])
            return buf.getvalue()
        raise ValueError("export format must be json or csv")
