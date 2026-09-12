"""`narrate-service` — synthesis behind an HTTP API of its own.

This package is the service, not a client of one. The distinction is the whole
point of the repository: what existed before was a caller that posted directly
to a speech engine's own container and kept the stitching and the file writing
on its side of the wire. Here the engine is an implementation detail behind
this package's API, and two properties that the previous implementation already
got right are carried over unchanged:

* **Chunking is the service's job.** A caller sends one arbitrarily long text
  and gets one artifact. No client keeps stitching logic, and the property
  holds whatever the engine's own input limit turns out to be, because the
  splitting happens here rather than being delegated to the engine.
* **Writes are atomic.** An artifact lands in a temporary sibling and is
  renamed onto its final name, so an interrupted or failed run never leaves a
  truncated file that looks finished.

⛔ **The personal-data gate is NOT here, deliberately.** It runs in the caller,
before the request. An audio file that *speaks* an account identifier is
personal data on disk that cannot be grepped for afterwards -- unlike text it
is unrecoverable once written and unfindable once shipped. From a caller's
point of view this service is a third party, so ungated text must never reach
it. A gate implemented here would be a second copy that a caller could believe
in while sending the request that defeats it.

Standard library only. The engine speaks HTTP, so `urllib.request` is a
complete client and no SDK is needed.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
