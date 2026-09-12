"""What can go wrong at the engine, told apart because callers act differently.

Three outcomes, not one, because the operator's next move differs:

* `EngineUnavailable` -- nothing answered. The engine container is down, or the
  address is wrong. The service reports this as `503`, and it is the one a
  caller may usefully retry.
* `EngineFailed` -- something answered and refused, or answered with something
  that is not audio. The request is the suspect, not the deployment. `502`.
* `EngineError` -- the base, so a caller that genuinely does not care can catch
  one thing.

⛔ **No message built here interpolates the text that was sent.** The whole
reason the gate lives in the caller is that this service is a third party to
whatever the text contains; an error message that quotes the input would write
it into a log, which is the same disclosure by a slower route.
"""

from __future__ import annotations


class EngineError(Exception):
    """Synthesis failed at the engine. Nothing was written."""


class EngineUnavailable(EngineError):
    """The engine could not be reached at all."""


class EngineFailed(EngineError):
    """The engine answered, and the answer was not usable audio."""
