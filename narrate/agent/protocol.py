"""The stdio tool protocol: newline-delimited JSON-RPC 2.0, and nothing else.

⚠️ **One compact JSON object per line, in both directions.** It is *not* the
LSP-style `Content-Length:` header framing that most JSON-RPC sample code uses;
the two share ancestry, and a server built from an LSP example hangs at the
handshake with no useful error. Four messages are the whole surface a tool
server needs: `initialize`, the `notifications/initialized` notification,
`tools/list` and `tools/call`.

## ⛔ THE ONE RULE THIS MODULE EXISTS TO KEEP

**The protocol stream carries protocol bytes and nothing else.** ⭐ `run_adapter`
rebinds `sys.stdout` to stderr for the whole run and hands the real handle to
`serve_stdio` privately, so a print anywhere beneath this package -- in the
chunker, in an engine adapter, in the store, in a library -- lands on stderr as
a log line instead of corrupting the transport. ⚠️ **The failure it prevents is
silent from the client's side**: the connection drops reporting a parse error,
and nothing names the print.

⛔ **`serve_stdio` writes to the handle it is GIVEN and never to `sys.stdout`.**
That is what makes the property testable: the test drives it with a synthesis
function that prints, and asserts every byte the client received parses as
JSON.

⛔ **The loop never dies of one bad message.** An unparseable line is logged to
stderr and skipped; an exception raised while handling a request becomes a
JSON-RPC error response. A tool server that exits on a malformed line takes the
whole session with it.
"""

from __future__ import annotations

import json
import sys

from .tools import TOOLS, UnknownTool, call_tool

SERVER_NAME = "narrate-service"
SERVER_VERSION = "0.1.0"

#: Echoed back to a client that does not name one itself.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _result(request_id, payload):
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _content(payload, is_error=False):
    """A tool result. ⭐ JSON in the text, so it is readable by both ends."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle(message, adapter):
    """One decoded message -> a response, or `None` for a notification.

    ⛔ Never raises for anything a client can send. A tool that fails answers
    with `isError` content; a method or tool that does not exist answers with
    a JSON-RPC error.
    """
    method = message.get("method")
    request_id = message.get("id")

    if request_id is None:
        return None                       # a notification; never answered

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        return _result(request_id, {
            "protocolVersion": requested or DEFAULT_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params") or {}
        try:
            payload, is_error = call_tool(
                adapter, params.get("name"), params.get("arguments")
            )
        except UnknownTool as exc:
            return _error(request_id, METHOD_NOT_FOUND, str(exc))
        except Exception as exc:                       # never kill the loop
            return _error(request_id, INTERNAL_ERROR, str(exc))
        return _result(request_id, _content(payload, is_error))

    return _error(request_id, METHOD_NOT_FOUND, f"unknown method: {method!r}")


def serve_stdio(source, sink, adapter, log=None):
    """Read JSON-RPC lines from `source`, write responses to `sink`.

    ⛔ **`sink` is the only thing this function writes protocol bytes to**, and
    it is passed in rather than taken from `sys.stdout` -- which is what makes
    the *"a print does not break the transport"* property assertable.
    """
    note = log if log is not None else _stderr

    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError as exc:
            # ⛔ Skipped, not fatal, and the reason goes to stderr rather than
            # into the stream the client is parsing.
            note(f"[{SERVER_NAME}] dropping unparseable line: {exc}")
            continue
        if not isinstance(message, dict):
            note(f"[{SERVER_NAME}] dropping a line that is not an object")
            continue

        response = handle(message, adapter)
        if response is None:
            continue
        sink.write(json.dumps(response) + "\n")
        sink.flush()


def _stderr(line):
    print(line, file=sys.stderr, flush=True)


def run_adapter(source=None, sink=None, adapter=None):
    """Run the adapter on stdio. Returns a process exit status.

    ⛔ **The rebinding is the FIRST thing that happens and it happens before
    the adapter is built**, because building it constructs an engine and a
    store and either of those could print. ⭐ The real handle is kept locally
    and handed to `serve_stdio`; nothing else can reach it.
    """
    from ..config import ConfigError
    from ..voices import UnknownVoice
    from .tools import Adapter

    real_stdout = sink if sink is not None else sys.stdout
    real_stdin = source if source is not None else sys.stdin

    # ⛔ Protocol bytes only: anything that prints from here on lands on
    # stderr. See the module docstring; this single line is the carried lesson.
    sys.stdout = sys.stderr

    if adapter is None:
        try:
            adapter = Adapter()
        except (ConfigError, UnknownVoice) as exc:
            print(f"narrate: {exc}", file=sys.stderr, flush=True)
            return 2

    serve_stdio(real_stdin, real_stdout, adapter)
    return 0
