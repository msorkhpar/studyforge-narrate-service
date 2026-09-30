# The agent-callable adapter

```bash
python3 -m narrate agent
```

An optional surface letting an agent call synthesis **directly**, over a stdio
tool protocol, for one-off narration outside a corpus build. ⭐ **Nothing has to
be running** — the adapter builds an engine and a store from the same
environment `serve` reads and calls straight in.

⛔ **It is optional and the service is complete without it.** The container's
`CMD` is `serve`, no compose profile starts this, and no module the service
ships imports it at module level. Start the serve path in a fresh interpreter
and `narrate.agent` is absent from `sys.modules`.

---

## ⛔ Before anything else: the personal-data gate is **yours**

The HTTP API says this and the adapter says it louder, because **you are the
last caller before the engine**. There is no framework client between you and
synthesis here.

> ⛔ **Gate your text before you call, never after.** Audio that *speaks* an
> account identifier is personal data on disk that **cannot be grepped for
> afterwards** — unrecoverable once written, unfindable once shipped.

Every tool description repeats it in the text the model actually reads, because
a rule that lives only in a document is a rule the caller never sees.

---

## The transport

Newline-delimited JSON-RPC 2.0 on stdin and stdout: **one compact JSON object
per line**, in both directions.

⚠️ **It is not the LSP-style `Content-Length:` header framing** that most
JSON-RPC sample code uses. The two share ancestry, and a server built from an
LSP example hangs at the handshake with no useful error.

| method | |
|---|---|
| `initialize` | the handshake. Echoes your `protocolVersion` back |
| `notifications/initialized` | a notification. ⛔ Never answered |
| `ping` | `{}` |
| `tools/list` | the three tools and their schemas |
| `tools/call` | run one |

### ⛔ stdout carries protocol bytes and nothing else

`run_adapter` rebinds `sys.stdout` to stderr for the whole run and keeps the
real handle privately, so **a careless print anywhere beneath this package —
in the chunker, in an engine adapter, in a library — becomes a log line instead
of breaking the transport.**

⚠️ **This is a carried lesson and it cost a debugging session.** A single stray
print, warning or traceback on the protocol stream corrupts it; the client
drops the connection reporting only a parse error, and nothing points at the
print that caused it.

⭐ **Committed control `p18` removes the rebinding**, and the test that names
this property fails when it does — so the guard is confirmable rather than
merely present.

---

## The tools

### `synthesize`

One text, of any length — splitting is the service's job.

```json
{"name": "synthesize", "arguments": {"text": "One spoken unit.", "voice": "am_liam"}}
```

The result's text is JSON:

```json
{"artifact_id": "<64 hex>", "url": "/v1/artifacts/<64 hex>",
 "file": "<64 hex>.mp3", "voice": "am_liam", "format": "mp3",
 "bytes": 49196, "seconds": 3.288, "chunks": 1, "cached": false,
 "engine": "kokoro", "engine_model": "kokoro"}
```

⛔ **No path outside the store is ever returned, and no absolute one.** `file`
is the name *within* the store. A store directory is either a container path or
somebody's home directory, and `narrate` never decides where an artifact lands
in your tree — that is yours.

### `narrate_batch`

The same request body as `POST /v1/jobs`, and the same manifest back: one entry
per submitted id, in submission order, each with its own content address.

⭐ **Prefer it over repeated `synthesize` calls.** Per-request overhead is the
difference between minutes and hours for a corpus. Read `counts`, not the
outcome of any one segment.

### `voices`

The catalogue and this deployment's default. ⭐ **Needs no engine and cannot
fail.** Call it before naming a voice: an unknown id is refused, never silently
defaulted.

---

## What a failure looks like

| | |
|---|---|
| a failed **synthesis** | `isError` content. ⭐ The call was well formed and the work did not succeed — show the reason to the model |
| an unknown **voice** | `isError` content naming what is permitted. For `narrate_batch`, the whole batch, before any segment is attempted |
| an unknown **tool** or **method** | a JSON-RPC error, `-32601`. ⚠️ That is a protocol fault and a different thing |
| an unparseable **line** | logged to stderr and skipped. ⛔ The loop never dies of one bad message |

The tool table is **closed**: a name arriving from a client is looked up, never
`getattr`-ed onto the adapter.

---

## ⚠️ The one condition to know before you point this at a deployment

⛔ **This adapter is a second writing PROCESS, and the store's publish lock is
in-process.** `narrate/artifacts.py` names one serving process per deployment
as the shape the service is run in; running this against a live deployment's
artifact directory is what breaks that premise. Two processes racing one
address can publish one synthesis's audio beside the other's record — both
halves complete and valid, with only the byte count and duration belonging to
the twin.

⭐ **By default they do not share a store.** The container sets
`NARRATE_ARTIFACT_DIR=/var/lib/narrate/artifacts` onto a named volume; this
adapter run on a host takes the default, a relative `artifacts` directory.
⛔ **Sharing is therefore something you do deliberately** — and
`consuming.json` declares `agent.shares_the_store: false` so it is a condition
you read rather than infer.

⚠️ **If you do share one, do it while the service is idle**, or accept that
window.

---

## Configuration

Identical to `serve` — see the *Configuration* table in `api.md`. The adapter
reads the same environment, so an agent and a deployment configured alike
address artifacts identically, and an agent's one-off narration is a cache hit
for a later corpus build.

⛔ **A misspelled `NARRATE_VOICE` refuses to start the adapter**, naming what is
permitted, exactly as it refuses to start the service.
