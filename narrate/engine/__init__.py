"""The speech engine, behind one seam.

⭐ **Everything above this package speaks to `synthesize_chunk(text, voice,
fmt)` and knows nothing else about how audio is made.** Today there is exactly
one implementation -- Kokoro, reached over its OpenAI-shaped HTTP API -- and it
is the only one this task was asked for. The seam is here so that a second
engine, and the CPU and GPU profiles that a deployment picks between, are a new
module in this package rather than a change to the API, the chunker, the store
or the server.

⛔ **What is deliberately absent**: an engine registry, a plugin loader, a
profile selector. One implementation does not need a lookup table, and the
interface is proven by the second implementation rather than by the abstraction
written before it.
"""

from .errors import EngineError, EngineFailed, EngineUnavailable
from .kokoro import KokoroEngine

__all__ = ["EngineError", "EngineFailed", "EngineUnavailable", "KokoroEngine"]
