"""Which adapter a deployment gets, chosen by configuration and nothing else.

⭐ **This module is the whole of *"switching engines is a deployment choice, not
a code change"*.** `NARRATE_ENGINE` names a family, `build_engine` looks it up
here, and no other module in the service branches on which engine is deployed.

⛔ **A closed set, not a plugin loader.** There is no entry-point scan and no
import-by-name: an engine that is not in `ENGINES` is refused, and adding one is
a line here in the same commit as the adapter it names. An import-by-name would
turn an environment variable into an instruction to import an arbitrary module,
which is a much larger surface than a deployment needs to pick between two
things.

⚠️ **`ENGINES` has one entry today and that is deliberate, for the reason
`config.SUPPORTED_FORMATS` has one.** The set exists because the *setting* has
to be validated -- an unknown `NARRATE_ENGINE` must be refused at startup with a
message naming what is permitted, not accepted and discovered later. A registry
whose closure is the point is not the same thing as an abstraction written
before its second implementation.

⭐ **The CPU and GPU profiles do NOT appear here, and their absence is the
result.** Both run the same adapter against the same request shape; what differs
between them is the engine image, the device reservation and the declared
profile label -- all of it deployment. ⛔ **If a profile needed its own entry in
this table, switching profiles would be a code change, which is exactly what
`NS-03` exists to prevent.**
"""

from __future__ import annotations

from ..config import ConfigError
from .base import check_engine
from .kokoro import ENGINE_NAME as KOKORO, KokoroEngine


class UnknownEngine(ConfigError):
    """`NARRATE_ENGINE` named an engine this build does not carry."""


def _build_kokoro(config):
    return KokoroEngine(
        config.engine_url,
        config.timeout,
        profile=config.engine_profile,
        # ⛔ The deployment's default voice reaches the ADAPTER, because the
        # adapter is what knows whether it exists. A misspelled `NARRATE_VOICE`
        # is therefore refused here, at startup, naming what is permitted --
        # not accepted and discovered on the first request.
        voice=config.voice,
    )


#: Engine family -> a factory taking a `Config`. ⛔ Closed; see the docstring.
ENGINES = {KOKORO: _build_kokoro}


def engine_names():
    """The engine families this build can deploy, in a stable order."""
    return tuple(sorted(ENGINES))


def build_engine(config):
    """The engine `config` names, checked against the adapter contract.

    ⛔ Raises `UnknownEngine` for a name that is not in the closed set,
    `UnknownVoice` if the deployment's default voice is not one the adapter
    offers, and `NotAnEngine` if a registered factory returns something that
    does not satisfy the contract -- all at startup, before anything is
    served.
    """
    try:
        factory = ENGINES[config.engine]
    except KeyError:
        permitted = ", ".join(engine_names())
        raise UnknownEngine(
            f"NARRATE_ENGINE must be one of: {permitted}"
        ) from None
    return check_engine(factory(config))
