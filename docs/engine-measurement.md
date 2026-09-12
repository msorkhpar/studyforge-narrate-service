# The recorded engine measurement

⭐ **This is the reading `README.md` points at.** Every other test in this
repository runs against `FakeEngine`; nothing in the suite needs a deployment,
and that is deliberate. What a suite built that way cannot establish is that
the *real* engine accepts the request shape this service sends and returns
bytes this service can gate. ⛔ **That is established here, by a run, and
nowhere else.**

⚠️ **A measurement, not a test.** It is not re-run by `pytest`, it does not gate
a merge, and it goes stale the moment either pinned digest moves. Re-take it
when a digest changes; the commands are all here.

---

## The deployment that was measured

| | |
|---|---|
| profile | `cpu` — the default, `docker compose up -d --build`, no overlay named |
| engine image | `ghcr.io/remsky/kokoro-fastapi-cpu:v0.8.2` |
| engine digest | `sha256:8545e2a4ae8d040749a369a848236fcf768aabc3b5b7a89451afa6507101c59a` |
| service image | `narrate-service:local`, built from this tree by the same command |
| engine published ports | none — reached only over the compose project's network |
| service address | `127.0.0.1:8870`, loopback |
| `/healthz` reported | `engine_reachable: true`, `provides: 3`, `voices: 68`, `engine_profile: cpu`, `chunk_chars: 1800`, `default_voice: am_liam` |

The digest is the *running* one, read back off the container with
`docker inspect`, not the one the compose file asks for — so the row records
what answered rather than what was requested. They agreed.

⚠️ **The GPU overlay was NOT measured.** `kokoro.py` already says the second
reading has never been taken and that remains true: this run did not take it
either. `count: all` reserves every NVIDIA device on the host, which is not a
thing to do in passing.

---

## The request

⛔ **Placeholder prose, always.** Nothing here came from an operator's
environment, and nothing that identifies anybody may ever be sent to a speech
engine — audio that *speaks* an identifier cannot be grepped for afterwards.

```bash
curl -fsS -X POST http://127.0.0.1:8870/v1/speech \
     -H 'Content-Type: application/json' \
     -d '{"text": "Synthesis is behind an API of its own."}' \
     -o speech.mp3
```

That is the README's own example, sent verbatim. The service put this on the
wire to the engine, which is the shape being established:

```json
{"model": "kokoro", "input": "<the chunk>", "voice": "am_liam", "response_format": "mp3"}
```

It was accepted: `HTTP/1.1 200 OK`, `Content-Type: audio/mpeg`,
`Content-Length: 47276`, `Narrate-Chunks: 1`, `Narrate-Seconds: 2.952`,
`Narrate-Engine: kokoro/cpu`, `Narrate-Cached: false`.

---

## ⭐ What the parser read off the real bytes

⛔ **The status code was not the check.** The response body was fed to
`narrate.mpeg.describe` — the same gate the service applies before it will
rename an artifact into place, built from the specification rather than from a
sample.

```
describe(body) -> {"frames": 123, "seconds": 2.952, "sample_rate": 24000}
```

Walked frame by frame, the real stream is:

| | read off the wire |
|---|---|
| leading ID3v2 tag | 44 bytes, skipped |
| first frame header | `ff f3 c4 c4` |
| MPEG version | **2** (not MPEG-1) |
| layer | III |
| bitrate | 128 kbit/s |
| sample rate | **24000 Hz** |
| channel mode | **mono** |
| padding | 0 |
| frames | 123, **every one of them the same header** |
| trailing non-frame bytes | none |

⭐ **The duration is arithmetic that closes.** MPEG-2 Layer III is 576 samples
per frame, so 123 × 576 ÷ 24000 = 2.952 s exactly — which is the figure the
service put in `Narrate-Seconds` and in the stored record. The parser, the
service and the engine agree, and the agreement was derived independently here
rather than read out of one of them.

⭐ **And so does the byte count, with nothing left over.** A frame at this
bitrate is (576 ÷ 8) × 128000 ÷ 24000 = **384 bytes**, so 123 × 384 = 47 232,
plus the 44-byte leading tag = **47 276 — the `Content-Length` exactly.** ⛔ No
unexplained byte in the response, which is the check that separates *"it
parsed"* from *"it is entirely accounted for"*: a parser can stop early and
still report a plausible duration.

### Concatenation, on real output

A longer placeholder text (4319 characters, past the 1800-character chunk
budget) came back as `Narrate-Chunks: 3`, 3 830 148 bytes, 239.376 s.
`describe` read **9974 frames at 24000 Hz** and 9974 × 576 ÷ 24000 = 239.376 s,
again exact.

⭐ **Two inter-frame ID3 tags, one per join.** `mpeg.py` predicted exactly this
shape — "every piece carries its own tag" — and until this run that branch had
only ever seen tags a test constructed. Real joins take it. No trailing bytes,
no sample-rate disagreement across the three pieces. ⭐ **This one closes on
bytes too:** 9974 × 384 + 44 + (2 × 44) = 3 830 148, the whole body.

### Idempotency, against the real engine

Re-sending the first request returned the same artifact id with
`Narrate-Cached: true` and the same `Narrate-Seconds`, so the content address
holds over a real synthesis and not only over a fake one.

### The voice catalogue

```
python3 -m tools.reconcile_voices http://<engine on the project network>:8880/v1
declared 68   served 68   same order: True
```

⭐ **`kokoro.py`'s `VOICE_IDS` is re-confirmed at the digest it claims.** It was
a measurement somebody else took; this is a second, independent one, and it
found no drift in either direction.

---

## ⛔ What this run refuted

⭐ **`tests/support.py` said the fixture matched the engine. It does not.** The
docstring read *"only MPEG-1 Layer III at 44.1 kHz is built here, because that
is what the engine emits"*, and the engine emits **MPEG-2 Layer III at 24 kHz,
mono**. The correction is in that file; the reading above is the evidence.

⚠️ **The consequence is a real coverage gap, and it is the one a fake engine is
structurally unable to show you.** `_read_header` has two arms — MPEG-1 uses
`_BITRATES_V1_L3` and 1152 samples per frame, MPEG-2 uses `_BITRATES_V2_L3` and
576 — and **every frame the suite builds takes the MPEG-1 arm while every frame
production sees takes the MPEG-2 arm.** The arm that runs in the deployment had
never executed against a real byte until this run. ⭐ **It is correct** — the
duration arithmetic closes twice above, at two lengths — but it was correct
untested, which is luck rather than evidence.

⛔ **The gap was closed by ADDING, never by changing `FRAME_SAMPLE_RATE`.** The
synthetic frames are built from the specification on purpose, and a suite that
only built what today's engine happens to emit would stop testing the parser
and start testing the engine. What was wrong was the *claim*, not the fixture.
So `tests/support.py` gained `one_frame_mpeg2()` beside `one_frame()` and
`tests/test_mpeg.py` gained the MPEG-2 arm, including a refusal case for a
stream that mixes the two.

⭐ **The new builder is derived, and one test asserts it equals the header
measured above** — so the fixture and this document are pinned to each other. If
the engine's output ever changes shape, that test is what says so.

## How to re-take it

```bash
docker compose up -d --build
# wait for health rather than sleeping
docker inspect -f '{{.State.Health.Status}}' narrate-service-narrate-1
curl -fsS -X POST http://127.0.0.1:8870/v1/speech \
     -H 'Content-Type: application/json' \
     -d '{"text": "Synthesis is behind an API of its own."}' -o speech.mp3
python3 -c 'from narrate import mpeg; print(mpeg.describe(open("speech.mp3","rb").read()))'
docker compose down
```

⛔ **`docker compose down` without `-v`.** The artifacts volume is named rather
than a bind precisely so no host path is ever written into this repository;
removing it is a separate decision and not part of taking a reading.
