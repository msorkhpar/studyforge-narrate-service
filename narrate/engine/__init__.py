"""The speech engine, behind one seam.

⭐ **Everything above this package speaks to three members and knows nothing
else about how audio is made** -- `synthesize_chunk(text, voice, fmt)`,
`reachable()` and `identity()`. The contract is written down in `base.py` and
checked at startup; which adapter a deployment gets is `registry.py`, chosen by
`NARRATE_ENGINE` and by nothing in the code above this package.

| module | |
|---|---|
| `base.py` | the contract, `EngineIdentity`, and the startup gate |
| `registry.py` | engine family -> adapter. ⛔ A closed set, not a plugin loader |
| `kokoro.py` | Kokoro over its OpenAI-shaped HTTP API |
| `errors.py` | the three failures, told apart because callers act differently |

⭐ **THE CPU AND GPU PROFILES ARE NOT MODULES HERE, AND THAT IS THE RESULT
RATHER THAN AN OMISSION.** Kokoro's CPU and GPU images speak one request shape,
so both profiles run *this same adapter*: what differs between them is the
engine image, the device reservation and the declared profile label, all of it
in `compose.yaml` and `compose.gpu.yaml`. ⛔ **If a profile needed its own class
here, switching profiles would be a code change** -- which is precisely what
`NS-03`'s *"switching profiles is a deployment choice, not a code change"*
forbids. The seam this package exists for is the one a **different engine**
crosses, and that one is `registry.py`.

⛔ **What is still deliberately absent**: an entry-point scan, and any
import-by-name from an environment variable. Adding an engine is a line in
`ENGINES` in the same commit as the adapter it names.
"""

from .base import (
    ADAPTER_MEMBERS,
    ADAPTER_METHODS,
    EngineIdentity,
    NotAnEngine,
    check_engine,
)
from .errors import EngineError, EngineFailed, EngineUnavailable
from .kokoro import KokoroEngine
from .registry import ENGINES, UnknownEngine, build_engine, engine_names

__all__ = [
    "ADAPTER_MEMBERS",
    "ADAPTER_METHODS",
    "ENGINES",
    "EngineError",
    "EngineFailed",
    "EngineIdentity",
    "EngineUnavailable",
    "KokoroEngine",
    "NotAnEngine",
    "UnknownEngine",
    "build_engine",
    "check_engine",
    "engine_names",
]
