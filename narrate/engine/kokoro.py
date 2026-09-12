"""Kokoro, reached over its OpenAI-shaped `/audio/speech` endpoint.

The engine speaks a documented HTTP shape, so `urllib.request` is a complete
client and no SDK is needed -- which is what keeps this repository on the
standard library.

⛔ **This module receives one chunk and returns its bytes.** It does not split,
it does not concatenate, and it does not write anything to disk. Splitting is
`narrate.chunking`'s and writing is `narrate.artifacts`'s, so that the property
*"chunking is the service's job"* holds for whatever engine is here rather than
depending on this particular one's input limit.

The transport is injectable for exactly one reason: so the suite can prove the
request shape, the timeout handling and every failure branch without a running
engine and without a GPU. A test that needs the deployment to be up is a test
that does not run.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .errors import EngineFailed, EngineUnavailable

#: The engine's model name in the OpenAI request shape. Kokoro serves one.
MODEL = "kokoro"

ENGINE_NAME = "kokoro"

#: The health probe gets its own, short timeout. Synthesis is legitimately slow
#: and its timeout is measured in minutes; a `GET /healthz` that inherited that
#: would hang for minutes reporting on an engine that is plainly not answering,
#: which is the opposite of what a health endpoint is for.
PROBE_TIMEOUT_SECONDS = 5.0


def _post(url, body, timeout):
    """Default transport: POST `body` as JSON, return the response bytes."""
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _get(url, timeout):
    """Default transport for the health probe."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status


class KokoroEngine:
    """Synthesis against one Kokoro endpoint."""

    name = ENGINE_NAME

    def __init__(self, base_url, timeout, transport=None, probe=None,
                 probe_timeout=PROBE_TIMEOUT_SECONDS):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._probe_timeout = probe_timeout
        self._transport = transport if transport is not None else _post
        self._probe = probe if probe is not None else _get

    @property
    def base_url(self):
        return self._base_url

    def synthesize_chunk(self, text, voice, fmt):
        """Audio bytes for one chunk. Raises `EngineError` on every failure.

        ⛔ Refusals name the endpoint and the status, never the text: see
        `errors.py`.
        """
        url = f"{self._base_url}/audio/speech"
        body = json.dumps(
            {"model": MODEL, "input": text, "voice": voice, "response_format": fmt}
        ).encode("utf-8")

        try:
            audio = self._transport(url, body, self._timeout)
        except urllib.error.HTTPError as exc:
            raise EngineFailed(f"the engine returned HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise EngineUnavailable(
                f"the engine did not answer within {self._timeout:g}s"
            ) from exc
        except OSError as exc:
            raise EngineUnavailable(
                f"cannot reach the engine at {self._base_url} "
                f"({exc.__class__.__name__})"
            ) from exc

        if not audio:
            raise EngineFailed("the engine returned no audio")
        return audio

    def reachable(self):
        """Whether the engine answers at all. Used only by `GET /healthz`.

        Never raises: a health endpoint that raises is a health endpoint that
        cannot report an unhealthy engine.
        """
        try:
            status = self._probe(f"{self._base_url}/models", self._probe_timeout)
        except Exception:
            return False
        return status is None or 200 <= int(status) < 500
