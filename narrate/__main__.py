"""`python3 -m narrate` -- start the service, or the agent adapter.

    python3 -m narrate serve      the HTTP service. This is the deployment
    python3 -m narrate agent      the agent-callable adapter, on stdio

Everything is configured by environment variable (`narrate.config`), because
the service is deployed as a container and a container is configured by its
environment. There are no flags carrying settings, so there is no second place
a setting can come from and no question about which one wins.

⛔ **The startup banner names the bind address and the engine address, and
nothing else.** Not the artifact directory's absolute path, not the
environment: a startup line is the most-copied line in any operator's terminal.

## ⛔ `narrate.agent` IS IMPORTED INSIDE ITS OWN BRANCH, AND THAT IS THE ROW

`NS-06`'s acceptance says *"the adapter is optional -- the service works fully
without it"*, and an import at the top of this file would make that a claim
rather than a property. ⭐ **Imported here, one line inside the `agent` branch,
it is CHECKABLE**: start the serve path in a fresh interpreter and
`narrate.agent` is absent from `sys.modules`. ⚠️ **That is exactly the assertion
`tests/test_agent.py` makes, in a subprocess**, because an in-process one would
be answered by whatever the rest of the suite had already imported.
"""

from __future__ import annotations

import sys

from .config import ConfigError, from_environment
from .server import build_server
from .voices import UnknownVoice

USAGE = "usage: python3 -m narrate {serve|agent}"

COMMANDS = ("serve", "agent")


def main(argv=None):
    """Return a process exit status. Never raises for a usage or config error."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in COMMANDS:
        print(USAGE, file=sys.stderr)
        return 2

    if args[0] == "agent":
        # ⛔ Imported HERE and nowhere above. See the module docstring: this
        # one line is what makes "the adapter is optional" a property of the
        # serve path rather than a sentence about it.
        from .agent import run_adapter
        return run_adapter()

    return _serve()


def _serve():
    """The HTTP service. ⛔ Never imports the agent adapter."""
    try:
        config = from_environment()
    except ConfigError as exc:
        print(f"narrate: {exc}", file=sys.stderr)
        return 2

    def log(line):
        print(f"narrate: {line}", flush=True)

    try:
        server = build_server(config, log=log)
    except UnknownVoice as exc:
        # ⛔ A misspelled NARRATE_VOICE refuses to start naming what is
        # permitted, rather than coming up healthy and mis-serving every
        # request that omitted a voice.
        print(f"narrate: {exc}", file=sys.stderr)
        return 2
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
