"""Fixtures shared by the modules that talk to a running server.

⭐ **The server is started on port 0 and talked to over a real socket**, so
these are end-to-end HTTP assertions rather than handler-method calls: the
status line, the headers and the body are what a caller actually receives. The
engine is faked, so the suite needs no running engine and no GPU.

⚠️ **`service` lives here rather than in `test_server.py` because two modules
now need it** -- the route tests and the job-route tests. Duplicating a
thirty-line fixture is how the two copies come to disagree about what a running
service is.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from narrate.config import Config
from narrate.server import build_server
from tests.support import FakeEngine


@pytest.fixture
def service(tmp_path):
    """A running server and a `request(method, path, body)` helper."""
    made = {}

    def start(engine=None, chunk_chars=1800, artifact_dir=None):
        config = Config(artifact_dir=artifact_dir or tmp_path,
                        bind="127.0.0.1", port=0, chunk_chars=chunk_chars)
        server = build_server(config, engine=engine or FakeEngine())
        made["server"] = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]

        def request(method, path, body=None, headers=None, raw_body=None):
            connection = http.client.HTTPConnection(host, port, timeout=30)
            if raw_body is not None:
                payload = raw_body
            else:
                payload = None if body is None else json.dumps(body).encode("utf-8")
            connection.request(method, path, payload, headers or (
                {"Content-Type": "application/json"} if payload else {}
            ))
            response = connection.getresponse()
            data = response.read()
            connection.close()
            return response, data

        return request

    yield start

    server = made.get("server")
    if server is not None:
        server.shutdown()
        server.server_close()
