"""What an agent can call, and what each call actually does.

Three tools, and each is a thin skin over a function the HTTP service calls
too, so there is one implementation of synthesis and one cache:

| tool | |
|---|---|
| `synthesize` | one text -> one artifact. `narrate.synthesis.synthesise` |
| `narrate_batch` | keyed segments -> a manifest. `narrate.jobs.run_job` |
| `voices` | the catalogue. ⭐ Needs no engine and cannot fail |

⛔ **A FAILED SYNTHESIS IS `isError` CONTENT, NOT A JSON-RPC ERROR.** The call
was well formed and the work did not succeed; the client should show the reason
to the model rather than treat it as a protocol fault. ⚠️ **A JSON-RPC error is
reserved for a malformed call** -- an unknown tool, or a request this module
cannot parse as one.

⛔ **NO PATH OUTSIDE THE STORE IS EVER RETURNED, and no absolute one.** The
adapter answers with the content address, the service-relative URL and the
file's name within the store. A store directory is either a container path or
somebody's home directory (R7), and the caller does not need it: `narrate`
returns artifacts and never decides where they land (R4).
"""

from __future__ import annotations

from ..artifacts import ArtifactStore
from ..config import FORMAT_MEDIA_TYPES, SUPPORTED_FORMATS, from_environment
from ..engine import EngineError, build_engine
from ..jobs import InvalidJob, parse_job, run_job
from ..synthesis import UnsupportedFormat, synthesise
from ..voices import UnknownVoice

#: ⛔ Repeated in every tool description because it is the one obligation this
#: surface cannot discharge for its caller. See the package docstring.
GATE_NOTE = (
    "The caller gates personal data OUT of the text before calling: this "
    "service never inspects it, and speech that names a person cannot be "
    "searched for once it is on disk."
)


class UnknownTool(LookupError):
    """No tool by that name. ⛔ A protocol-level error, not a tool failure."""


TOOLS = [
    {
        "name": "synthesize",
        "description": (
            "Speak one text and store it as an audio artifact. Returns the "
            "artifact's content address, its URL on the narrate service, and "
            "its duration. Text of any length is accepted -- splitting is the "
            "service's job. Re-submitting unchanged text synthesises nothing "
            "and returns the same address. " + GATE_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to speak."},
                "voice": {
                    "type": "string",
                    "description": (
                        "A voice id from the `voices` tool. Omit for the "
                        "deployment's default. An unknown id is refused."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": list(SUPPORTED_FORMATS),
                    "description": "Audio format. Defaults to mp3.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "narrate_batch",
        "description": (
            "Speak many keyed segments in one call and return a manifest: one "
            "entry per submitted id, in submission order, each with its own "
            "content address. Prefer this over repeated `synthesize` calls -- "
            "per-request overhead is the difference between minutes and hours "
            "for a corpus. Read `counts`, not the outcome of any one segment. "
            + GATE_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "Objects with a unique `id` and a `text`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["id", "text"],
                    },
                },
                "voice": {
                    "type": "string",
                    "description": (
                        "A voice id from the `voices` tool, applied to every "
                        "segment. An unknown id refuses the whole job."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": list(SUPPORTED_FORMATS),
                    "description": "Audio format. Defaults to mp3.",
                },
            },
            "required": ["segments"],
        },
    },
    {
        "name": "voices",
        "description": (
            "List the voices this deployment can speak and which one it uses "
            "by default. Call this before `synthesize` if you intend to name "
            "a voice: an unknown id is refused rather than silently defaulted."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class Adapter:
    """One engine, one store and one catalogue, built once per process.

    ⛔ **Built from the same environment `serve` reads**, so an agent and a
    deployment configured alike address artifacts identically -- which is what
    makes an agent's one-off narration a cache hit for a later corpus build.
    """

    def __init__(self, config=None, engine=None):
        self.config = config if config is not None else from_environment()
        self.engine = engine if engine is not None else build_engine(self.config)
        self.catalogue = self.engine.voices()
        # ⛔ At construction, so a misspelled NARRATE_VOICE refuses to start
        # this adapter rather than failing every call it is ever sent -- the
        # same gate `build_server` applies to the HTTP path.
        self.catalogue.require(self.config.voice)
        self.store = ArtifactStore(self.config.artifact_dir)

    # -- tools ------------------------------------------------------------

    def synthesize(self, arguments):
        text = arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        voice = arguments.get("voice") or self.config.voice
        fmt = arguments.get("format") or SUPPORTED_FORMATS[0]
        self.catalogue.require(voice)

        result = synthesise(
            text, voice, fmt,
            engine=self.engine, store=self.store,
            chunk_chars=self.config.chunk_chars,
            media_types=FORMAT_MEDIA_TYPES,
            keep_audio=False,
        )
        summary = result.summary()
        return {
            "artifact_id": summary["artifact_id"],
            "url": summary["url"],
            # ⛔ The name WITHIN the store, never the directory holding it.
            "file": self.store.path_for(summary["artifact_id"]).name,
            "voice": summary["voice"],
            "format": summary["format"],
            "bytes": summary["bytes"],
            "seconds": summary["seconds"],
            "chunks": summary["chunks"],
            "cached": summary["cached"],
            "engine": summary["engine"],
            "engine_model": summary["engine_model"],
        }

    def narrate_batch(self, arguments):
        job = parse_job(arguments, default_voice=self.config.voice,
                        catalogue=self.catalogue)
        return run_job(
            job,
            engine=self.engine, store=self.store,
            chunk_chars=self.config.chunk_chars,
            media_types=FORMAT_MEDIA_TYPES,
            provides=_provides(),
        )

    def voices(self, arguments):
        return {
            "engine": self.engine.name,
            "default": self.config.voice,
            "voices": self.catalogue.listing(),
        }


def _provides():
    """The promise version, read from its single source."""
    from .. import PROVIDES
    return PROVIDES


#: Tool name -> the `Adapter` method that runs it. ⛔ A closed table, for the
#: reason `engine/registry.py` is one: a name arrives from a client, and
#: dispatching by `getattr` would turn it into an instruction to call an
#: arbitrary method.
DISPATCH = {
    "synthesize": Adapter.synthesize,
    "narrate_batch": Adapter.narrate_batch,
    "voices": Adapter.voices,
}


def call_tool(adapter, name, arguments):
    """Run one tool. Returns `(payload, is_error)`.

    ⛔ Raises `UnknownTool` for a name outside `DISPATCH` -- that is a protocol
    fault and not a failed synthesis. Everything a caller could get wrong
    about a well-formed call comes back as `(message, True)`.
    """
    try:
        method = DISPATCH[name]
    except KeyError:
        raise UnknownTool(
            "tool must be one of: " + ", ".join(DISPATCH)
        ) from None

    try:
        return method(adapter, arguments or {}), False
    except (UnknownVoice, InvalidJob, UnsupportedFormat, ValueError) as exc:
        return str(exc), True
    except EngineError as exc:
        return str(exc), True
