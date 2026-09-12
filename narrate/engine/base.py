"""The engine adapter contract, written down and checked at startup.

⭐ **Everything above this package speaks to three members and knows nothing
else about how audio is made**: `synthesize_chunk(text, voice, fmt)`,
`reachable()`, and `identity()`. An adapter for a different speech engine is a
new module in this package that provides those three; it is never a change to
the API, the chunker, the store or the server.

⛔ **It is a duck-typed contract with a RUNTIME GATE, deliberately, and not an
abstract base class.** An ABC is enforced at subclass definition, which is the
wrong moment: the object that actually reaches the server may arrive from the
registry, from a test, or from a caller of `build_server(config, engine=...)`,
which is public. `check_engine` is called on whatever object that is, so a
missing member is a refusal at startup naming what is absent, rather than an
`AttributeError` on the first request that a caller sees as a `500`.

## What an adapter must provide

| member | |
|---|---|
| `name` | the engine family, a short lowercase id. `"kokoro"` |
| `synthesize_chunk(text, voice, fmt)` | bytes for ONE chunk. Raises `EngineError` on every failure. Never splits, never joins, never writes |
| `reachable()` | whether the engine answers at all. ⛔ **Never raises** |
| `identity()` | an `EngineIdentity` — what produced an artifact |

⚠️ **`identity()`'s `profile` is a DECLARATION, not a detection, and this is the
one place a reader could be misled.** The service is on the far side of an HTTP
boundary from its engine: it cannot see whether that engine has a GPU, and any
claim that it can would be a claim about somebody else's container. What the
service guarantees is narrower and still worth having — the value came from a
closed set, it was declared by the deployment that chose the engine image, and
⭐ **the same value is reported on `GET /healthz` and on every artifact**, so a
caller that records it beside an artifact records what the deployment said the
artifact was made on. ⛔ **A deployment that declares nothing reports
`unknown`** rather than defaulting to a hardware claim that would be a guess.
"""

from __future__ import annotations

from dataclasses import dataclass


class NotAnEngine(TypeError):
    """An object offered as an engine does not satisfy the adapter contract."""


#: The three members, plus the family name. Checked in this order so the
#: message names the first thing missing rather than all of them at once.
ADAPTER_MEMBERS = ("name", "synthesize_chunk", "reachable", "identity")

#: Members that must additionally be callable.
ADAPTER_METHODS = ("synthesize_chunk", "reachable", "identity")


@dataclass(frozen=True)
class EngineIdentity:
    """What made an artifact, in the three parts a caller may want separately.

    ⭐ **Three fields rather than one string**, because a consumer that records
    these beside an artifact asks different questions of each: *which engine
    family* decides whether a voice id means anything, *which profile* is the
    hardware question, and *which model* is the one that changes what the audio
    sounds like without either of the other two moving.
    """

    #: The engine family. `"kokoro"`.
    engine: str
    #: `"cpu"`, `"gpu"`, or `"unknown"` -- declared by the deployment.
    profile: str
    #: The model the engine is asked for, as the engine names it.
    model: str

    @property
    def label(self):
        """The one-line form, for a header and for a log. `"kokoro/cpu"`."""
        return f"{self.engine}/{self.profile}"

    def as_dict(self):
        """The JSON shape, for `GET /healthz`."""
        return {
            "engine": self.engine,
            "engine_profile": self.profile,
            "engine_model": self.model,
        }


def check_engine(engine):
    """Return `engine`, or raise `NotAnEngine` naming what it is missing.

    ⛔ **The message names the CONTRACT and never the object**: an engine
    instance carries a base URL, and a URL in a refusal is a deployment
    detail in whatever log the operator pastes somewhere.
    """
    for member in ADAPTER_MEMBERS:
        if not hasattr(engine, member):
            raise NotAnEngine(
                f"an engine must provide {member!r}; the contract is "
                f"{', '.join(ADAPTER_MEMBERS)}"
            )
    for method in ADAPTER_METHODS:
        if not callable(getattr(engine, method)):
            raise NotAnEngine(f"an engine's {method!r} must be callable")
    return engine
