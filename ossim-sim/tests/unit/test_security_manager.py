from ossim.managers.security import SecurityManager


def test_roles_permissions_login_and_append_only_audit():
    manager = SecurityManager()
    assert manager.load([
        {"action": "login", "user": "alice", "at": 0},
        {"action": "access", "user": "alice", "resource": "files", "permission": "read", "at": 1},
        {"action": "access", "user": "alice", "resource": "files", "permission": "delete", "at": 2},
        {"action": "logout", "user": "alice", "at": 3},
    ]) == []
    events = manager.run()
    assert [event.outcome for event in events] == ["ok", "ok", "denied", "ok"]
    snapshot = manager.snapshot()
    assert len(snapshot["audit_log"]) == 4
    snapshot["audit_log"].clear()
    assert len(manager.snapshot()["audit_log"]) == 4
    assert manager.metrics()["denied"]["value"] == 1


def test_repeated_failed_logins_create_alert():
    manager = SecurityManager()
    assert manager.load([{"action": "login", "user": "intruder", "at": i} for i in range(3)]) == []
    manager.run()
    assert any(alert["severity"] == "critical" for alert in manager.snapshot()["alerts"])
    assert manager.metrics()["denied"]["value"] == 3


def test_configuration_and_input_validation_are_atomic():
    manager = SecurityManager()
    before = manager.config.copy()
    assert manager.configure({"failed_login_alert_threshold": 0})
    assert manager.config == before
    assert manager.load([{"action": "delete", "user": "alice"}])
    assert manager.operations == []


def test_disabled_user_cannot_login_or_access():
    manager = SecurityManager()
    assert manager.configure({"users": {"alice": {"role": "operator", "enabled": False}},
                              "roles": {"operator": {"files": ["read"]}}}) == []
    assert manager.load([{"action": "login", "user": "alice"},
                         {"action": "access", "user": "alice", "resource": "files"}]) == []
    manager.run()
    assert [row["outcome"] for row in manager.snapshot()["audit_log"]] == ["denied", "denied"]


def test_step_processes_one_security_request_without_resetting_loaded_work():
    from ossim.core.events import Event

    manager = SecurityManager()
    assert manager.load([{"action": "login", "user": "alice", "at": 0},
                         {"action": "logout", "user": "alice", "at": 2}]) == []
    first = manager.step()
    assert len(first) == 1 and first[0].event_type == "LOGIN_SUCCESS"
    request = Event(0, 1, "", "req-1", "process", "SECURITY_REQUEST", "alice", "access",
                    None, None, "ok", message='{"action":"access","resource":"files","permission":"read"}')
    second = manager.step(request)
    assert len(second) == 1 and second[0].event_type == "ACCESS_GRANTED"
    assert manager.cursor == 1  # The next loaded logout remains queued.
