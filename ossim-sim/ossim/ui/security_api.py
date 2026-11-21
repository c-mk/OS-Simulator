"""Dashboard API for RBAC security, access checks, alerts and audit history."""
from __future__ import annotations
from typing import Any

from ossim.managers.security import SecurityManager
from ossim.ui.memory_api import valid_stop


def handle(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if path != "/api/security/run":
        return 404, {"errors": ["unknown endpoint"]}
    stop = body.get("stop")
    if stop is not None and not valid_stop(stop):
        return 422, {"errors": ["stop must contain positive integer max_time and/or max_events"]}
    manager = SecurityManager()
    config = {key: body[key] for key in ("users", "roles", "failed_login_alert_threshold") if key in body}
    errors = manager.configure(config)
    if errors:
        return 422, {"errors": errors}
    errors = manager.load(body.get("operations"))
    if errors:
        return 422, {"errors": errors}
    events = manager.run(stop)
    return 200, {"events": [event.to_dict() for event in events], "snapshot": manager.snapshot(),
                 "metrics": manager.metrics(), "warnings": manager.validate(), "csv": manager.export("csv")}
