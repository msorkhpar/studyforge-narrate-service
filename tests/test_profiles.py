"""The two profiles and `consuming.json`, checked against each other.

⛔ **A consumer never reads this repository's Dockerfile or compose file to
work out how to run it** -- `consuming.json` is what it reads. So the failure
this module exists to catch is **drift**: a compose file that changed and a
declaration that did not, which is worse than no declaration at all because a
consumer has no way to see it.

⚠️ **The compose files are read as TEXT, with whole-line comments stripped, and
that is a deliberate limitation rather than an oversight.** This repository is
standard library only and there is no YAML parser to have; a substring check
over the uncommented body is what can honestly be done here. It is enough for
the assertions below, every one of which is about a literal that must or must
not appear -- ⭐ **and the comment stripping is load-bearing, because
`compose.yaml`'s own comments say the words `nvidia` and `devices` while
explaining why the file must not contain them.**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import narrate
from narrate import PROVIDES
from narrate import config as config_module
from narrate import jobs as jobs_module
from narrate.artifacts import ADDRESS_FIELDS, ADDRESS_SCHEME

ROOT = Path(__file__).resolve().parents[1]


def _uncommented(name):
    """A compose file's body: every whole-line comment removed."""
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def contract():
    return json.loads((ROOT / "consuming.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cpu_compose():
    return _uncommented("compose.yaml")


@pytest.fixture(scope="module")
def gpu_compose():
    return _uncommented("compose.gpu.yaml")


class TestTheFileItself:
    def test_it_carries_both_versions_and_they_are_not_the_same_question(self, contract):
        """⛔ The pin file records which BUILD; `provides` records which PROMISE.

        `consuming_api` versions this file's own schema. Conflating any two of
        the three is the defect the file exists to prevent.
        """
        assert contract["consuming_api"] == 1
        # ⛔ ONE source. `narrate.PROVIDES` is what `/healthz` and every
        # manifest report, so a bump in one place and not the other is a
        # failure here rather than a consumer's surprise.
        assert contract["provides"] == PROVIDES
        assert contract["component"] == "narrate-service"

    def test_the_promise_version_is_not_the_build_version(self, contract):
        """⚠️ Three different questions and none substitutes for another.

        The pin file records which BUILD, `provides` which PROMISE, and
        `consuming_api` this file's own SCHEMA (spec R9).
        """
        assert str(contract["provides"]) != narrate.__version__
        assert contract["provides"] != contract["consuming_api"]

    def test_the_LAST_declared_gap_is_closed_and_the_marker_is_EMPTY(self, contract):
        """⭐ The voice catalogue landed the half that was declared absent, and this test is the
        one that was written to fail on this branch.

        ⚠️ **Its previous form asserted the absence**: `not_yet_declared ==
        ["voices"]` and `"voices" not in contract`. ⛔ **Both halves flip
        together or the file lies in one direction or the other** -- a
        declared `voices` block beside a marker still calling it absent, or a
        marker emptied with nothing behind it.
        """
        assert contract["not_yet_declared"] == []
        assert "voices" in contract

    def test_an_EMPTY_marker_still_means_nothing_is_owed(self, contract):
        """⚠️ *Nothing is owed* and *nobody has looked* are different claims.

        ⭐ The key survives as an empty list rather than being deleted,
        because a consumer that found no key at all would be back to the
        inference this marker exists to remove.
        """
        assert "not_yet_declared" in contract
        assert contract["not_yet_declared"] == []


class TestTheProfiles:
    def test_the_default_profile_is_cpu(self, contract):
        """⛔ R15. The path that works anywhere is the one you get by default."""
        assert contract["profiles"]["default"] == "cpu"

    def test_the_cpu_profile_requires_no_gpu_and_no_vendor_runtime(self, contract):
        cpu = contract["profiles"]["cpu"]["requires"]
        assert cpu["gpu"] is False
        assert cpu["vendor_runtime"] is None
        assert cpu["host_driver"] is None
        assert cpu["devices"] == []

    def test_the_cpu_profile_needs_no_opt_in_and_the_gpu_profile_states_its(self, contract):
        assert contract["profiles"]["cpu"]["opt_in"] is None
        assert contract["profiles"]["cpu"]["compose_files"] == ["compose.yaml"]
        gpu = contract["profiles"]["gpu"]
        assert gpu["opt_in"] == "-f compose.yaml -f compose.gpu.yaml"
        assert gpu["compose_files"] == ["compose.yaml", "compose.gpu.yaml"]

    def test_the_gpu_profile_declares_everything_it_needs(self, contract):
        gpu = contract["profiles"]["gpu"]["requires"]
        assert gpu["gpu"] is True
        assert gpu["vendor_runtime"] == "nvidia-container-toolkit"
        assert gpu["devices"][0]["driver"] == "nvidia"

    def test_neither_profile_publishes_the_engine(self, contract):
        for name in ("cpu", "gpu"):
            assert contract["profiles"][name]["engine_published"] is False


class TestTheComposeFilesAgreeWithTheDeclaration:
    def test_each_declared_engine_image_is_in_the_file_that_declares_it(
        self, contract, cpu_compose, gpu_compose
    ):
        assert contract["profiles"]["cpu"]["engine_image"] in cpu_compose
        assert contract["profiles"]["gpu"]["engine_image"] in gpu_compose

    def test_both_engine_images_are_pinned_by_digest(self, contract):
        """A tag is a moving pointer; the digest is what makes it reproducible."""
        for name in ("cpu", "gpu"):
            assert "@sha256:" in contract["profiles"][name]["engine_image"]

    def test_the_default_deployment_names_no_device_and_no_vendor_driver(
        self, cpu_compose
    ):
        """⛔ THE CPU PROPERTY, stated as the absence that produces it.

        A device reservation naming a vendor driver is exactly what makes a
        compose file fail to come up on a machine that has neither.
        """
        assert "nvidia" not in cpu_compose.lower()
        assert "devices" not in cpu_compose
        assert "deploy" not in cpu_compose

    def test_the_overlay_is_the_thing_that_reserves_the_device(self, gpu_compose):
        assert "driver: nvidia" in gpu_compose
        assert "capabilities: [gpu]" in gpu_compose

    def test_the_overlay_changes_the_profile_label_and_nothing_about_the_address(
        self, cpu_compose, gpu_compose
    ):
        """⭐ Switching profiles is a deployment choice, not a code change."""
        assert "NARRATE_ENGINE_PROFILE: cpu" in cpu_compose
        assert "NARRATE_ENGINE_PROFILE: gpu" in gpu_compose
        assert "NARRATE_ENGINE_URL" in cpu_compose
        assert "NARRATE_ENGINE_URL" not in gpu_compose
        assert "image: narrate-service:local" not in gpu_compose

    def test_the_engine_is_published_nowhere_under_either_profile(
        self, cpu_compose, gpu_compose
    ):
        assert "8880:8880" not in cpu_compose
        assert "8880:8880" not in gpu_compose

    def test_no_docker_socket_is_mounted_by_either_profile(
        self, contract, cpu_compose, gpu_compose
    ):
        """⛔ Spec §8.3. Not behind a flag, not "only locally"."""
        assert contract["service"]["docker_socket"] is False
        assert "docker.sock" not in cpu_compose
        assert "docker.sock" not in gpu_compose

    def test_the_declared_host_port_binding_is_loopback_in_the_file(
        self, contract, cpu_compose
    ):
        port = contract["service"]["ports"][0]
        assert port["publish_on_all_interfaces"] is False
        assert f'"{port["host_bind"]}:{port["container"]}:{port["container"]}"' in cpu_compose


class TestTheDeclarationAgreesWithTheCode:
    """⛔ The other drift: a declared default that the service does not use."""

    def _env(self, contract, name):
        for entry in contract["service"]["environment"]:
            if entry["name"] == name:
                return entry
        raise AssertionError(f"{name} is not declared in consuming.json")

    def test_the_engine_closed_set_is_the_one_the_service_enforces(self, contract):
        assert self._env(contract, "NARRATE_ENGINE")["one_of"] == list(
            config_module.SUPPORTED_ENGINES
        )

    def test_the_profile_closed_set_is_the_one_the_service_enforces(self, contract):
        assert self._env(contract, "NARRATE_ENGINE_PROFILE")["one_of"] == list(
            config_module.ENGINE_PROFILES
        )

    @pytest.mark.parametrize("name,attribute", [
        ("NARRATE_ENGINE", "DEFAULT_ENGINE"),
        ("NARRATE_ENGINE_PROFILE", "DEFAULT_ENGINE_PROFILE"),
        ("NARRATE_BIND", "DEFAULT_BIND"),
        ("NARRATE_VOICE", "DEFAULT_VOICE"),
    ])
    def test_each_declared_default_is_the_module_constant(self, contract, name, attribute):
        assert self._env(contract, name)["default"] == getattr(config_module, attribute)

    @pytest.mark.parametrize("name,attribute", [
        ("NARRATE_PORT", "DEFAULT_PORT"),
        ("NARRATE_CHUNK_CHARS", "DEFAULT_CHUNK_CHARS"),
    ])
    def test_each_declared_numeric_default_is_the_module_constant(
        self, contract, name, attribute
    ):
        assert int(self._env(contract, name)["default"]) == getattr(
            config_module, attribute
        )

    def test_the_declared_formats_are_the_closed_set(self, contract):
        assert contract["api"]["formats"] == list(config_module.SUPPORTED_FORMATS)

    def test_the_healthcheck_declaration_matches_the_default_port(self, contract):
        health = contract["service"]["healthcheck"]
        assert health["path"] == "/healthz"
        assert health["port"] == config_module.DEFAULT_PORT
        assert health["expect_status"] == 200

    def test_the_declared_artifact_mount_is_where_the_image_writes(self, contract):
        mount = contract["service"]["mounts"][0]
        assert mount["required"] is True
        assert mount["read_only"] is False
        assert mount["container_path"] in (ROOT / "Dockerfile").read_text(
            encoding="utf-8"
        )


class TestTheBatchDeclarationAgreesWithTheCode:
    """⛔ The third drift, and it is the one the batch job added.

    A manifest is a WIRE shape: it takes no contract row of its own and is
    versioned by `provides`. ⭐ **So the only thing standing
    between a consumer and a silently changed promise is that the declaration
    and the module constants are asserted to be the same lists.**
    """

    @pytest.fixture
    def api(self, contract):
        return contract["api"]

    def test_the_batch_route_is_declared(self, api):
        paths = [(route["method"], route["path"]) for route in api["routes"]]
        assert ("POST", "/v1/jobs") in paths
        assert ("POST", "/v1/speech") in paths

    def test_every_declared_route_is_a_literal_the_server_matches_on(self, api):
        """⭐ Read from the server module's own text, not from a second list.

        Every path this file declares appears in `server.py` as a quoted
        literal -- `/v1/artifacts/{id}` as its prefix constant. A route
        declared here and never routed there fails, which is the drift a
        consumer would otherwise find by getting a `404`.
        """
        served = (ROOT / "narrate" / "server.py").read_text(encoding="utf-8")
        for route in api["routes"]:
            literal = route["path"].replace("{id}", "")
            assert f'"{literal}"' in served, literal

    def test_the_status_closed_set_is_the_one_the_runner_uses(self, api):
        assert api["manifest"]["segment_statuses"] == list(
            jobs_module.SEGMENT_STATUSES
        )

    def test_the_failure_reason_closed_set_is_the_one_the_runner_uses(self, api):
        assert api["manifest"]["failure_reasons"] == list(
            jobs_module.FAILURE_REASONS
        )

    def test_the_declared_segment_cap_is_the_module_constant(self, api):
        assert api["manifest"]["max_segments"] == jobs_module.MAX_SEGMENTS

    def test_the_declared_body_cap_is_the_module_constant(self, api):
        from narrate.server import MAX_BODY_BYTES
        assert api["max_request_bytes"] == MAX_BODY_BYTES

    def test_only_engine_unavailable_halts_a_job_and_it_is_declared(self, api):
        halts = api["manifest"]["halts_the_job"]
        assert halts == ["engine_unavailable"]
        assert set(halts) <= set(jobs_module.FAILURE_REASONS)

    def test_the_declared_addressing_is_what_the_code_actually_hashes(self, api):
        cache = api["cache"]
        assert cache["scheme"] == ADDRESS_SCHEME
        assert cache["over"] == list(ADDRESS_FIELDS)
        assert cache["order"] == jobs_module.ADDRESSING["order"]
        assert cache["encoding"] == jobs_module.ADDRESSING["encoding"]

    def test_the_declared_VOICES_are_the_ones_the_adapter_offers(self, contract):
        """⛔ The drift this file exists to catch, for the voice catalogue's half.

        ⚠️ **Both directions.** A voice declared and not offered is a caller
        told to use something that will be refused; a voice offered and not
        declared is a real voice a consumer reading the file never learns
        about.
        """
        from narrate.engine.kokoro import VOICE_IDS
        declared = [v["id"] for v in contract["voices"]["catalogue"]]
        assert tuple(declared) == VOICE_IDS
        assert contract["voices"]["count"] == len(VOICE_IDS)

    def test_the_declared_default_voice_is_the_configured_one(self, contract):
        assert contract["voices"]["default"] == config_module.DEFAULT_VOICE
        assert contract["voices"]["default"] in [
            v["id"] for v in contract["voices"]["catalogue"]
        ]

    def test_every_declared_voice_carries_the_four_fields(self, contract):
        """⭐ A consumer picks a voice per corpus, which is a LANGUAGE choice."""
        for entry in contract["voices"]["catalogue"]:
            assert sorted(entry) == ["gender", "id", "language", "name"]
            assert entry["id"] and entry["name"]

    def test_the_declaration_says_the_voice_is_in_the_address(self, contract):
        """⛔ The two claims must agree or a consumer plans a corpus wrongly."""
        assert contract["voices"]["in_the_content_address"] is True
        assert "voice" in contract["api"]["cache"]["over"]

    def test_the_engine_is_declared_ABSENT_from_the_address(self, api):
        """⛔ A consumer plans a redeployment around this fact.

        If the engine were in the address, moving between the cpu and gpu
        profiles of one model would re-synthesise an entire corpus.
        """
        assert api["cache"]["engine_in_address"] is False
        assert "engine" not in api["cache"]["over"]

    def test_the_engine_MODEL_is_declared_PRESENT_and_really_is(self, api):
        """⛔ The opposite claim to the one above, and they are not the same
        question.

        ⚠️ **`engine_in_address: false` was read as covering the model and it
        never did.** The family and the hardware profile are outside the
        address; the model is inside it, because it decides how a voice
        sounds. A declaration that said only the first left a consumer to
        infer the second, and the inference was wrong.
        """
        assert api["cache"]["engine_model_in_address"] is True
        assert "engine_model" in api["cache"]["over"]
        assert "engine_model" in ADDRESS_FIELDS

    def test_the_declared_idempotence_is_not_a_claim_the_code_contradicts(self, api):
        assert api["cache"]["content_addressed"] is True
        assert api["cache"]["idempotent"] is True
        assert "cached" in jobs_module.SEGMENT_STATUSES

    def test_the_manifest_declares_that_a_well_formed_job_is_always_two_hundred(self, api):
        assert api["manifest"]["http_status_for_a_well_formed_job"] == 200
        assert api["manifest"]["one_entry_per_submitted_id"] is True

    def test_the_manifest_declares_the_key_that_versions_it(self, api):
        """⛔ The promise register, not a tenth `*_api`."""
        assert api["manifest"]["versioned_by"] == "provides"
        assert "manifest_api" not in api


class TestTheOptionalAdapterIsDeclaredAsOptional:
    """⛔ The optional adapter. A consumer must not read the Dockerfile to learn this (R19).

    ⚠️ **The condition worth declaring is not that the adapter exists** -- it is
    that it is a second WRITING PROCESS and does not share a store by default.
    A consumer that pointed it at a live deployment's artifact directory would
    be breaking a premise `narrate/artifacts.py` states and nothing enforces.
    """

    def test_the_declared_command_is_the_one_the_entry_point_accepts(self, contract):
        from narrate.__main__ import COMMANDS
        assert contract["agent"]["command"] == ["python3", "-m", "narrate", "agent"]
        assert contract["agent"]["command"][-1] in COMMANDS

    def test_the_declared_tools_are_the_ones_the_adapter_dispatches(self, contract):
        from narrate.agent.tools import DISPATCH
        assert contract["agent"]["tools"] == list(DISPATCH)

    def test_it_is_declared_optional_and_the_deployment_agrees(self, contract):
        assert contract["agent"]["optional"] is True
        assert contract["agent"]["started_by_any_compose_profile"] is False
        assert contract["agent"]["in_the_container_command"] is False
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert 'CMD ["python3", "-m", "narrate", "serve"]' in dockerfile

    def test_the_store_sharing_condition_is_declared_and_not_left_to_inference(
        self, contract
    ):
        """⚠️ Declared `false` BY DEFAULT, with the reason, rather than omitted."""
        assert contract["agent"]["shares_the_store"] is False
        note = contract["agent"]["shares_the_store_note"]
        assert "SECOND WRITING PROCESS" in note
        assert "in-process" in note


class TestTheProvidesGateActuallyGates:
    """⛔ A version field that does not move when its own
    definition says it must is a gate that has stopped gating.

    ⭐ **`provides` is defined in `docs/api.md` as the version of "the routes,
    the manifest's shape, and the cache's behaviour".** ⚠️ **Nothing made that
    mechanical** — it relied on whoever changed one of the three remembering
    what the definition said, and the office that changed two of them did not.

    ⛔ **So the three components are PINNED here beside the number.** A change
    to any of them fails this class, which is the moment the bump question has
    to be answered rather than remembered. ⭐ It does not decide the answer: a
    taker may bump `provides` or argue the change is invisible to a consumer —
    but not silently.
    """

    #: The observable promise at `provides == 2`. ⛔ Update WITH the bump, in
    #: the same commit, or explain in the handoff why the change is invisible.
    PROMISED_ROUTES = (
        ("GET", "/healthz"),
        ("GET", "/v1/voices"),
        ("POST", "/v1/speech"),
        ("POST", "/v1/jobs"),
        ("GET", "/v1/artifacts/{id}"),
    )
    PROMISED_MANIFEST_KEYS = (
        "addressing", "counts", "format", "ok", "provides", "segments", "voice",
    )
    PROMISED_ADDRESS_SCHEME = "narrate-address-3"

    def test_the_number_itself(self):
        assert PROVIDES == 3

    def test_the_routes_are_the_ones_this_promise_names(self, contract):
        actual = tuple((r["method"], r["path"]) for r in contract["api"]["routes"])
        assert actual == self.PROMISED_ROUTES

    def test_the_manifest_shape_is_the_one_this_promise_names(self):
        """⭐ Read from a real manifest, never from a second hand-kept list."""
        from narrate.artifacts import ArtifactStore
        from narrate.config import FORMAT_MEDIA_TYPES
        from narrate.jobs import parse_job, run_job
        from tests.support import FakeEngine
        import tempfile

        engine = FakeEngine()
        with tempfile.TemporaryDirectory() as directory:
            job = parse_job({"segments": [{"id": "s1", "text": "Prose."}]},
                            default_voice="am_liam",
                            catalogue=engine.voices())
            manifest = run_job(job, engine=engine,
                               store=ArtifactStore(directory), chunk_chars=1800,
                               media_types=FORMAT_MEDIA_TYPES, provides=PROVIDES)
        assert tuple(sorted(manifest)) == self.PROMISED_MANIFEST_KEYS

    def test_the_cache_behaviour_is_the_one_this_promise_names(self, contract):
        assert contract["api"]["cache"]["scheme"] == self.PROMISED_ADDRESS_SCHEME
        assert ADDRESS_SCHEME == self.PROMISED_ADDRESS_SCHEME

    def test_2_IS_a_published_version_now_so_3_is_the_next_one(self):
        """⚠️ Why `3`, and why the previous round's argument does not apply.

        ⛔ **The reasoning this replaces was correct WHEN IT WAS WRITTEN and is
        not correct now**, and that is the whole content of this test. It ran:
        *"version 2 has never left this repository, so the churn inside it is
        not a version a consumer could have built against, and bumping to 3
        would leave a phantom 2 that nobody can name."*

        ⭐ **Version 2 has since merged.** It is obtainable, so its promise is
        real and the next change to any of the three pinned components is a
        new number rather than more churn inside an unpublished one. ⚠️ **The
        mechanical rule applies BETWEEN published versions, and 2 is now one
        of them.**

        ⛔ **The sharpest consequence, recorded here because it is the one a
        consumer feels**: `narrate-address-3` re-addresses every artifact, so
        a store filled under `provides: 2` is a complete cache miss under `3`
        and a corpus is re-synthesised once.
        """
        assert PROVIDES == 3
