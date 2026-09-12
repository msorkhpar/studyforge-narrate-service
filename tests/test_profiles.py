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

from narrate import config as config_module

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
        the three is the defect the file exists to prevent (spec, Ruling 5).
        """
        assert contract["consuming_api"] == 1
        assert contract["provides"] == 1
        assert contract["component"] == "narrate-service"

    def test_the_half_this_task_does_not_own_is_declared_absent(self, contract):
        """⚠️ Voices are `NS-04`'s half. Absence is NAMED, not left to inference.

        A consumer that found no `voices` key and no marker could not tell
        "this service has no voices" from "nobody has written that part yet".
        """
        assert contract["not_yet_declared"] == ["voices"]
        assert "voices" not in contract


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
