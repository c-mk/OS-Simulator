from ossim.ui.security_api import handle


def test_security_api_returns_audit_alerts_metrics_and_csv():
    code, result = handle("/api/security/run", {"operations": [
        {"action": "login", "user": "alice"},
        {"action": "access", "user": "alice", "resource": "files", "permission": "read"},
        {"action": "access", "user": "alice", "resource": "files", "permission": "delete"},
    ]})
    assert code == 200
    assert result["metrics"]["authorized"]["value"] == 2
    assert result["metrics"]["denied"]["value"] == 1
    assert result["csv"].startswith("seq,time,user,action")


def test_security_api_rejects_invalid_role_grants():
    code, result = handle("/api/security/run", {"roles": {"bad": {"files": "read"}},
                                                  "operations": [{"action": "login", "user": "alice"}]})
    assert code == 422 and "grants" in " ".join(result["errors"])
