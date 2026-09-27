"""⭐ A publisher on Windows runs this service from PowerShell, on Docker Desktop.

- ⭐ Every file an image or a shell reads is checked out with LF line ends:
  Git for Windows checks text out CRLF by default, and the image this checkout
  builds would carry a carriage return on every line of what it copies.
- ⭐ The README gives the PowerShell form of each command a POSIX shell spells
  its own way, and no PowerShell block carries a POSIX-only construct.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

#: What a POSIX shell reads and PowerShell does not: a substitution, a line
#: continuation, and a variable set for one command by prefixing it.
POSIX_ONLY = re.compile(r"\$\(|\\\s*$|^[A-Z_]+=\S+ \S", re.MULTILINE)


def blocks(language: str) -> list[str]:
    return re.findall(rf"^```{language}\n(.*?)^```", README, flags=re.MULTILINE | re.DOTALL)


def test_every_file_the_image_reads_is_checked_out_with_lf():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    paths = ("Dockerfile", "compose.yaml", "compose.gpu.yaml", "narrate/__main__.py")
    done = subprocess.run([git, "check-attr", "eol", "--", *paths], cwd=ROOT,
                          capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip("git cannot read this checkout's attributes here")
    assert [line.rsplit(": ", 1)[1] for line in done.stdout.splitlines()] == ["lf"] * len(paths)


def test_every_posix_only_command_has_a_powershell_form():
    posix = [block for block in blocks("bash") if POSIX_ONLY.search(block)]
    assert posix, "the check reads no POSIX-only block: the README moved under it"
    powershell = blocks("powershell")
    assert len(powershell) >= len(posix)


def test_no_powershell_block_carries_a_posix_only_construct():
    for block in blocks("powershell"):
        assert not POSIX_ONLY.search(block), block


def test_the_check_can_say_no():
    assert POSIX_ONLY.search("X=1 python3 -m narrate serve")
    assert POSIX_ONLY.search("curl -fsS \\\n  -o speech.mp3")
    assert not POSIX_ONLY.search("$env:X = '1'; python -m narrate serve")
