"""File manager tests (Milestone 3). Expected values below were worked out by hand from inputs/fs_script.txt and
inputs/fs_baseline.txt before running the code; the baseline also matches expected_results/file_baseline.json."""
import csv
import io
import json

import pytest

from ossim.managers.base import INTERFACE_METHODS
from ossim.managers.file import FileManager, FileSystem, FsDenied, FsError, file_request
from ossim.managers.file import fs as fsmod

# (command, ok, output or error) for the 20 lines of inputs/fs_script.txt
HAND_STEPS = [
    ("mkdir", True, ""), ("mkdir", True, ""), ("mkdir", True, ""), ("mkfile", True, ""), ("write", True, ""),
    ("append", True, ""), ("mkfile", True, ""), ("ls", True, "docs/"), ("ls", True, "empty.txt\ntodo.txt"),
    ("cat", True, "buy milk, eggs"),
    ("mkdir", False, "already exists: /home/alice/docs"), ("mkfile", False, "no such directory: /nodir"),
    ("cat", False, "no such file: /home/alice/docs/nothing.txt"), ("rm", False, "is a directory: /home/alice/docs"),
    ("rmdir", False, "directory not empty: /home/alice/docs"),
    ("write", True, ""), ("rm", True, ""), ("rm", True, ""), ("rmdir", True, ""), ("ls", True, "alice/"),
]
HAND_TOTALS = {"operations": 20, "succeeded": 15, "failed": 5, "denied": 0, "bytes_read": 14, "bytes_written": 15,
               "files_created": 2, "dirs_created": 3, "files_deleted": 2, "dirs_deleted": 1, "storage_used": 0, "nodes": 3}


def loaded(path="inputs/fs_script.txt", **config):
    fm = FileManager()
    assert fm.configure(config) == []
    assert fm.load(path) == []
    return fm


def test_implements_the_manager_interface():
    fm = FileManager()
    assert all(callable(getattr(fm, m)) for m in INTERFACE_METHODS)
    assert fm.name == "file"


def test_script_has_at_least_12_commands_and_every_command_type():
    fm = loaded()
    assert len(fm.script) == 20
    assert {e["cmd"] for e in fm.script} == {"mkdir", "ls", "mkfile", "write", "append", "cat", "rm", "rmdir"}


def test_script_matches_hand_worked_steps():
    fm = loaded()
    fm.run()
    got = [(h["cmd"], h["ok"], h["output"] if h["ok"] else h["error"]) for h in fm.history]
    assert got == HAND_STEPS


def test_script_totals_match_hand_worked_values():
    fm = loaded()
    fm.run()
    m = {k: v["value"] for k, v in fm.metrics().items()}
    for k, v in HAND_TOTALS.items():
        assert m[k] == v, k
    # latency: 4 mkdir (20) + 3 mkfile (20) + 2 write (30) + append (30) + 3 ls (10) + 2 cat (10) + 3 rm (20) + 2 rmdir (20)
    assert fm.clock == 380
    assert m["avg_latency"] == 1.9                     # 380 ticks / 20 commands = 19 ticks = 1.9 ms


def test_per_command_latency_table():
    fm = loaded()
    fm.run()
    pc = fm.per_command()
    assert pc["mkdir"] == {"count": 4, "ok": 3, "failed": 1, "denied": 0, "total_ticks": 80, "avg_ms": 2.0}
    assert pc["ls"]["count"] == 3 and pc["ls"]["total_ticks"] == 30 and pc["ls"]["avg_ms"] == 1.0
    assert pc["rm"]["failed"] == 1 and pc["rm"]["ok"] == 2


def test_baseline_script_matches_expected_results_json():
    exp = json.load(open("expected_results/file_baseline.json"))
    fm = loaded("inputs/fs_baseline.txt")
    fm.run()
    for h, s in zip(fm.history, exp["steps"], strict=True):
        assert h["ok"] is s["ok"]
        assert (h["output"] if h["ok"] else h["error"]) == (s["output"] if s["ok"] else s["error"])
    m = {k: v["value"] for k, v in fm.metrics().items()}
    t = exp["totals"]
    for key in ("succeeded", "failed", "bytes_written", "bytes_read"):
        assert m[key] == t[key], key
    assert (m["dirs_created"], m["files_created"], m["files_deleted"], m["dirs_deleted"]) == (
        t["dirs_created"], t["files_created"], t["files_deleted"], t["dirs_deleted"])
    assert m["storage_used"] == t["final_storage_bytes"]
    assert fm.snapshot()["tree"]["children"] == exp["final_tree"]["children"]


# ---- path handling -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path,parts", [("/", []), ("/a//b/", ["a", "b"]), ("/a/./b", ["a", "b"]), ("/a/b/../c", ["a", "c"]),
                                         ("/a/b/../../", [])])
def test_path_normalization(path, parts):
    assert fsmod.split_path(path) == parts


@pytest.mark.parametrize("path,msg", [("docs", "absolute"), ("", "non-empty"), ("/..", "escapes the root"),
                                       ("/a/../../b", "escapes the root"), ("/bad name", "invalid name"),
                                       ("/x" * 40 + "/" + "n" * 65, "invalid name"), ("/a\x00b", "invalid character"),
                                       ("/" + "/".join("d" for _ in range(40)), "too deep")])
def test_bad_paths_are_rejected_safely(path, msg):
    fs = FileSystem()
    with pytest.raises(FsError, match=msg):
        fs.mkdir(path)
    assert fs.node_count == 1


def test_non_string_paths_are_rejected():
    fs = FileSystem()
    for bad in (None, 5, ["/a"]):
        with pytest.raises(FsError):
            fs.mkdir(bad)


def test_dotdot_resolves_before_lookup():
    fs = FileSystem()
    fs.mkdir("/a")
    fs.mkdir("/a/b/../c")
    assert fs.ls("/a")["output"] == "c/"          # /a/b/../c is /a/c; /a/b was never created


# ---- command errors and safe deletion ----------------------------------------------------------------------------
def test_each_command_has_a_specific_error():
    fs = FileSystem()
    fs.mkdir("/d")
    fs.mkfile("/d/f")
    cases = [
        (lambda: fs.mkdir("/"), "already exists: /"),
        (lambda: fs.mkdir("/d"), "already exists: /d"),
        (lambda: fs.mkdir("/x/y"), "no such directory: /x"),
        (lambda: fs.mkdir("/d/f/g"), "not a directory: /d/f"),
        (lambda: fs.mkfile("/d/f"), "already exists: /d/f"),
        (lambda: fs.ls("/nope"), "no such directory: /nope"),
        (lambda: fs.cat("/d"), "is a directory: /d"),
        (lambda: fs.cat("/nope"), "no such file: /nope"),
        (lambda: fs.write("/d", "x"), "is a directory: /d"),
        (lambda: fs.write("/nope", "x"), "no such file: /nope"),
        (lambda: fs.append("/nope", "x"), "no such file: /nope"),
        (lambda: fs.rm("/d"), "is a directory: /d"),
        (lambda: fs.rm("/nope"), "no such file: /nope"),
        (lambda: fs.rmdir("/d"), "directory not empty: /d"),
        (lambda: fs.rmdir("/d/f"), "not a directory: /d/f"),
        (lambda: fs.rmdir("/nope"), "no such directory: /nope"),
        (lambda: fs.rmdir("/"), "cannot remove the root"),
    ]
    for call, msg in cases:
        with pytest.raises(FsError, match=msg):
            call()
    assert fs.node_count == 3 and fs.storage == 0     # nothing changed by any failure


def test_failed_command_leaves_the_tree_unchanged():
    fm = FileManager()
    fm.load([("mkdir", ["/a"]), ("mkdir", ["/a"]), ("rmdir", ["/zzz"])])
    fm.run()
    assert [h["outcome"] for h in fm.history] == ["ok", "failed", "failed"]
    assert fm.fs.node_count == 2


def test_ls_of_a_file_names_it_and_empty_dir_is_empty():
    fs = FileSystem()
    fs.mkdir("/d")
    fs.mkfile("/d/f.txt")
    assert fs.ls("/d/f.txt")["output"] == "f.txt"
    fs.mkdir("/e")
    assert fs.ls("/e")["output"] == ""


def test_write_replaces_and_append_adds_utf8_sizes():
    fs = FileSystem()
    fs.mkfile("/f")
    assert fs.write("/f", "héllo")["bytes_written"] == 6        # é is two bytes
    assert fs.storage == 6
    fs.write("/f", "ab")
    assert fs.storage == 2 and fs.cat("/f")["output"] == "ab"
    fs.append("/f", "cd")
    assert fs.cat("/f")["output"] == "abcd" and fs.storage == 4
    fs.rm("/f")
    assert fs.storage == 0


def test_limits_are_enforced(monkeypatch):
    fs = FileSystem()
    fs.mkfile("/big")
    monkeypatch.setattr(fsmod, "MAX_FILE_BYTES", 10)
    with pytest.raises(FsError, match="exceed 10 bytes"):
        fs.write("/big", "x" * 11)
    assert fs.write("/big", "x" * 10)["bytes_written"] == 10
    with pytest.raises(FsError, match="exceed 10 bytes"):
        fs.append("/big", "y")
    assert fs.cat("/big")["output"] == "x" * 10
    monkeypatch.setattr(fsmod, "MAX_NODES", 3)
    fs.mkfile("/b")
    with pytest.raises(FsError, match="too many"):
        fs.mkfile("/c")
    monkeypatch.setattr(fsmod, "MAX_STORAGE_BYTES", 12)
    with pytest.raises(FsError, match="storage limit"):
        fs.write("/b", "zzz")


def test_host_files_are_never_touched(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("host data")
    fs = FileSystem()
    for path in (str(secret), "/../etc/passwd"):
        with pytest.raises(FsError):
            fs.cat(path)
    assert secret.read_text() == "host data"


# ---- permissions -------------------------------------------------------------------------------------------------
def _fs():
    fs = FileSystem(users={"alice": "staff", "bob": "staff", "guest": "guests"}, admins=["admin"])
    fs.mkdir("/shared")
    fs.set_mode("/shared", "775", group="staff")
    return fs


def test_owner_group_other_bits():
    fs = _fs()
    fs.mkfile("/shared/a.txt", user="alice")           # alice owns it, default 640, group staff
    fs.write("/shared/a.txt", "hi", user="alice")
    assert fs.cat("/shared/a.txt", user="bob")["output"] == "hi"          # group read
    with pytest.raises(FsDenied, match="bob cannot write"):
        fs.write("/shared/a.txt", "no", user="bob")                       # group has r only
    with pytest.raises(FsDenied, match="guest cannot read"):
        fs.cat("/shared/a.txt", user="guest")                              # other has nothing
    assert fs.cat("/shared/a.txt", user="admin")["output"] == "hi"        # admin bypass


def test_create_and_delete_need_write_on_the_parent():
    fs = _fs()
    with pytest.raises(FsDenied, match="guest cannot write /shared"):
        fs.mkfile("/shared/g.txt", user="guest")
    fs.mkfile("/shared/a.txt", user="alice")
    with pytest.raises(FsDenied):
        fs.rm("/shared/a.txt", user="guest")
    assert fs.node_count == 3
    fs.rm("/shared/a.txt", user="bob")                  # staff group has w on /shared


def test_denied_is_distinct_from_failed_and_logged():
    fm = FileManager()
    fm.load([("mkdir", ["/shared"], 0, "admin"), ("mkfile", ["/shared/x"], 0, "guest"), ("cat", ["/nope"], 0, "alice")])
    fm.run()
    assert [h["outcome"] for h in fm.history] == ["ok", "denied", "failed"]
    m = fm.metrics()
    assert (m["denied"]["value"], m["failed"]["value"]) == (1, 1)
    denied = [e for e in fm.events if e.outcome == "denied"]
    assert len(denied) == 1 and denied[0].severity == "warning"


def test_set_mode_validates_and_survives_run():
    fm = FileManager()
    fm.load([("mkfile", ["/a"], 0, "alice")])
    assert fm.set_mode("/", "777") == []
    assert fm.set_mode("/", "9") and fm.set_mode("/missing", "777")
    fm.run()
    assert fm.history[0]["outcome"] == "ok"            # alice may write to a 777 root
    fm.run()
    assert fm.history[0]["outcome"] == "ok" and fm.setup == [("/", "777", None, None)]


# ---- process requests and blocking -------------------------------------------------------------------------------
def test_process_request_blocks_then_unblocks():
    fm = FileManager()
    assert fm.load([("mkdir", ["/d"]),
                    {"cmd": "mkfile", "args": ["/d/f"], "at": 100, "user": "admin", "pid": "P2"}]) == []
    ev = fm.run()
    types = [(e.time, e.event_type, e.entity_id) for e in ev]
    assert types == [(0, "FILE_OP", "admin"), (100, "BLOCK", "P2"), (100, "FILE_OP", "P2"), (120, "UNBLOCK", "P2")]
    b, u = ev[1], ev[3]
    assert (b.prev_state, b.new_state, u.prev_state, u.new_state) == ("running", "waiting", "waiting", "ready")
    assert u.phase == "service_done"


def test_step_accepts_a_live_file_request_event():
    fm = FileManager()
    fm.load([("mkdir", ["/d"])])
    out = fm.step(file_request("P1", "mkdir", ["/live"], 50))
    assert [e.event_type for e in out] == ["BLOCK", "FILE_OP", "UNBLOCK"]
    assert fm.fs.ls("/")["output"] == "live/"
    assert fm.step(Event_stub()) == []


class Event_stub:  # noqa: N801  (any non-FILE_REQUEST event is ignored)
    event_type = "ARRIVE"


# ---- run control, snapshot, export, validation -------------------------------------------------------------------
def test_stop_conditions_never_cut_a_command_in_half():
    fm = loaded()
    assert len(fm.run({"max_events": 5})) == 5 and fm.cursor == 5
    fm.run({"max_time": 100})        # commands start at ticks 0, 20, 40, 60, 80 (+20,+20,+20,+20,+30); the 6th would start at 110
    assert fm.cursor == 5 and fm.clock == 110
    fm.run()
    assert fm.cursor == 20


def test_run_is_restartable_and_deterministic():
    fm = loaded()
    a = [e.to_dict() for e in fm.run()]
    b = [e.to_dict() for e in fm.run()]
    assert a == b and len(fm.history) == 20


def test_reset_returns_to_an_empty_tree():
    fm = loaded()
    fm.run()
    fm.reset()
    s = fm.snapshot()
    assert s["tree"]["children"] == [] and s["log"] == [] and s["clock"] == 0 and s["script_length"] == 20


def test_snapshot_is_json_and_has_metadata():
    fm = loaded()
    fm.run({"max_events": 7})
    s = fm.snapshot()
    json.dumps(s)
    node = s["tree"]["children"][0]["children"][0]["children"][0]       # /home/alice/docs
    assert node["name"] == "docs" and node["is_dir"] and node["owner"] == "admin" and node["mode"] == "750"
    todo = next(c for c in node["children"] if c["name"] == "todo.txt")
    assert todo["size"] == 14 and todo["mode"] == "640" and todo["created"] == 60 and todo["modified"] == 110
    assert s["storage_bytes"] == 14 and s["node_count"] == 6


def test_csv_export_has_one_row_per_command():
    fm = loaded()
    fm.run()
    rows = list(csv.reader(io.StringIO(fm.export("csv"))))
    assert rows[0][:5] == ["index", "time_ms", "user", "pid", "command"] and len(rows) == 21
    assert rows[11][6] == "failed" and rows[11][7] == "already exists: /home/alice/docs"
    assert json.loads(fm.export("json"))["metrics"]["operations"]["value"] == 20
    with pytest.raises(ValueError):
        fm.export("xml")


def test_load_errors_are_specific_and_change_nothing():
    fm = loaded()
    fm.run()
    assert fm.load([("mkdir", ["/a"]), ("chmod", ["/a"]), ("write", ["/a"]), ("ls", ["/", "/"]), ("rm", [5]),
                    ("mkdir", ["/b"], -1), 7]) == [
        "Command 2: unknown command 'chmod'", "Command 3: write takes 2 argument(s), got 1",
        "Command 4: ls takes 0 to 1 argument(s), got 2", "Command 5: arguments must be text",
        "Command 6: time must be a whole number of ticks, 0 or more", "Command 7: invalid entry 7"]
    assert fm.load([]) == ["Script is empty"]
    assert len(fm.script) == 20 and len(fm.history) == 20
    assert fm.load("inputs/does_not_exist.txt")


def test_bad_script_file_reports_the_line(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("mkdir /a\nformat /\n")
    assert FileManager().load(p) == [f"{p}:2: unknown command 'format'"]


def test_configure_validation():
    fm = FileManager()
    assert fm.configure({"latency_ticks": {"mkdir": -1}}) == ["latency_ticks cannot be negative"]
    assert fm.configure({"latency_ticks": {"chmod": 1}}) == ["latency_ticks must map command names to ticks"]
    assert fm.configure({"users": ["alice"]}) == ["users must map each user name to a group name"]
    assert fm.configure({"bogus": 1}) == ["unknown setting 'bogus'"]
    assert fm.config["latency_ticks"]["mkdir"] == 20          # unchanged after the errors
    assert fm.configure({"latency_ticks": {"mkdir": 5}}) == [] and fm.config["latency_ticks"]["ls"] == 10


def test_validate_warns_on_short_script_and_unknown_user():
    fm = FileManager()
    fm.load([("mkdir", ["/a"], 0, "zed")])
    w = fm.validate()
    assert any("fewer than 12" in x for x in w) and any("'zed'" in x for x in w)
    assert FileManager().validate() == ["No script loaded", "script has fewer than 12 commands (Milestone 3 asks for 12 or more)"]
