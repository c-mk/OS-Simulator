# Security Manager

The Security Manager provides a deterministic role-based access-control model for the simulator. It is simulation-only and does not authenticate real accounts or store passwords.

## Capabilities

- Users map to roles and can be enabled or disabled.
- Roles grant `read`, `write`, `execute`, `delete`, or `admin` actions on named resources; `*` grants apply to every resource.
- Login and logout operations maintain simulated active sessions.
- Access checks require an active session and a matching role grant.
- Denied access and failed logins are recorded in an append-only audit sequence.
- Repeated failed login attempts create alerts at the configured threshold.
- Snapshot, metrics, CSV audit export and JSON run export are available.

## API

`POST /api/security/run`

```json
{
  "failed_login_alert_threshold": 3,
  "operations": [
    {"action":"login", "user":"alice", "at":0},
    {"action":"access", "user":"alice", "resource":"files", "permission":"read", "at":1},
    {"action":"access", "user":"alice", "resource":"files", "permission":"delete", "at":2},
    {"action":"logout", "user":"alice", "at":3}
  ]
}
```

The response includes `events`, `snapshot` (users, roles, active sessions, audit log and alerts), `metrics`, `warnings` and `csv`. A run can be limited with the shared `stop` object.

## Default demo roles

| Role | Example grants |
| --- | --- |
| administrator | all actions on all resources |
| operator | read/write files; read/execute devices; read network |
| viewer | read files, devices and network |
| guest | read public resources only |

A successful login is required before an access check can be granted. This manager is an educational RBAC model, not production identity management.
