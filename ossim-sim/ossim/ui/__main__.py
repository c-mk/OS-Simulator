"""Serve the dashboard prototype on localhost only: python -m ossim.ui  (then open http://127.0.0.1:8000)."""
import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).parent / "prototype"

if __name__ == "__main__":
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler) as srv:
        print("Dashboard prototype at http://127.0.0.1:8000  (Ctrl+C to stop)")
        srv.serve_forever()
