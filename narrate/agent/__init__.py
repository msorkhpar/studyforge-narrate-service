"""The agent-callable adapter: synthesis over a stdio tool protocol.

    python3 -m narrate agent

⭐ **Optional, and the whole service works without it.** Nothing under
`narrate/` imports this package: the container's `CMD` is `serve`, no compose
profile starts it, and `narrate/__main__.py` imports it inside the one branch
that runs it. ⛔ **That is a property rather than a claim** -- start the serve
path in a fresh interpreter and `narrate.agent` is absent from `sys.modules`,
which is what `tests/test_agent.py` asserts, in a subprocess.

## ⛔ THE PROTOCOL STREAM CARRIES PROTOCOL BYTES AND NOTHING ELSE

⚠️ **This is the carried lesson `E13` says cost a debugging session, and it is
an acceptance clause rather than advice.** The transport is newline-delimited
JSON-RPC 2.0 on stdout. A single stray `print`, a warning, or a traceback on
that stream corrupts it, and the client drops the connection reporting only a
parse error -- with nothing pointing at the print that caused it.

⭐ **So `run_adapter` rebinds `sys.stdout` to stderr for the whole run and
keeps the real handle privately**, exactly as CodeSignal's tool server did. A
careless print anywhere beneath this package -- in the chunker, in an engine
adapter, in the store -- degrades to a log line instead of breaking the
transport. ⛔ **`protocol.py` writes to the private handle and to nothing
else**, and committed control `p18` removes the rebinding to prove the test
that names this property really fires.

## ⛔ IT CALLS THE SERVICE'S FUNCTIONS, NOT THE SERVICE'S HTTP API

`run_job` is a plain function returning a plain dictionary and needs no HTTP
(`NS-02`). So the adapter builds an engine and a store from the same
environment `serve` reads and calls straight in. ⭐ **Nothing has to be running**
-- an agent narrating one paragraph does not first deploy a web service.

⚠️ **THE PRICE, STATED RATHER THAN DISCOVERED: this is the SECOND WRITING
PROCESS that `narrate.artifacts` says the store does not have.** The publish
lock is in-process, and `artifacts.put`'s docstring names one serving process
per deployment as the shape the service is run in. ⛔ **Point this adapter at a
running deployment's artifact directory and that premise is gone**: two
processes racing one address can publish one synthesis's audio beside the
other's record. Both halves stay complete and valid -- the unique temporary
guarantees that -- and only the byte count and duration would belong to the
twin.

⭐ **By default they do NOT share a store, and that is measurable rather than
hoped for**: the container sets `NARRATE_ARTIFACT_DIR=/var/lib/narrate/artifacts`
onto a named volume, while this adapter run on a host takes `config`'s default,
a relative `artifacts` directory beside the working directory. ⛔ **Sharing is
therefore something an operator has to do deliberately**, and it is declared as
`shares_the_store: false` in `consuming.json` so a consumer reads the condition
rather than inferring it.

## ⛔ NO PERSONAL-DATA GATE LIVES HERE, AND THAT IS NOT AN OVERSIGHT

`E13` rules the gate client-side and pre-request (R7, `NS-05`), and this
package is inside the service. ⚠️ **The caller of this adapter is an agent, so
the AGENT is the gate's owner** -- there is no `narrate.client` between it and
the engine. ⛔ **Every tool description below says so in the text the model
actually reads**, because a rule that only exists in a docstring is a rule the
caller never sees. An mp3 that speaks an account identifier cannot be grepped
for afterwards.
"""

from .protocol import SERVER_NAME, SERVER_VERSION, handle, run_adapter, serve_stdio
from .tools import TOOLS, call_tool

__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "TOOLS",
    "call_tool",
    "handle",
    "run_adapter",
    "serve_stdio",
]
