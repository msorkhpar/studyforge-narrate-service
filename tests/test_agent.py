"""`narrate.agent` -- the agent-callable adapter, and its three acceptances.

> An agent can synthesise a segment through the adapter. A deliberate print
> inside the synthesis path does not break the transport. The adapter is
> optional -- the service works fully without it.

⛔ **THE SECOND AND THIRD ARE DRIVEN IN A REAL SUBPROCESS, and that is not
belt-and-braces.** Both are properties of a *process*: whether a print on the
real stdout file descriptor reaches the client, and whether the serve path
imports this package. ⚠️ **An in-process test answers neither** -- it would
compare a `StringIO` the test itself supplied, and it would read a
`sys.modules` that the rest of the suite had already filled.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from narrate.agent import handle, run_adapter, serve_stdio
from narrate.agent.tools import TOOLS, Adapter, UnknownTool, call_tool
from narrate.artifacts import ArtifactStore
from narrate.config import Config
from narrate.voices import UnknownVoice
from tests.support import NO_SUCH_VOICE, FakeEngine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def adapter(tmp_path):
    """An adapter over a fake engine and a temporary store. No engine needed."""
    engine = FakeEngine()
    built = Adapter(config=Config(artifact_dir=tmp_path), engine=engine)
    built.store = ArtifactStore(tmp_path)
    return built


def rpc(method, request_id=1, **params):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params:
        message["params"] = params
    return message


def payload_of(response):
    """The JSON a tool answered with, decoded from its text content."""
    return json.loads(response["result"]["content"][0]["text"])


class TestAnAgentCanSynthesiseASegment:
    """⭐ The first acceptance, driven through the protocol rather than around it."""

    def test_the_handshake_answers_with_this_server(self, adapter):
        response = handle(rpc("initialize"), adapter)
        assert response["result"]["serverInfo"]["name"] == "narrate-service"
        assert "tools" in response["result"]["capabilities"]

    def test_a_notification_is_never_answered(self, adapter):
        """⛔ A response to a notification is a protocol fault of its own."""
        assert handle({"jsonrpc": "2.0",
                       "method": "notifications/initialized"}, adapter) is None

    def test_the_three_tools_are_listed_with_schemas(self, adapter):
        listed = handle(rpc("tools/list"), adapter)["result"]["tools"]
        assert [t["name"] for t in listed] == [
            "synthesize", "narrate_batch", "voices"
        ]
        for tool in listed:
            assert tool["inputSchema"]["type"] == "object"
            assert tool["description"]

    def test_synthesize_returns_an_address_that_really_holds_audio(self, adapter):
        response = handle(
            rpc("tools/call", name="synthesize",
                arguments={"text": "One spoken unit."}), adapter)
        assert response["result"]["isError"] is False
        body = payload_of(response)
        assert body["cached"] is False
        assert body["seconds"] > 0
        assert adapter.store.read(body["artifact_id"])

    def test_a_second_identical_call_synthesises_NOTHING(self, adapter):
        """⭐ The cache is the service's, not a second one behind this surface.

        ⛔ Asserted on the ENGINE's call list, which is outside the code that
        would otherwise be agreeing with itself.
        """
        arguments = {"text": "One spoken unit."}
        first = payload_of(handle(rpc("tools/call", name="synthesize",
                                      arguments=arguments), adapter))
        calls_after_first = len(adapter.engine.calls)
        second = payload_of(handle(rpc("tools/call", name="synthesize",
                                       arguments=arguments), adapter))

        assert second["artifact_id"] == first["artifact_id"]
        assert second["cached"] is True
        assert len(adapter.engine.calls) == calls_after_first

    def test_narrate_batch_returns_a_manifest_of_every_submitted_id(self, adapter):
        response = handle(
            rpc("tools/call", name="narrate_batch", arguments={"segments": [
                {"id": "s1", "text": "The first unit."},
                {"id": "s2", "text": "The second unit."},
            ]}), adapter)
        manifest = payload_of(response)
        assert [e["id"] for e in manifest["segments"]] == ["s1", "s2"]
        assert manifest["counts"]["total"] == 2
        assert manifest["ok"] is True

    def test_voices_answers_the_catalogue_and_needs_no_engine(self, adapter):
        body = payload_of(handle(rpc("tools/call", name="voices"), adapter))
        assert body["default"] == adapter.config.voice
        assert [v["id"] for v in body["voices"]] == list(
            adapter.catalogue.ids()
        )
        assert adapter.engine.calls == []


class TestWhatTheAdapterRefusesAndHow:
    def test_an_unknown_voice_is_tool_content_and_not_a_protocol_error(
        self, adapter
    ):
        """⛔ The call was well formed and the work did not succeed. A client
        should show the reason to the model, not treat it as a transport
        fault."""
        response = handle(
            rpc("tools/call", name="synthesize",
                arguments={"text": "Prose.", "voice": NO_SUCH_VOICE}), adapter)
        assert "error" not in response
        assert response["result"]["isError"] is True
        assert "voice must be one of" in response["result"]["content"][0]["text"]

    def test_an_unknown_voice_refuses_the_WHOLE_batch(self, adapter):
        response = handle(
            rpc("tools/call", name="narrate_batch",
                arguments={"segments": [{"id": "s1", "text": "Prose."}],
                           "voice": NO_SUCH_VOICE}), adapter)
        assert response["result"]["isError"] is True
        assert adapter.engine.calls == []

    def test_an_unknown_TOOL_is_a_protocol_error(self, adapter):
        """⚠️ The other side of the line: this is not a failed synthesis."""
        response = handle(
            rpc("tools/call", name="no-such-tool", arguments={}), adapter)
        assert response["error"]["code"] == -32601
        assert "synthesize" in response["error"]["message"]

    def test_an_unknown_method_is_a_protocol_error(self, adapter):
        assert handle(rpc("no/such/method"), adapter)["error"]["code"] == -32601

    def test_the_dispatch_table_is_closed_and_not_a_getattr(self, adapter):
        """⛔ `engine/registry.py`'s rule: a name arriving from a client must
        not become an instruction to call an arbitrary method."""
        with pytest.raises(UnknownTool):
            call_tool(adapter, "synthesize_chunk", {})
        with pytest.raises(UnknownTool):
            call_tool(adapter, "__init__", {})

    def test_no_returned_path_leaves_the_store(self, adapter):
        """⛔ R7 and R4. The store directory is a container path or somebody's
        home directory, and the caller does not need it."""
        body = payload_of(handle(
            rpc("tools/call", name="synthesize",
                arguments={"text": "Prose."}), adapter))
        assert "/" not in body["file"]
        assert body["file"].startswith(body["artifact_id"])
        assert body["url"] == f"/v1/artifacts/{body['artifact_id']}"

    def test_a_misspelled_default_voice_refuses_to_build_the_adapter(self, tmp_path):
        with pytest.raises(UnknownVoice):
            Adapter(config=Config(artifact_dir=tmp_path, voice=NO_SUCH_VOICE),
                    engine=FakeEngine())

    def test_every_tool_description_states_the_gate_obligation(self):
        """⛔ The personal-data gate is client-side, and the caller here
        is an agent. ⚠️ A rule that lives only in a docstring is a rule the
        caller never reads -- these are the words the model actually sees."""
        speaking = [t for t in TOOLS if t["name"] != "voices"]
        assert len(speaking) == 2
        for tool in speaking:
            assert "gates personal data" in tool["description"]


class TestTheProtocolStreamCarriesProtocolBytesAndNothingElse:
    """⛔ A lesson carried from earlier work, and an ACCEPTANCE CLAUSE rather than advice."""

    def test_serve_stdio_writes_to_the_handle_it_was_given(self, adapter):
        sink = io.StringIO()
        serve_stdio(io.StringIO(json.dumps(rpc("ping")) + "\n"), sink, adapter)
        assert json.loads(sink.getvalue().strip())["result"] == {}

    def test_an_unparseable_line_is_skipped_and_does_not_kill_the_loop(
        self, adapter
    ):
        sink, noted = io.StringIO(), []
        source = io.StringIO("not json\n\n" + json.dumps(rpc("ping")) + "\n")
        serve_stdio(source, sink, adapter, log=noted.append)
        assert len(sink.getvalue().strip().splitlines()) == 1
        assert any("unparseable" in line for line in noted)

    def test_a_print_inside_the_synthesis_path_does_not_break_the_transport(
        self, tmp_path
    ):
        """⛔ THE CLAUSE, in a real process with a real stdout descriptor.

        ⚠️ **A `StringIO` sink would not test this at all.** The failure is
        that a `print` beneath the adapter reaches the same file descriptor
        the client is parsing; only a real process can exhibit it, and only
        `run_adapter`'s rebinding prevents it.

        ⭐ **The plant is deliberately loud**: a bare print, a warning, and a
        printed traceback, all inside the function that synthesises a chunk.
        Every line the client receives must still parse as JSON, and the
        answer must be the right one.
        """
        harness = textwrap.dedent(f'''
            import sys, traceback, warnings
            sys.path.insert(0, {str(ROOT)!r})
            from narrate.agent import run_adapter
            from narrate.agent.tools import Adapter
            from narrate.config import Config
            from tests.support import FakeEngine, mpeg_bytes

            class NoisyEngine(FakeEngine):
                def synthesize_chunk(self, text, voice, fmt):
                    # ⛔ Three deliberate ways of writing to stdout, inside
                    # the synthesis path.
                    print("a careless print inside the synthesis path")
                    warnings.warn("a warning nobody suppressed")
                    traceback.print_stack()
                    return super().synthesize_chunk(text, voice, fmt)

            adapter = Adapter(config=Config(artifact_dir={str(tmp_path)!r}),
                              engine=NoisyEngine())
            raise SystemExit(run_adapter(adapter=adapter))
        ''')

        lines = [
            json.dumps(rpc("initialize", request_id=1)),
            json.dumps(rpc("tools/call", request_id=2, name="synthesize",
                           arguments={"text": "One spoken unit."})),
        ]
        completed = subprocess.run(
            [sys.executable, "-c", harness],
            input="\n".join(lines) + "\n",
            capture_output=True, text=True, cwd=str(ROOT), check=False,
        )

        assert completed.returncode == 0, completed.stderr
        received = [line for line in completed.stdout.splitlines() if line.strip()]

        # ⛔ EVERY line, not the ones that happen to parse.
        decoded = [json.loads(line) for line in received]
        assert [message["id"] for message in decoded] == [1, 2]
        body = json.loads(decoded[1]["result"]["content"][0]["text"])
        assert body["cached"] is False
        assert body["seconds"] > 0

        # ⭐ The control on the control: the noise really was emitted, and it
        # went to stderr. Without this the test would pass for an engine that
        # printed nothing.
        assert "a careless print inside the synthesis path" in completed.stderr
        assert "a warning nobody suppressed" in completed.stderr
        assert "a careless print" not in completed.stdout


class TestTheAdapterIsOptional:
    """⛔ *"the service works fully without it"*, as a property of the process."""

    def test_the_serve_path_never_imports_the_agent_package(self):
        """⭐ A fresh interpreter, because the suite has already imported it.

        ⛔ This is what makes the lazy import in `narrate/__main__.py` a
        property rather than a comment: move it to the top of that file and
        this fails.
        """
        probe = (
            "import sys; import narrate.__main__, narrate.server; "
            "print('narrate.agent' in sys.modules)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, cwd=str(ROOT), check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "False"

    def test_no_module_the_service_ships_imports_the_adapter_AT_MODULE_LEVEL(self):
        """⛔ Wider than the entry point, and read from the source text.

        ⚠️ **An import at column zero runs when the module is imported**, which
        is what would make the adapter part of the service. An indented one
        runs only when its branch does. ⭐ `narrate/__main__.py` has exactly one
        and it is indented; nothing else has any.
        """
        offenders = []
        for path in sorted((ROOT / "narrate").rglob("*.py")):
            if "agent" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.startswith(("import ", "from ")):
                    continue
                if ".agent" in line or " agent " in line:
                    offenders.append(f"{path.name}:{number}")
        assert offenders == []

    def test_the_container_command_is_serve_and_no_profile_starts_the_adapter(self):
        """⚠️ Deployment, not code: an optional surface that a compose file
        started would not be optional."""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert 'CMD ["python3", "-m", "narrate", "serve"]' in dockerfile
        for name in ("compose.yaml", "compose.gpu.yaml"):
            body = "\n".join(
                line for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            assert "agent" not in body

    def test_the_entry_point_names_both_commands_and_refuses_a_third(self):
        from narrate.__main__ import COMMANDS, main
        assert COMMANDS == ("serve", "agent")
        assert main(["not-a-command"]) == 2
        assert main([]) == 2
