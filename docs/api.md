# The `narrate-service` HTTP API

Version `0.1.0`. Three routes. Every request and response body is JSON except
a synthesised artifact, which is audio.

---

## ⛔ Before anything else: the personal-data gate is **yours**, not ours

**This service does not inspect, filter or redact the text you send it.** That
is deliberate and it is not an omission to be filed as a gap.

> ⛔ **Gate your text before the request, never after.** An audio file that
> *speaks* an account identifier is personal data on disk just as surely as a
> text file containing it — and unlike text it **cannot be grepped for
> afterwards**. It is unrecoverable once written and unfindable once shipped.

From your point of view this service is a **third party**. Ungated text must
never reach it. A gate implemented here would be a second copy of yours, and a
second copy is something a caller can believe in while sending exactly the
request that defeats it — so there is one gate, it is the caller's, and it runs
**before** the request.

## ⛔ And the second thing: this service never writes into your tree

It returns an artifact and keeps its own copy under its own id. **Where a file
lands is your decision**, every time. A synthesis service that knew where your
site keeps its audio would be a second authority on your layout.

---

## `GET /healthz`

Is the service up, and can it reach its engine.

```bash
curl -fsS http://127.0.0.1:8870/healthz
```

```json
{
  "status": "ok",
  "version": "0.1.0",
  "engine": "kokoro",
  "engine_reachable": true,
  "formats": ["mp3"]
}
```

| field | |
|---|---|
| `status` | `"ok"` whenever the service answers at all |
| `version` | the service's version |
| `engine` | which engine is deployed — record it beside an artifact you keep |
| `engine_reachable` | ⚠️ **`false` does not fail the request.** A health endpoint that fails when the engine is down cannot report that the engine is down |
| `formats` | what `POST /v1/speech` will accept as `format` |

⚠️ The engine probe has its own short timeout. Synthesis is legitimately slow
and its timeout is measured in minutes; a health check that inherited that
would hang for minutes reporting on an engine that is plainly not answering.

---

## `POST /v1/speech`

Synthesise one text. **Any length** — see *Chunking*, below.

### Request

`Content-Type: application/json`, and `Content-Length` is required.

| field | required | default | |
|---|---|---|---|
| `text` | ⭐ yes | — | the words to speak. Must contain something other than whitespace |
| `voice` | no | `am_liam` | the engine's voice id |
| `format` | no | `mp3` | ⛔ a **closed set**; today it contains `mp3` only |

```bash
curl -fsS -X POST http://127.0.0.1:8870/v1/speech \
     -H 'Content-Type: application/json' \
     -d '{"text": "Synthesis is behind an API of its own.", "voice": "am_liam"}' \
     -D headers.txt -o speech.mp3
```

### Response — `200`

The **body is the audio**, with `Content-Type: audio/mpeg`. One round trip, one
file, nothing to stitch.

The artifact is also **kept**, and these headers say where:

| header | |
|---|---|
| `Narrate-Artifact-Id` | 32 lowercase hex characters |
| `Narrate-Artifact-Url` | `/v1/artifacts/<id>` — fetch it again from here |
| `Narrate-Chunks` | how many pieces the text was split into |
| `Narrate-Voice` | the voice actually used |
| `Narrate-Seconds` | the artifact's duration, summed from its frames |

⭐ **Both callers are served without either doing the other's work.** A script
that wants one file uses `curl -o` and ignores the headers. A generator that
fetches artifacts and places them itself takes the id and comes back for it.

### Refusals

| status | when | what you do |
|---|---|---|
| `400` | the body is not a JSON object; `text` is missing, not a string, or only whitespace; `voice` or `format` is not a string; `format` is not in the closed set | fix the request. The message **names what is permitted** |
| `411` | no `Content-Length` | send one |
| `413` | the declared body length exceeds 4 MiB | send less. Refused on the declared length, **before** the bytes are read |
| `502` | the engine answered and the answer was not usable audio — an HTTP error from the engine, an empty response, or something that is not a decodable MPEG stream | look at the engine, not at your request |
| `503` | the engine could not be reached, or did not answer in time | the deployment. This is the one worth retrying |

Every refusal is `{"error": "<message>"}`.

⛔ **No refusal, log line or header ever echoes the text you sent.** A message
that quoted the input would write it into a log, which is the same disclosure
by a slower route.

---

## `GET /v1/artifacts/<id>`

Fetch a finished artifact again by the id `POST /v1/speech` returned.

```bash
curl -fsS http://127.0.0.1:8870/v1/artifacts/$ID -o speech.mp3
```

`200` with `Content-Type: audio/mpeg`, or `404` — which is also what a
malformed id gets, because an id is 32 lowercase hex characters and anything
else was never one this service minted.

⚠️ **Artifacts are not garbage-collected.** The store grows until somebody
empties it. That is a deployment decision and this service does not make it for
you.

---

## Two properties this service guarantees

### Chunking is **the service's** job

Send a text of any length. The service splits it internally — on a paragraph
break, else a sentence end, else a space — synthesises each piece in order, and
returns **one** artifact.

⭐ **You never keep stitching logic, and you never learn the engine's input
limit.** The split happens here rather than being delegated to the engine, so
the property holds when the engine is swapped for one with a different limit.
`Narrate-Chunks` tells you what happened; nothing requires you to act on it.

### Writes are **atomic**

An artifact appears under its final name **complete or not at all**. Bytes go
to a temporary sibling in the same directory and are renamed onto the
destination in one atomic step.

⭐ **Why this one matters more than it looks.** A truncated audio file *plays*.
Nothing downstream notices; it simply stops mid-sentence. So a partial write is
the one failure that would reach a listener silently, and there is no window in
which a partial artifact exists under a name you could fetch.

If any chunk fails, **nothing is stored** — you get a `502` or `503` and the
store is exactly as you found it.

---

## What is **not** here yet

Named, so you do not build against something that is absent, and do not build
against something half-present:

| not here | where it goes |
|---|---|
| ⛔ **A batch job API** — a list of `{id, text}` segments in, one artifact per id plus a manifest out | the next task. **There is no `/v1/jobs`**, and a test asserts its absence |
| ⛔ **Content-addressed caching and idempotence** | with the batch API. ⚠️ **Today, re-submitting identical text synthesises again and returns a different id.** The id is opaque and random — it is *not* a content address, deliberately, so that nothing starts relying on idempotence that is not there |
| ⛔ **A CPU profile / hardware independence** | a later task. Today's deployment is GPU-only and reserves every NVIDIA device on the host |
| ⛔ **A voice catalogue** — what voices exist and how a corpus picks one | a later task. `voice` is passed through to the engine unvalidated; an unknown voice surfaces as a `502` |
| ⛔ **A machine-readable `consuming.json`** — image tag, ports, GPU opt-in, environment, healthcheck, voices | contributed by the profile and voice-catalogue tasks, which are the two that know their halves |
| ⛔ **Formats other than `mp3`** | an MPEG elementary stream is a run of independently decodable frames, so its chunks concatenate with no muxer. A container format cannot be joined that way. A half-supported format that produced a broken file for long input would be worse than a refusal |

---

## Configuration

All environment, no flags — so there is exactly one place a setting comes from.

| variable | default | |
|---|---|---|
| `NARRATE_ENGINE_URL` | `http://127.0.0.1:8880/v1` | the engine's OpenAI-shaped speech API |
| `NARRATE_BIND` | `127.0.0.1` | ⛔ loopback. See below |
| `NARRATE_PORT` | `8870` | |
| `NARRATE_ARTIFACT_DIR` | `artifacts` | relative to the working directory |
| `NARRATE_VOICE` | `am_liam` | used when a request names none |
| `NARRATE_CHUNK_CHARS` | `1800` | characters per chunk, minimum 64 |
| `NARRATE_TIMEOUT_SECONDS` | `600` | per chunk. Synthesis runs at roughly a second per thousand characters |

⛔ **The default bind is loopback and widening it is a decision, not a
default.** This service has **no authentication of any kind**. Put something
that authenticates in front of it before it is reachable from anywhere else.

⛔ **A refusal from configuration names the variable and never its value.** An
environment variable is exactly where an account identifier or a home path
turns up, and a message echoing one would copy it into the log an operator then
pastes somewhere.
