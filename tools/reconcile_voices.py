"""Compare the DECLARED voice catalogue against what an engine really serves.

    python3 -m tools.reconcile_voices http://127.0.0.1:8880/v1

⛔ **This exists because `narrate/engine/kokoro.py` declares its catalogue
instead of fetching it, and that trade has a cost: the declaration can drift
from the engine.** ⭐ **The trade is still right** -- validation must work with
the engine down, and `consuming.json` has to be readable without running
anything (`narrate.voices` argues both) -- ⚠️ **but a cost nobody can measure is
a cost nobody will notice.** This is the measurement.

⛔ **It is a TOOL and not a test, deliberately.** A test that reached an engine
would be a test that does not run: the suite needs no engine, no GPU and no
network, and turning that into a skip would hide a red as a dot.

Exit status is `0` when the two agree and `1` when they do not, so it can be
put in front of a release without being read by a human.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from narrate.engine.kokoro import VOICES_PATH, VOICE_IDS

TIMEOUT_SECONDS = 15.0


def fetch(base_url, timeout=TIMEOUT_SECONDS, open_url=None):
    """The voice ids one running engine reports, in the order it reports them.

    ⛔ Raises `RuntimeError` naming the endpoint and the failure, never the
    body: an engine's response is not this tool's to quote into a log.
    """
    opener = open_url if open_url is not None else urllib.request.urlopen
    url = base_url.rstrip("/") + VOICES_PATH
    try:
        with opener(url, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"the engine returned HTTP {exc.code} for {url}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"cannot read {url} ({exc.__class__.__name__})"
        ) from exc

    entries = payload.get("voices") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise RuntimeError(f"{url} did not answer with a list of voices")
    return tuple(
        entry.get("id") if isinstance(entry, dict) else entry for entry in entries
    )


def compare(declared, served):
    """`(missing, extra, order_matches)` -- what the two disagree about.

    * `missing`: declared here and NOT served. ⛔ Selectable, and every request
      naming one fails at the engine.
    * `extra`: served and not declared. ⚠️ Refused by this service, so a real
      voice is unreachable.
    """
    declared_set, served_set = set(declared), set(served)
    return (
        tuple(v for v in declared if v not in served_set),
        tuple(v for v in served if v not in declared_set),
        tuple(declared) == tuple(served),
    )


def report(base_url, declared=VOICE_IDS, fetch_ids=fetch, out=print):
    """Print the comparison. Returns a process exit status."""
    try:
        served = fetch_ids(base_url)
    except RuntimeError as exc:
        out(f"reconcile: {exc}")
        return 1

    missing, extra, ordered = compare(declared, served)
    out(f"declared {len(declared)}   served {len(served)}   "
        f"same order: {ordered}")
    out(f"declared here and NOT served: {list(missing) or 'none'}")
    out(f"served and NOT declared here: {list(extra) or 'none'}")

    if missing or extra:
        out("⛔ the declared catalogue and this engine DISAGREE")
        return 1
    if not ordered:
        # ⚠️ Not a failure. The order is cosmetic -- it decides how a menu
        # reads, never which voice a caller gets -- so it is reported and
        # does not change the verdict.
        out("⚠️ same members, different order (cosmetic)")
    out("⭐ the declared catalogue matches this engine")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "engine_url",
        help="the engine's base URL, e.g. http://127.0.0.1:8880/v1",
    )
    arguments = parser.parse_args(argv)
    return report(arguments.engine_url)


if __name__ == "__main__":
    raise SystemExit(main())
