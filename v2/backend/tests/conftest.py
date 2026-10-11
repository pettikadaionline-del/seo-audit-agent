import functools
import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

# Tests crawl a local fixture site, so private targets must be allowed and delays removed.
os.environ.setdefault("ALLOW_PRIVATE_TARGETS", "true")
os.environ.setdefault("REQUEST_DELAY_SECONDS", "0")
os.environ.setdefault("PAGESPEED_ENABLED", "false")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_seo_agent.db")

FIXTURE_DIR = Path(__file__).parent / "fixture_site"
FIXTURE_PORT = 8765  # fixture HTML hard-codes this port in canonical/sitemap URLs


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def fixture_site():
    handler = functools.partial(_Quiet, directory=str(FIXTURE_DIR))
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", FIXTURE_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{FIXTURE_PORT}/"
    server.shutdown()
    server.server_close()
