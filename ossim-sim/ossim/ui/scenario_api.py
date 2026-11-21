"""Early six-manager scenario: process/memory/file integration plus security, device and network."""
from __future__ import annotations
from typing import Any

from ossim.ui import device_api, integration_api, network_api, security_api


def handle(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if path != "/api/scenario/run":
        return 404, {"errors": ["unknown endpoint"]}
    for key in ("security", "device", "network"):
        if not isinstance(body.get(key), dict):
            return 422, {"errors": [f"{key} must be an object"]}
    code, integrated = integration_api.handle("/api/integration/run", body)
    if code != 200:
        return code, integrated
    code, security = security_api.handle("/api/security/run", body["security"])
    if code != 200:
        return code, security
    code, device = device_api.handle("/api/device/run", body["device"])
    if code != 200:
        return code, device
    code, network = network_api.handle("/api/network/run", body["network"])
    if code != 200:
        return code, network

    # Merge independent manager streams for a shared, inspectable timeline.
    streams = [integrated["events"], security["events"], device["events"], network["events"]]
    rows = [event for stream in streams for event in stream]
    manager_order = {name: i for i, name in enumerate(("process", "memory", "file", "security", "device", "network"))}
    rows.sort(key=lambda event: (event["time"], manager_order.get(event["manager"], 99), event["seq"]))
    events = [{**event, "seq": index} for index, event in enumerate(rows, 1)]
    return 200, {
        "scenario": "six-manager-early-integration",
        "events": events,
        "managers": {
            "process": integrated["process"], "memory": integrated["memory"], "file": integrated["file"],
            "security": {"snapshot": security["snapshot"], "metrics": security["metrics"]},
            "device": {"snapshot": device["snapshot"], "metrics": device["metrics"]},
            "network": {"snapshot": network["snapshot"], "metrics": network["metrics"]},
        },
        "blocked": integrated["blocked"], "per_process": integrated["per_process"],
        "warnings": integrated["warnings"] + security["warnings"] + device["warnings"] + network["warnings"],
        "integration_boundary": (
            "This is an early integration: all six manager outputs share one ordered event timeline, but device, "
            "network and security outcomes do not yet feed back into CPU scheduling or mutate another manager's state."
        ),
    }
