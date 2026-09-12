# narrate-service

Turn text into speech, over HTTP, in a container. Standard library only.

**[`docs/api.md`](docs/api.md) is the API.** Read it before calling this — in
particular the two rules at the top, which are the ones a caller can get wrong
in a way that cannot be undone.

---

## What it is, and what it replaces

A **service**, not a client of one.

What existed before was a caller that posted directly into a speech engine's
own container. Every caller therefore knew the engine's address, its request
shape and its input limit; each kept its own stitching logic for long text and
its own file-writing; and swapping the engine was a change to every caller.

Here the engine is an implementation detail behind one API. A caller knows one
address and one request shape, and two properties the previous implementation
already got right are carried over unchanged:

- ⭐ **Chunking is the service's job.** Send one text of any length, get one
  artifact. No caller keeps stitching logic, and the property holds whatever
  the engine's own input limit turns out to be — because the splitting happens
  here rather than being delegated to the engine.
- ⭐ **Writes are atomic.** An artifact lands in a temporary sibling and is
  renamed onto its final name, so an interrupted run never leaves a truncated
  file that looks finished. ⚠️ **A truncated audio file plays** — it simply
  stops mid-sentence — which is why this is the failure worth engineering
  against.

## ⛔ Two rules for anyone calling this

1. **Gate your text before the request, never after.** This service does not
   inspect or redact anything. Audio that *speaks* an identifier is personal
   data that **cannot be grepped for afterwards**. From your side this is a
   third party.
2. **It never writes into your tree.** It returns an artifact and keeps its own
   copy; where a file lands is your decision, every time.

Both are argued in [`docs/api.md`](docs/api.md).

## Run it

```bash
docker compose up -d --build

curl -fsS http://127.0.0.1:8870/healthz

curl -fsS -X POST http://127.0.0.1:8870/v1/speech \
     -H 'Content-Type: application/json' \
     -d '{"text": "Synthesis is behind an API of its own."}' \
     -o speech.mp3
```

⛔ **The engine is not published** — it is reachable only from the compose
project's network, only by this service. ⛔ **The service binds `127.0.0.1` on
the host**: it has no authentication of its own. ⛔ **No docker socket is
mounted anywhere.**

⚠️ **Today's engine profile is GPU-only.** It is the deployment that existed
before, carried over unchanged, and it reserves every NVIDIA device on the
host. A CPU path that works anywhere, with GPU as an opt-in profile, is the
next piece of work and is deliberately not attempted here — stated rather than
left to be discovered on a machine with no GPU, where `compose.yaml` does not
come up.

### Without the container

The service itself is standard library only, so it runs from a checkout against
any reachable engine:

```bash
NARRATE_ENGINE_URL=http://127.0.0.1:8880/v1 python3 -m narrate serve
```

## The suite

```bash
python3 -m pip install -e '.[test]'    # pytest, the only dependency, test-only
python3 -m pytest -ra
```

⭐ **Nothing in the suite needs a running engine or a GPU.** The engine is
injected, so every route, every failure branch and both carried-over properties
are exercised offline. That the real engine accepts the request shape is
established by a recorded measurement, not by a test that skips when the
deployment is down.

## Layout

| | |
|---|---|
| `narrate/server.py` | the three routes |
| `narrate/synthesis.py` | split → synthesise → verify → store, in that order |
| `narrate/chunking.py` | where a long text is cut, and why there |
| `narrate/artifacts.py` | the atomic write, and the opaque id |
| `narrate/mpeg.py` | the gate that makes *playable* a checked claim, not a hope |
| `narrate/engine/` | the engine seam. One implementation: Kokoro over HTTP |
| `narrate/config.py` | every setting, from the environment |

## What is not here yet

A batch job API, content-addressed caching, a CPU profile, a voice catalogue,
and a machine-readable `consuming.json`. Each is named in
[`docs/api.md`](docs/api.md) with where it goes, so that nothing is built
against something absent — or, worse, against something half-present.
