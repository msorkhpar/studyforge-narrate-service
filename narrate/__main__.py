"""`python3 -m narrate` -- start the service.

    python3 -m narrate serve

Everything is configured by environment variable (`narrate.config`), because
the service is deployed as a container and a container is configured by its
environment. There are no flags carrying settings, so there is no second place
a setting can come from and no question about which one wins.

⛔ **The startup banner names the bind address and the engine address, and
nothing else.** Not the artifact directory's absolute path, not the
environment: a startup line is the most-copied line in any operator's terminal.
"""

from __future__ import annotations

import sys

from .config import ConfigError, from_environment
from .server import build_server

USAGE = "usage: python3 -m narrate serve"


def main(argv=None):
    """Return a process exit status. Never raises for a usage or config error."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["serve"]:
        print(USAGE, file=sys.stderr)
        return 2

    try:
        config = from_environment()
    except ConfigError as exc:
        print(f"narrate: {exc}", file=sys.stderr)
        return 2

    def log(line):
        print(f"narrate: {line}", flush=True)

    server = build_server(config, log=log)
    host, port = server.server_address[:2]
    print(
        f"narrate: serving on http://{host}:{port} "
        f"-> engine {config.engine_url}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("narrate: stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
