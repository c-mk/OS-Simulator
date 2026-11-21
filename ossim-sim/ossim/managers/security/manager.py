"""Role-based security manager with authorization checks and append-only audit records."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from ossim.core.events import Event
from ossim.managers.base import Manager

DEFAULTS = {
    "users": {
        "admin": {"role": "administrator", "enabled": True},
        "alice": {"role": "operator", "enabled": True},
        "bob": {"role": "viewer", "enabled": True},
        "guest": {"role": "guest", "enabled": True},
    },
    "roles": {
        "administrator": {"*": ["read", "write", "execute", "delete", "admin"]},
        "operator": {"files": ["read", "write"], "devices": ["read", "execute"], "network": ["read"]},
        "viewer": {"files": ["read"], "devices": ["read"], "network": ["read"]},
        "guest": {"public": ["read"]},
    },
    "failed_login_alert_threshold": 3,
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class SecurityManager(Manager):
    """A deterministic RBAC model. Audit records are append-only during a run."""

    name = "security"

    def __init__(self) -> None:
        self.config = json.loads(json.dumps(DEFAULTS))
        self.operations: list[dict[str, Any]] = []
        self.reset()

    def configure(self, config: dict[str, Any]) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]
        merged = {**self.config, **config}
        errors = [f"unknown setting {key!r}" for key in config if key not in DEFAULTS]
        users, roles = merged["users"], merged["roles"]
        if not isinstance(users, dict) or not users:
            errors.append("users must be a non-empty object")
        elif any(not isinstance(name, str) or not name or not isinstance(item, dict)
                 or not isinstance(item.get("role"), str) or not isinstance(item.get("enabled", True), bool)
                 for name, item in users.items()):
            errors.append("each user must have a role and optional boolean enabled field")
        if not isinstance(roles, dict) or not roles:
            errors.append("roles must be a non-empty object")
        else:
            for role, grants in roles.items():
                if not isinstance(role, str) or not isinstance(grants, dict):
                    errors.append("each role must map resource names to action lists")
                    continue
                for resource, actions in grants.items():
                    if not isinstance(resource, str) or not isinstance(actions, list) or not all(
                        isinstance(a, str) and a in {"read", "write", "execute", "delete", "admin", "*"}
                        for a in actions
                    ):
                        errors.append(f"role {role!r}: grants must be lists of valid actions")
        if isinstance(users, dict) and isinstance(roles, dict):
            for user, item in users.items():
                if isinstance(item, dict) and item.get("role") not in roles:
                    errors.append(f"user {user!r} refers to unknown role {item.get('role')!r}")
        threshold = merged["failed_login_alert_threshold"]
        if not _is_int(threshold) or threshold < 1:
            errors.append("failed_login_alert_threshold must be a positive integer")
        if errors:
            return errors
        self.config = json.loads(json.dumps(merged))
        self.reset()
        return []

    def load(self, data: Any) -> list[str]:
        if isinstance(data, (str, Path)):
            try:
                data = json.loads(Path(data).read_text())
            except (OSError, ValueError) as exc:
                return [f"cannot load security operations: {exc}"]
        if not isinstance(data, list) or not data:
            return ["security operations must be a non-empty list"]
        cleaned = []
        errors = []
        valid = {"login", "logout", "access"}
        for index, item in enumerate(data, 1):
            if not isinstance(item, dict):
                errors.append(f"Operation {index} must be an object")
                continue
            action = item.get("action")
            user = item.get("user")
            at = item.get("at", index - 1)
            if action not in valid:
                errors.append(f"Operation {index}: action must be login, logout or access")
            if not isinstance(user, str) or not user:
                errors.append(f"Operation {index}: user must be a non-empty name")
            if not _is_int(at) or at < 0:
                errors.append(f"Operation {index}: at must be a non-negative integer tick")
            resource = item.get("resource", "")
            permission = item.get("permission", "read")
            if action == "access" and (not isinstance(resource, str) or not resource):
                errors.append(f"Operation {index}: access needs a resource")
            if action == "access" and permission not in {"read", "write", "execute", "delete", "admin"}:
                errors.append(f"Operation {index}: invalid permission")
            cleaned.append({"id": str(item.get("id", f"SEC{index}")), "action": action, "user": user,
                            "at": at, "resource": resource, "permission": permission})
        if errors:
            return errors
        self.operations = cleaned
        self.reset()
        return []

    def reset(self) -> None:
        self.clock = 0
        self.cursor = 0
        self.seq = 0
        self.events: list[Event] = []
        self._audit: list[dict[str, Any]] = []
        self._alerts: list[dict[str, Any]] = []
        self._sessions: set[str] = set()
        self._failed_logins: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []

    def _record(self, at: int, operation: dict[str, Any], event_type: str, outcome: str,
                message: str, severity: str = "info", prev: str | None = None, new: str | None = None) -> None:
        self.seq += 1
        record = {"seq": self.seq, "time": at, "user": operation["user"], "action": operation["action"],
                  "resource": operation.get("resource", ""), "permission": operation.get("permission", ""),
                  "outcome": outcome, "severity": severity, "message": message}
        # Internal audit storage is only appended to. Snapshot/export return copies.
        self._audit.append(record)
        self.events.append(Event(self.seq, at, "", operation["id"], "security", event_type,
                                 operation["user"], operation["action"], prev, new, outcome, 0,
                                 severity, message))
        if severity in {"warning", "critical"}:
            self._alerts.append({"seq": self.seq, "time": at, "severity": severity,
                                 "user": operation["user"], "message": message})

    def authorize(self, user: str, resource: str, permission: str) -> bool:
        """Return whether the configured role grants the requested action."""
        entry = self.config["users"].get(user)
        if not entry or not entry.get("enabled", True):
            return False
        grants = self.config["roles"].get(entry["role"], {})
        actions = grants.get("*") or grants.get(resource) or []
        return "*" in actions or "admin" in actions or permission in actions

    def login(self, user: str, at: int = 0) -> bool:
        op = {"id": f"LOGIN-{self.seq + 1}", "action": "login", "user": user}
        entry = self.config["users"].get(user)
        if entry and entry.get("enabled", True):
            self._sessions.add(user)
            self._failed_logins[user] = 0
            self._record(at, op, "LOGIN_SUCCESS", "ok", f"{user} logged in", prev="logged_out", new="active")
            return True
        count = self._failed_logins.get(user, 0) + 1
        self._failed_logins[user] = count
        severity = "warning" if count >= self.config["failed_login_alert_threshold"] else "info"
        self._record(at, op, "LOGIN_FAILURE", "denied", f"login rejected for unknown or disabled user (attempt {count})", severity)
        if count == self.config["failed_login_alert_threshold"]:
            self._alerts.append({"seq": self.seq, "time": at, "severity": "critical", "user": user,
                                 "message": f"failed login threshold reached for {user}"})
        return False

    def logout(self, user: str, at: int = 0) -> bool:
        op = {"id": f"LOGOUT-{self.seq + 1}", "action": "logout", "user": user}
        if user not in self._sessions:
            self._record(at, op, "LOGOUT_FAILURE", "failed", f"no active session for {user}", "warning")
            return False
        self._sessions.remove(user)
        self._record(at, op, "LOGOUT_SUCCESS", "ok", f"{user} logged out", prev="active", new="logged_out")
        return True

    def check_access(self, user: str, resource: str, permission: str, at: int = 0) -> bool:
        op = {"id": f"ACCESS-{self.seq + 1}", "action": "access", "user": user,
              "resource": resource, "permission": permission}
        allowed = user in self._sessions and self.authorize(user, resource, permission)
        if allowed:
            self._record(at, op, "ACCESS_GRANTED", "ok", f"{user} granted {permission} on {resource}")
        else:
            self._record(at, op, "ACCESS_DENIED", "denied", f"{user} denied {permission} on {resource}", "warning")
        return allowed

    def step(self, event: Event | None = None) -> list[Event]:
        if event is not None:
            if event.event_type != "SECURITY_REQUEST":
                return []
            try:
                data = json.loads(event.message)
            except ValueError:
                return []
            operation = {"id": event.correlation_id or f"SEC-{self.seq + 1}",
                         "action": data.get("action", event.action), "user": event.entity_id,
                         "at": event.time, "resource": data.get("resource", ""),
                         "permission": data.get("permission", "read")}
            if operation["action"] not in {"login", "logout", "access"}:
                return []
            if operation["action"] == "access" and not operation["resource"]:
                return []
            before = len(self.events)
            self._apply(operation)
            self.clock = max(self.clock, event.time)
            return self.events[before:]
        if self.cursor >= len(self.operations):
            return []
        op = self.operations[self.cursor]
        self.cursor += 1
        before = len(self.events)
        self._apply(op)
        self.clock = max(self.clock, op["at"])
        return self.events[before:]

    def _apply(self, op: dict[str, Any]) -> None:
        action, user, at = op["action"], op["user"], op["at"]
        if action == "login":
            self.login(user, at)
        elif action == "logout":
            self.logout(user, at)
        else:
            self.check_access(user, op["resource"], op["permission"], at)

    def run(self, stop: dict[str, Any] | None = None) -> list[Event]:
        self.reset()
        stop = stop or {}
        for op in self.operations:
            if stop.get("max_time") is not None and op["at"] > stop["max_time"]:
                break
            if stop.get("max_events") is not None and self.cursor >= stop["max_events"]:
                break
            self.step()
        return list(self.events)

    def snapshot(self) -> dict[str, Any]:
        return {"clock": self.clock, "users": json.loads(json.dumps(self.config["users"])),
                "roles": json.loads(json.dumps(self.config["roles"])), "active_sessions": sorted(self._sessions),
                "audit_log": [dict(row) for row in self._audit], "alerts": [dict(row) for row in self._alerts],
                "history": [dict(row) for row in self.history]}

    def metrics(self) -> dict[str, dict[str, Any]]:
        total = len(self._audit)
        allowed = sum(row["outcome"] == "ok" for row in self._audit)
        denied = sum(row["outcome"] == "denied" for row in self._audit)
        failed = sum(row["outcome"] == "failed" for row in self._audit)
        return {"operations": {"value": total, "unit": "count"},
                "authorized": {"value": allowed, "unit": "count"},
                "denied": {"value": denied, "unit": "count"},
                "failed": {"value": failed, "unit": "count"},
                "alerts": {"value": len(self._alerts), "unit": "count"}}

    def validate(self) -> list[str]:
        warnings = []
        if not self.config["users"]:
            warnings.append("No users configured")
        if not self.operations:
            warnings.append("No security operations loaded")
        return warnings

    def export(self, fmt: str = "json") -> str:
        if fmt == "json":
            return json.dumps({"snapshot": self.snapshot(), "metrics": self.metrics(),
                               "events": [event.to_dict() for event in self.events]}, indent=2)
        if fmt == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["seq", "time", "user", "action", "resource",
                                                         "permission", "outcome", "severity", "message"])
            writer.writeheader()
            writer.writerows(self._audit)
            return output.getvalue()
        raise ValueError("export format must be json or csv")
