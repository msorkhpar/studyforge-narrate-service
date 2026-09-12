# narrate-service

Turn text into speech, over HTTP, in a container. Standard library only.

**[`docs/api.md`](docs/api.md) is the API.** Read it before calling this — in
particular the two rules at the top, which are the ones a caller can get wrong
in a way that cannot be undone.

**[`docs/agent.md`](docs/agent.md) is the optional agent-callable adapter** —
`python3 -m narrate agent`, a stdio tool protocol for one-off narration outside
a corpus build. ⭐ **The service is complete without it**: no compose profile
starts it and nothing the service ships imports it.

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
- ⭐ **Writes are atomic, and safe under concurrency.** An artifact lands in its
  own unique temporary sibling and is renamed onto its final name, so an
  interrupted run never leaves a truncated file that looks finished — and two
  callers sending identical prose at the same time, which content addressing
  makes the *expected* case, cannot publish a mixture of their two syntheses.
  ⚠️ **A truncated audio file plays** — it simply stops mid-sentence — which is
  why this is the failure worth engineering against. ⭐ **An artifact and the
  record describing it are published, and read back, as one pair**, so a
  duration you are given always belongs to the file you get.

And one the service adds:

- ⭐ **Synthesis is idempotent.** An artifact's id is a **content address** over
  the format, the voice, the chunk budget and the text, so re-submitting an
  unchanged segment synthesises nothing and returns the same id. Change one
  segment's prose and one segment is re-synthesised. ⚠️ **The address is over
  the request, never over the audio** — a speech model may emit different bytes
  for identical input, so a digest of the output would be a cache that never
  hits. ⛔ **The chunk budget is in it** because each chunk is a separate engine
  request and the pieces are concatenated, so a different budget is different
  bytes at every join.

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

# one text, one file, in one round trip
curl -fsS -X POST http://127.0.0.1:8870/v1/speech \
     -H 'Content-Type: application/json' \
     -d '{"text": "Synthesis is behind an API of its own."}' \
     -o speech.mp3

# a batch of keyed segments, and a manifest of addresses back
curl -fsS -X POST http://127.0.0.1:8870/v1/jobs \
     -H 'Content-Type: application/json' \
     -d '{"segments": [{"id": "u01-s001", "text": "The first speech unit."},
                       {"id": "u01-s002", "text": "The second speech unit."}]}'
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
default, the healthcheck, both profiles with their requirements and the GPU
one's opt-in, the manifest's closed sets, the addressing scheme — which is
exactly enough to compute an address yourself before you submit anything — and,
since `provides: 3`, **every voice this deployment can speak** and the optional
agent adapter's condition for sharing a store.

⭐ **`not_yet_declared` is now EMPTY, and the key is kept rather than deleted.**
It named `voices` from the day the file was created until `NS-04` landed them;
an empty list still says *nothing is owed*, which a missing key could not.
Reading a Dockerfile is the first step toward forking it.

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
injected, so every route, every failure branch and every carried-over property
are exercised offline.

### ⛔ And the controls that prove the suite can go red

```bash
python3 -m tools.plant        # every control; a control that does not fire FAILS
python3 -m tools.plant p07    # one, by id
```

⭐ **A green suite that cannot go red measures nothing**, so each property has a
control that breaks it deliberately and names the test that must fire. ⚠️ **An
anchor that does not match exactly once is refused** rather than silently
applying nothing, and the ordinary suite asserts that every committed anchor
still resolves — so a refactor that moves one turns the harness red instead of
quietly disarming a control. That the real engine accepts the request shape is
established by a recorded measurement, not by a test that skips when the
deployment is down. ⭐ **That measurement is
[`docs/engine-measurement.md`](docs/engine-measurement.md)** — the CPU profile
at its pinned digest, the README's own request, and what `narrate.mpeg` read
off the bytes that came back. ⚠️ **It also refuted something**, which is what a
first live run is for.

## Layout

| | |
|---|---|
| `narrate/server.py` | the five routes |
| `narrate/synthesis.py` | split → synthesise → verify → store, in that order |
| `narrate/chunking.py` | where a long text is cut, and why there |
| `narrate/artifacts.py` | the atomic write, and the content address |
| `narrate/jobs.py` | the batch job, and what its manifest says |
| `narrate/voices.py` | the voice catalogue: ⛔ **declared by the adapter, never fetched** |
| `narrate/agent/` | ⭐ the OPTIONAL agent adapter. Nothing else imports it |
| `tools/reconcile_voices.py` | the declared catalogue against a running engine |
| `tools/plant.py` | ⛔ the negative-control harness: plant a defect, prove the suite catches it, restore |
| `narrate/mpeg.py` | the gate that makes *playable* a checked claim, not a hope |
| `narrate/engine/` | the engine seam — the contract, the registry, and Kokoro over HTTP |
| `narrate/config.py` | every setting, from the environment |

## What is not here yet

⭐ **`consuming.json` is complete: `not_yet_declared` is empty.** The voice
catalogue it named from the beginning is here, and the file now carries all 68
voices with the reading that produced them.

⚠️ **Two things a consumer should still know, and both are declared rather than
absent:**

- ⛔ **Formats other than `mp3`.** An MPEG elementary stream is a run of
  independently decodable frames, so its chunks concatenate with no muxer; a
  container format cannot be joined that way, and a half-supported format that
  produced a broken file for long input would be worse than a refusal.
- ⛔ **The store's publish lock is IN-PROCESS.** One serving process per
  deployment is the shape this is run in. The optional agent adapter is a
  second process, so pointing it at a live deployment's artifact directory is
  a condition to read in [`docs/agent.md`](docs/agent.md) rather than a default
  to assume — and `consuming.json` says `agent.shares_the_store: false`.

Each is named in [`docs/api.md`](docs/api.md) or [`docs/agent.md`](docs/agent.md)
with where it goes, so that nothing is built against something absent — or,
worse, against something half-present.
