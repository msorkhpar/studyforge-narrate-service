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

from ..config import DEFAULT_ENGINE_PROFILE as DEFAULT_PROFILE
from ..voices import UNKNOWN, Voice, catalogue_from_ids
from .base import EngineIdentity
from .errors import EngineFailed, EngineUnavailable

#: The engine's model name in the OpenAI request shape. Kokoro serves one.
MODEL = "kokoro"

ENGINE_NAME = "kokoro"

#: The health probe gets its own, short timeout. Synthesis is legitimately slow
#: and its timeout is measured in minutes; a `GET /healthz` that inherited that
#: would hang for minutes reporting on an engine that is plainly not answering,
#: which is the opposite of what a health endpoint is for.
PROBE_TIMEOUT_SECONDS = 5.0

#: Where the engine lists what it can speak. ⛔ Read by `tools.reconcile_voices`
#: and by nothing in the service: validation must work with the engine down.
VOICES_PATH = "/audio/voices"

# -- the voice catalogue ---------------------------------------------------
#
# ⛔ **MEASURED, NOT COMPILED FROM DOCUMENTATION.** `VOICE_IDS` below is the
# `id` field of every entry `GET /v1/audio/voices` returned from the engine
# image this repository pins for the CPU profile --
# `ghcr.io/remsky/kokoro-fastapi-cpu:v0.8.2`, digest
# `sha256:8545e2a4ae8d040749a369a848236fcf768aabc3b5b7a89451afa6507101c59a` --
# started with nothing else configured. ⭐ **68 ids, in the order the engine
# returned them.** ⚠️ The engine also returns a quality grade and a training
# duration per voice; those are deliberately NOT carried here, because they are
# the engine's editorial opinion of itself and would go stale in a committed
# file without anything noticing.
#
# ⚠️ **The reading was taken on the CPU image only.** The GPU image is the same
# upstream version and is *expected* to serve the same list -- ⛔ **which is an
# expectation and not a measurement, and nobody has taken the second one.**
# `python3 -m tools.reconcile_voices <engine-base-url>` takes it against any
# running engine and prints what the two disagree about.

#: Every voice id this adapter declares. ⛔ A measurement; see above.
VOICE_IDS = (
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jadzia",
    "af_jessica", "af_kore", "af_nicole", "af_nova", "af_river",
    "af_sarah", "af_sky", "af_v0", "af_v0bella", "af_v0irulan",
    "af_v0nicole", "af_v0sarah", "af_v0sky", "am_adam", "am_echo",
    "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "am_v0adam", "am_v0gurney", "am_v0michael",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bf_v0emma",
    "bf_v0isabella", "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "bm_v0george", "bm_v0lewis", "ef_dora", "em_alex", "em_santa",
    "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi", "if_sara",
    "im_nicola", "jf_alpha", "jf_gongitsune", "jf_nezumi",
    "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian",
    "zm_yunxi", "zm_yunxia", "zm_yunyang",
)

#: ⛔ **A DECODING RULE, published rather than applied silently.** Kokoro names
#: a voice `<language><gender>_<speaker>`; the two tables below are that
#: convention written down, so a consumer can check the derivation rather than
#: trust a hand-written table. ⚠️ **The ids are the fact and this is an
#: interpretation of them** -- a prefix outside these tables decodes to
#: `unknown` rather than being guessed at or dropped.
LANGUAGE_BY_PREFIX = {
    "a": "en-US", "b": "en-GB", "e": "es", "f": "fr-FR", "h": "hi",
    "i": "it", "j": "ja", "p": "pt-BR", "z": "zh",
}

GENDER_BY_PREFIX = {"f": "female", "m": "male"}

#: The marker Kokoro puts on a voice carried over from an earlier release.
LEGACY_MARKER = "v0"


def decode_voice(voice_id):
    """A `Voice` from one Kokoro id, by the published rule above.

    ⛔ **Total, and it never raises.** An id whose prefix is not in the tables
    still yields a selectable voice carrying `unknown` where the rule does not
    reach -- because a voice the engine really serves must stay usable, and a
    decoder that refused it would turn a naming convention into an outage.
    """
    prefix, _, rest = voice_id.partition("_")
    language = LANGUAGE_BY_PREFIX.get(prefix[:1], UNKNOWN)
    gender = GENDER_BY_PREFIX.get(prefix[1:2], UNKNOWN)

    if rest.startswith(LEGACY_MARKER):
        speaker = rest[len(LEGACY_MARKER):]
        name = (f"{speaker.capitalize()} ({LEGACY_MARKER})" if speaker
                else f"Legacy ({LEGACY_MARKER})")
    else:
        name = rest.capitalize() or voice_id

    return Voice(id=voice_id, name=name, language=language, gender=gender)


def voice_catalogue(default):
    """This adapter's catalogue, with `default` as the fallback voice.

    ⛔ Raises `UnknownVoice` if `default` is not one of the declared ids, and
    it is called at startup -- so a deployment whose `NARRATE_VOICE` is
    misspelled refuses to start rather than failing every request it is sent.
    """
    return catalogue_from_ids(VOICE_IDS, default, decode_voice)


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

    def __init__(self, base_url, timeout, profile=DEFAULT_PROFILE,
                 voice=None, transport=None, probe=None,
                 probe_timeout=PROBE_TIMEOUT_SECONDS):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._profile = profile
        self._probe_timeout = probe_timeout
        self._transport = transport if transport is not None else _post
        self._probe = probe if probe is not None else _get
        # ⛔ Built HERE, at construction, and not on first use. `build_engine`
        # runs at startup, so a `NARRATE_VOICE` this adapter does not offer is
        # a refusal to start naming what is permitted -- never a deployment
        # that comes up and then fails every request it is ever sent.
        self._catalogue = voice_catalogue(voice or VOICE_IDS[0])

    @property
    def base_url(self):
        return self._base_url

    def voices(self):
        """This adapter's `VoiceCatalogue`. ⛔ Declared, never fetched.

        ⚠️ **The engine is not consulted, and that is the point.** Validation
        that needed a round trip would turn *"no such voice"* into *"try
        again later"* whenever the engine was down, and a job in a misspelled
        voice would then be attempted rather than refused. See
        `narrate.voices` for the whole argument and for the cost.
        """
        return self._catalogue

    def identity(self):
        """What produced an artifact. ⛔ `profile` is declared, not detected.

        ⚠️ **The same adapter serves the CPU and the GPU profile**: Kokoro's
        two images speak one request shape, so the profile is carried here as
        the deployment's own statement and changes nothing about the call.
        That it changes nothing is the point -- see `registry.py`.
        """
        return EngineIdentity(
            engine=self.name, profile=self._profile, model=MODEL
        )

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
