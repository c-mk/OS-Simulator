"""SC-01: simulator code must not touch the host (no subprocess, sockets, os.system)."""
import re
from pathlib import Path

BANNED = re.compile(r"\b(import subprocess|from subprocess|os\.system|import socket|from socket|shutil\.rmtree)\b")


def test_no_host_access_in_source():
    src = Path(__file__).resolve().parents[1] / "ossim"
    hits = [str(p) for p in src.rglob("*.py") if BANNED.search(p.read_text())]
    assert hits == []
