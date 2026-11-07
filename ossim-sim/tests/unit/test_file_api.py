"""File endpoint (T-FILE-API). Expected values are the hand-worked ones in test_file_manager.py."""
import csv
import io
import json

from ossim.ui.file_api import handle

SCRIPT = open("inputs/fs_script.txt").read()
BASELINE = open("inputs/fs_baseline.txt").read()


def test_run_returns_events_snapshot_metrics_and_csv():
    code, out = handle("/api/file/run", {"script": SCRIPT})
    assert code == 200
    assert out["metrics"]["operations"]["value"] == 20 and out["metrics"]["failed"]["value"] == 5
    assert len(out["events"]) == 20 and out["events"][0]["manager"] == "file"
    assert out["snapshot"]["tree"]["children"][0]["name"] == "home"
    assert len(list(csv.reader(io.StringIO(out["csv"])))) == 21
    assert out["warnings"] == []
    json.dumps(out)


def test_baseline_script_ends_with_an_empty_tree():
    code, out = handle("/api/file/run", {"script": BASELINE})
    assert code == 200 and out["snapshot"]["tree"]["children"] == [] and out["metrics"]["storage_used"]["value"] == 0


def test_user_and_setup_decide_permissions():
    script = "mkdir /shared\nmkfile /shared/a.txt\n"
    code, out = handle("/api/file/run", {"script": script, "user": "guest"})
    assert code == 200 and [h["outcome"] for h in out["snapshot"]["log"]] == ["denied", "failed"]   # /shared was never created
    code, out = handle("/api/file/run", {"script": script, "user": "alice", "setup": [{"path": "/", "mode": "775", "group": "staff"}]})
    assert [h["outcome"] for h in out["snapshot"]["log"]] == ["ok", "ok"]


def test_stop_limits():
    code, out = handle("/api/file/run", {"script": SCRIPT, "stop": {"max_events": 4}})
    assert code == 200 and len(out["events"]) == 4 and out["snapshot"]["processed"] == 4


def test_bad_requests_are_422_and_name_the_problem():
    cases = [
        ({"script": 5}, "script must be text"),
        ({}, "script must be text"),
        ({"script": "format /\n"}, "script:1: unknown command 'format'"),
        ({"script": "# only a comment\n"}, "Script is empty"),
        ({"script": "mkdir /a\n", "users": ["x"]}, "users must map each user name to a group name"),
        ({"script": "mkdir /a\n", "setup": "x"}, "setup must be a list"),
        ({"script": "mkdir /a\n", "setup": [{"path": "/"}]}, "each setup entry needs a path and a mode"),
        ({"script": "mkdir /a\n", "setup": [{"path": "/nope", "mode": "777"}]}, "no such file or directory: /nope"),
        ({"script": "mkdir /a\n", "setup": [{"path": "/", "mode": "9"}]}, "mode must be three octal digits like 640: '9'"),
        ({"script": "mkdir /a\n" * 2001}, "script is too long (limit 2000 lines)"),
        ({"script": "mkdir /a\n", "stop": {"max_events": 0}}, "stop must be"),
    ]
    for body, msg in cases:
        code, out = handle("/api/file/run", body)
        assert code == 422 and msg in out["errors"][0], (body, out)
    assert handle("/api/file/nope", {})[0] == 404


def test_host_paths_in_a_script_stay_inside_the_simulation(tmp_path):
    secret = tmp_path / "s.txt"
    secret.write_text("host data")
    code, out = handle("/api/file/run", {"script": f"cat {secret}\ncat /../etc/passwd\n"})
    assert code == 200 and [h["outcome"] for h in out["snapshot"]["log"]] == ["failed", "failed"]
    assert secret.read_text() == "host data"
