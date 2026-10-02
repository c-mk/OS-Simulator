"""Invalid input fails safely with specific messages (VU-01, TS-04)."""
import pytest

from ossim.io.loaders import InputError, load_processes_csv, load_trace


@pytest.mark.parametrize("body,msg", [
    ("pid,arrival,burst\nP1,0,8\n", "header"),
    ("pid,arrival,burst,priority\nP1,0,8,1\nP1,1,2,1\n", "duplicate"),
    ("pid,arrival,burst,priority\nP1,0,x,1\n", "integers"),
    ("pid,arrival,burst,priority\nP1,-1,8,1\n", ">= 0"),
    ("pid,arrival,burst,priority\nP1,0,8\n", "fields"),
    ("pid,arrival,burst,priority\n", "no processes"),
])
def test_bad_process_files(tmp_path, body, msg):
    f = tmp_path / "p.csv"
    f.write_text(body)
    with pytest.raises(InputError, match=msg):
        load_processes_csv(f)


def test_bad_trace(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("0x10\nzz\n")
    with pytest.raises(InputError, match="line|2"):
        load_trace(f)
