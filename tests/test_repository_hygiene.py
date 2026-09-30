"""⭐ What a stranger reads in a clone: the product, and nothing about how it was made.

- ⛔ No task identifier, no requirement number, no "register direction", no
  hand-off and no office in any tracked file. Those are how the work was
  organised, not what the service is, and they mean nothing to a reader.
- ⭐ The README says where the third-party pieces come from, says how to get the
  repository by a clone URL placeholder, and does not assume a checkout.

Tracked files are read from git when it is available and from the tree
otherwise, so the check runs in a plain clone or an unpacked archive.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve()

#: Each pattern is a phrase that only appears when process talk has leaked in.
TRACES = re.compile(
    r"\bNS-\d+"
    r"|\bW\d{3}\b"
    r"|\bREL-\d+"
    r"|\bR\d{1,2}\b"
    r"|\bspec R\d+"
    r"|\bregister (?:direction|ruling)|\ba register\b"
    r"|\bhand-?off\b"
    r"|\boffice\b"
    r"|\bthe user (?:said|asked|ruled|wants)"
    r"|\bruled by\b",
    re.IGNORECASE,
)

TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ""}


def tracked_files() -> list[Path]:
    git = shutil.which("git")
    if git and (ROOT / ".git").exists():
        done = subprocess.run([git, "ls-files"], cwd=ROOT, capture_output=True, text=True)
        if done.returncode == 0:
            return [ROOT / name for name in done.stdout.splitlines()]
    skip = {".git", ".pytest_cache", "__pycache__", "artifacts"}
    return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]


def text_files() -> list[Path]:
    return [
        p for p in tracked_files()
        if p.suffix in TEXT_SUFFIXES and p.resolve() != THIS and p.is_file()
    ]


def test_the_scan_reads_the_files_it_claims_to():
    names = {p.name for p in text_files()}
    assert {"README.md", "consuming.json", "compose.yaml", "api.md", "server.py"} <= names


def test_no_tracked_file_carries_process_phrasing():
    found = []
    for path in text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hit = TRACES.search(line)
            if hit:
                found.append(f"{path.relative_to(ROOT)}:{number}: {hit.group(0)!r}")
    assert not found, "process phrasing in tracked files:\n" + "\n".join(found)


README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_readme_names_the_three_third_party_pieces():
    section = re.search(r"^## Third-party\n(.*?)(?=^## )", README, re.MULTILINE | re.DOTALL)
    assert section, "the README has no Third-party section"
    body = section.group(1)
    for name in ("Kokoro-FastAPI", "Kokoro-82M", "espeak-ng"):
        assert name in body, f"{name} is not named in the Third-party section"


def test_the_readme_starts_from_a_clone_url_placeholder_and_one_compose_command():
    assert "git clone <clone-url>" in README
    assert "docker compose up -d --build" in README


def test_the_readme_says_how_a_client_on_another_machine_reaches_it():
    section = re.search(r"^### Reaching it from another machine\n(.*?)(?=^##)", README, re.MULTILINE | re.DOTALL)
    assert section, "the README has no section on reaching it from another machine"
    body = section.group(1)
    assert "NARRATE_BIND" in body and "127.0.0.1:8870:8870" in body
