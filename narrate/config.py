"""Where the service's settings come from, and what each one is permitted to be.

Every setting has a default that works on a developer's machine and an
environment variable that overrides it, because the service is deployed as a
container and a container is configured by its environment.

⛔ **No path in this module is absolute-by-default except the container's own
artifact directory**, which is a path inside an image rather than a fact about
anybody's disk. Anything derived from a home directory is personal data and is
never written down here or anywhere else in this repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: The engine's OpenAI-shaped speech API. The service is the only thing that
#: ever talks to it; a caller of this service never learns this address.
DEFAULT_ENGINE_URL = "http://127.0.0.1:8880/v1"

#: Loopback only, and this is not a default to be casually widened: the service
#: has no authentication of its own. Publishing it on every interface is a
#: deployment decision somebody makes explicitly, never one that happens by
#: leaving a setting alone.
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8870

DEFAULT_VOICE = "am_liam"

#: ⛔ A closed set, for the same reason `SUPPORTED_FORMATS` is one: an unknown
#: value here must be refused at startup naming what is permitted, never
#: accepted and discovered on the first request. `narrate.engine.registry` is
#: the table this is the validation half of.
SUPPORTED_ENGINES = ("kokoro",)

DEFAULT_ENGINE = "kokoro"

#: ⛔ **A declared label, never a detected one.** The service reaches its engine
#: over HTTP and cannot see the hardware on the other side; what it can do is
#: report what the deployment that chose the engine image said, identically on
#: `GET /healthz` and on every artifact. `unknown` is the default precisely so
#: that a deployment which declares nothing does not silently make a hardware
#: claim -- and it is a legitimate value rather than an error: the service runs
#: perfectly well against an engine whose hardware nobody has declared.
ENGINE_PROFILES = ("cpu", "gpu", "unknown")

DEFAULT_ENGINE_PROFILE = "unknown"

#: Characters per chunk. The engine accepts far more than this in one request,
#: but the splitting is deliberately ours (see the package docstring), and a
#: budget the engine comfortably clears keeps a chunk boundary from ever being
#: the thing that fails a long synthesis.
DEFAULT_CHUNK_CHARS = 1800

#: Synthesis runs at roughly a second per thousand characters, so a long text
#: legitimately takes minutes. Generous by default, overridable for tests.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: ⛔ A closed set, not a blacklist. `mp3` is an MPEG elementary stream, which
#: is a sequence of independently decodable frames -- so the chunks of one
#: synthesis concatenate into one playable artifact with no muxer. A container
#: format such as `wav` or `flac` carries a header describing the whole file
#: and cannot be concatenated that way; supporting one means a real muxer, and
#: a half-supported format that produces a broken file for long input is worse
#: than a refusal that names what is permitted.
SUPPORTED_FORMATS = ("mp3",)

#: The media type each supported format is served as.
FORMAT_MEDIA_TYPES = {"mp3": "audio/mpeg"}


class ConfigError(ValueError):
    """A setting was present and not usable. Nothing started."""


@dataclass(frozen=True)
class Config:
    """Everything the service needs to run, resolved once at startup."""

    engine: str = DEFAULT_ENGINE
    engine_url: str = DEFAULT_ENGINE_URL
    engine_profile: str = DEFAULT_ENGINE_PROFILE
    artifact_dir: Path = Path("artifacts")
    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    voice: str = DEFAULT_VOICE
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    timeout: float = DEFAULT_TIMEOUT_SECONDS


def _positive_int(name, raw, minimum=1):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a whole number") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _one_of(name, raw, permitted):
    """⛔ Names what is PERMITTED and never echoes what arrived."""
    if raw not in permitted:
        raise ConfigError(f"{name} must be one of: {', '.join(permitted)}")
    return raw


def _positive_float(name, raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a number") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def from_environment(environ=None):
    """Build a `Config` from the process environment.

    ⛔ A refusal here names what is **permitted** and never echoes what
    arrived: an environment variable is exactly the place an account
    identifier or a home path turns up, and a message quoting it would copy
    that into the log the operator then pastes somewhere.
    """
    env = os.environ if environ is None else environ
    defaults = Config()

    port = defaults.port
    if env.get("NARRATE_PORT"):
        port = _positive_int("NARRATE_PORT", env["NARRATE_PORT"])
        if port > 65535:
            raise ConfigError("NARRATE_PORT must be between 1 and 65535")

    chunk_chars = defaults.chunk_chars
    if env.get("NARRATE_CHUNK_CHARS"):
        chunk_chars = _positive_int(
            "NARRATE_CHUNK_CHARS", env["NARRATE_CHUNK_CHARS"], minimum=64
        )

    timeout = defaults.timeout
    if env.get("NARRATE_TIMEOUT_SECONDS"):
        timeout = _positive_float(
            "NARRATE_TIMEOUT_SECONDS", env["NARRATE_TIMEOUT_SECONDS"]
        )

    artifact_dir = defaults.artifact_dir
    if env.get("NARRATE_ARTIFACT_DIR"):
        artifact_dir = Path(env["NARRATE_ARTIFACT_DIR"])

    engine = defaults.engine
    if env.get("NARRATE_ENGINE"):
        engine = _one_of("NARRATE_ENGINE", env["NARRATE_ENGINE"], SUPPORTED_ENGINES)

    engine_profile = defaults.engine_profile
    if env.get("NARRATE_ENGINE_PROFILE"):
        engine_profile = _one_of(
            "NARRATE_ENGINE_PROFILE", env["NARRATE_ENGINE_PROFILE"], ENGINE_PROFILES
        )

    return Config(
        engine=engine,
        engine_url=(env.get("NARRATE_ENGINE_URL") or defaults.engine_url).rstrip("/"),
        engine_profile=engine_profile,
        artifact_dir=artifact_dir,
        bind=env.get("NARRATE_BIND") or defaults.bind,
        port=port,
        voice=env.get("NARRATE_VOICE") or defaults.voice,
        chunk_chars=chunk_chars,
        timeout=timeout,
    )
