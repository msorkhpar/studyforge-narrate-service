"""The HTTP surface: four routes, on `http.server`, standard library only.

    GET  /healthz                 is the service up, and is its engine up
    POST /v1/speech               synthesise one text, get one artifact back
    POST /v1/jobs                 synthesise many keyed segments, get a manifest
    GET  /v1/artifacts/<id>       fetch a finished artifact again

⭐ **Why `POST /v1/speech` returns the audio *and* keeps it.** A caller that
wants one file gets it in one round trip, with `curl -o` and nothing else. A
caller that wants to fetch and place artifacts separately -- which is what a
site generator does, because *where a file lands* is its decision and never
this service's -- has the id and the URL in the response headers. Neither
caller is made to do the other's work.

⛔ **This service never writes into a caller's tree.** It returns artifacts and
keeps its own copy in its own directory; a synthesis service that knew where a
study site keeps its audio would be a second authority on layout.

⭐ **`POST /v1/jobs` NEVER RETURNS AUDIO, and that is the difference between the
two synthesis routes.** A corpus is thousands of segments; a response that
carried their bytes would be a multi-gigabyte body no caller wants in memory.
The manifest carries one address per id and the caller fetches what it needs
from `/v1/artifacts/<id>` -- which, because addresses are content addresses, is
usually nothing at all on a re-run. ⛔ **Both routes go through the same
`synthesise()` and therefore the same cache**: a segment sent to one is a cache
hit at the other.

⛔ **No authentication, and therefore loopback by default.** Binding this on a
routable interface is a decision a deployment makes explicitly, in front of
something that does authenticate.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import PROVIDES, __version__
from .artifacts import ArtifactStore, UnknownArtifact
from .config import FORMAT_MEDIA_TYPES, SUPPORTED_FORMATS
from .engine import EngineError, EngineUnavailable, build_engine, check_engine
from .jobs import InvalidJob, parse_job, run_job
from .synthesis import UnsupportedFormat, synthesise

#: Refuse a body larger than this before reading it. Synthesis is slow and a
#: caller's text is prose; a request in the megabytes is a mistake or an abuse,
#: and either way reading it into memory first is the wrong way to find out.
MAX_BODY_BYTES = 4 * 1024 * 1024

_ARTIFACT_PREFIX = "/v1/artifacts/"


class _Handler(BaseHTTPRequestHandler):
    """One request. The service's state hangs off the server, not off this."""

    protocol_version = "HTTP/1.1"
    server_version = f"narrate-service/{__version__}"
    #: ⛔ Not the default. `BaseHTTPRequestHandler` appends the Python version
    #: to `Server:`, which tells a stranger what to look up CVEs for.
    sys_version = ""

    # -- routing ----------------------------------------------------------

    def do_GET(self):
        if self.path == "/healthz":
            return self._health()
        if self.path.startswith(_ARTIFACT_PREFIX):
            return self._artifact(self.path[len(_ARTIFACT_PREFIX):])
        return self._error(HTTPStatus.NOT_FOUND, "no such route")

    def do_POST(self):
        if self.path == "/v1/speech":
            return self._speech()
        if self.path == "/v1/jobs":
            return self._jobs()
        return self._error(HTTPStatus.NOT_FOUND, "no such route")

    # -- routes -----------------------------------------------------------

    def _health(self):
        service = self.server.narrate
        payload = {
            "status": "ok",
            "version": __version__,
            # ⭐ Which PROMISE this deployment is making, so a caller can check
            # it before it builds a job rather than after. Not the build.
            "provides": PROVIDES,
            # ⛔ Part of the content address and a DEPLOYMENT setting, so a
            # caller that recomputes an address for itself cannot get it from
            # a constant. Published here and in every manifest.
            "chunk_chars": service.chunk_chars,
            "engine_reachable": service.engine.reachable(),
            "formats": list(SUPPORTED_FORMATS),
        }
        # ⭐ The SAME three fields a synthesised artifact is stamped with, from
        # the same `identity()`. A caller can read them here before it sends
        # anything and compare them to what came back with an artifact.
        payload.update(service.engine.identity().as_dict())
        return self._json(HTTPStatus.OK, payload)

    def _artifact(self, artifact_id):
        service = self.server.narrate
        try:
            audio = service.store.read(artifact_id)
        except UnknownArtifact as exc:
            return self._error(HTTPStatus.NOT_FOUND, str(exc))
        return self._bytes(HTTPStatus.OK, audio, FORMAT_MEDIA_TYPES["mp3"])

    def _speech(self):
        service = self.server.narrate

        body = self._read_body()
        if body is None:
            return None
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return self._error(HTTPStatus.BAD_REQUEST, "body must be JSON")
        if not isinstance(request, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "body must be a JSON object")

        text = request.get("text")
        if not isinstance(text, str):
            return self._error(HTTPStatus.BAD_REQUEST, "text must be a string")
        voice = request.get("voice") or service.voice
        if not isinstance(voice, str):
            return self._error(HTTPStatus.BAD_REQUEST, "voice must be a string")
        fmt = request.get("format") or SUPPORTED_FORMATS[0]
        if not isinstance(fmt, str):
            return self._error(HTTPStatus.BAD_REQUEST, "format must be a string")

        try:
            result = synthesise(
                text, voice, fmt,
                engine=service.engine,
                store=service.store,
                chunk_chars=service.chunk_chars,
                media_types=FORMAT_MEDIA_TYPES,
            )
        except (UnsupportedFormat, ValueError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except EngineUnavailable as exc:
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except EngineError as exc:
            return self._error(HTTPStatus.BAD_GATEWAY, str(exc))

        summary = result.summary()
        return self._bytes(
            HTTPStatus.OK, result.audio, result.media_type,
            extra={
                "Narrate-Artifact-Id": summary["artifact_id"],
                "Narrate-Artifact-Url": summary["url"],
                "Narrate-Chunks": str(summary["chunks"]),
                "Narrate-Voice": summary["voice"],
                "Narrate-Seconds": str(summary["seconds"]),
                # ⛔ On the ARTIFACT, not only on /healthz: a caller that keeps
                # an artifact must be able to record what produced it without
                # a second request to an endpoint that may by then be
                # answering for a redeployed engine.
                "Narrate-Engine": result.identity.label,
                "Narrate-Engine-Model": result.identity.model,
                # ⭐ Whether this cost a synthesis. On `true` the engine above
                # is the one that made the file, not the one deployed now.
                "Narrate-Cached": "true" if result.cached else "false",
            },
        )

    def _jobs(self):
        """A batch of keyed segments. ⛔ The manifest is the whole response.

        A well-formed job always answers `200`; a segment's failure is an entry
        in the manifest, because a caller must read the manifest anyway to
        learn the addresses. A body that is not a job never runs and is a
        `400`.
        """
        service = self.server.narrate

        body = self._read_body()
        if body is None:
            return None
        try:
            request = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return self._error(HTTPStatus.BAD_REQUEST, "body must be JSON")

        try:
            job = parse_job(request, default_voice=service.voice)
        except InvalidJob as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))

        manifest = run_job(
            job,
            engine=service.engine,
            store=service.store,
            chunk_chars=service.chunk_chars,
            media_types=FORMAT_MEDIA_TYPES,
            provides=PROVIDES,
        )
        return self._json(HTTPStatus.OK, manifest)

    # -- plumbing ---------------------------------------------------------

    def _read_body(self):
        """Request body, or `None` having already sent a refusal."""
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"body must be at most {MAX_BODY_BYTES} bytes",
            )
            return None
        return self.rfile.read(length)

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        return self._bytes(status, body, "application/json")

    def _error(self, status, message):
        return self._json(status, {"error": message})

    def _bytes(self, status, body, media_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
        return None

    def log_message(self, fmt, *args):
        """One line per request: method, path, status. ⛔ Never the body.

        The default logs the request line only, which is already right for
        this service -- the text is in the body and must not reach a log. This
        override exists to say so and to drop the client address, which on a
        deployment behind a proxy is a stranger's address in somebody's file.
        """
        self.server.narrate.log(f"{self.requestline} -> {args[1] if len(args) > 1 else ''}")


class _Service:
    """What every request needs, built once."""

    def __init__(self, engine, store, voice, chunk_chars, log=None):
        self.engine = engine
        self.store = store
        self.voice = voice
        self.chunk_chars = chunk_chars
        self._log = log

    def log(self, line):
        if self._log is not None:
            self._log(line)


class NarrateServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` carrying the service's state."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        self.narrate = service
        super().__init__(address, _Handler)


def build_server(config, engine=None, log=None):
    """A `NarrateServer` bound per `config`, ready to `serve_forever()`.

    `engine` is injectable so the suite can exercise every route without a
    running engine and without a GPU.
    """
    if engine is None:
        engine = build_engine(config)
    else:
        # ⛔ An injected engine is checked too, and at startup. This parameter
        # is public; an object missing a member would otherwise surface as a
        # 500 on the first request rather than as a refusal to start.
        check_engine(engine)
    service = _Service(
        engine=engine,
        store=ArtifactStore(config.artifact_dir),
        voice=config.voice,
        chunk_chars=config.chunk_chars,
        log=log,
    )
    return NarrateServer((config.bind, config.port), service)
