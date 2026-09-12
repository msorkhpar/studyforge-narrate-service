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

### Profiles — CPU by default, GPU by opting in

⭐ **`docker compose up` is the CPU deployment and it needs no GPU, no vendor
driver and no container runtime beyond docker.** The GPU deployment is opt-in
by naming a second file, so nothing selects it by accident:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
```

⛔ **Switching profiles changes no code.** Both run the same image of this
service, the same adapter and the same request shape; the overlay changes the
engine image, the device reservation and the reported profile label, and
`docker compose config` prints exactly that difference. ⚠️ **CPU synthesis is
slower** — that is the trade, and slower everywhere beats fast nowhere else.

⚠️ **`engine_profile` is what the deployment DECLARED, not something the
service detected.** It is on the far side of HTTP from its engine and cannot
see that engine's hardware. What it guarantees is that the same value appears
on `/healthz` and on every artifact, so an artifact you keep carries what the
deployment said made it.

### ⛔ Don't read this repository's compose files to consume it

[`consuming.json`](consuming.json) is the machine-readable contract: image,
ports and their host binding, mounts, uid, every environment variable with its
default, the healthcheck, and both profiles with their requirements and the GPU
one's opt-in. It names its own gap (`not_yet_declared`) rather than leaving you
to guess. Reading a Dockerfile is the first step toward forking it.

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
| `narrate/engine/` | the engine seam — the contract, the registry, and Kokoro over HTTP |
| `narrate/config.py` | every setting, from the environment |

## What is not here yet

A batch job API, content-addressed caching, and a voice catalogue — which is
also the one part of `consuming.json` that is still absent, and the file says
so itself. Each is named in [`docs/api.md`](docs/api.md) with where it goes, so
that nothing is built against something absent — or, worse, against something
half-present.
