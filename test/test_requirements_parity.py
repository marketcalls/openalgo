"""Every runtime library in pyproject.toml is also in the requirements files.

The dev server and Docker install from pyproject.toml, but native Ubuntu
installs (install.sh, install-multi.sh and update.sh) install from
requirements-nginx.txt, and a manual install uses requirements.txt. A library
added to pyproject.toml alone works everywhere except on the servers most
people run. 2.0.2.6 shipped openscript, litellm, agno and ddgs that way:
OpenScript strategies and the agent failed on every updated Ubuntu install,
while the site itself started and looked healthy.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = ("requirements-nginx.txt", "requirements.txt")


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject() -> dict[str, Requirement]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (Requirement(spec) for spec in data["project"]["dependencies"])
    return {_key(req.name): req for req in requirements}


def _requirements(filename: str) -> dict[str, Requirement]:
    found = {}
    for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        req = Requirement(line)
        found[_key(req.name)] = req
    return found


@pytest.mark.parametrize("filename", REQUIREMENT_FILES)
def test_every_pyproject_dependency_is_listed(filename):
    listed = _requirements(filename)
    missing = sorted(req.name for key, req in _pyproject().items() if key not in listed)
    assert not missing, (
        f"{filename} does not install {', '.join(missing)}, which pyproject.toml "
        "depends on. Add them with the same version as pyproject.toml."
    )


@pytest.mark.parametrize("filename", REQUIREMENT_FILES)
def test_listed_versions_satisfy_pyproject(filename):
    listed = _requirements(filename)
    wrong = []
    for key, wanted in _pyproject().items():
        have = listed.get(key)
        if have is None:
            continue
        pins = [spec.version for spec in have.specifier if spec.operator == "=="]
        if pins:
            wrong += [
                f"{have.name}=={pin} (pyproject.toml wants {wanted.specifier})"
                for pin in pins
                if not wanted.specifier.contains(pin, prereleases=True)
            ]
        elif have.specifier != wanted.specifier:
            wrong.append(f"{have.name}{have.specifier} (pyproject.toml wants {wanted.specifier})")
    assert not wrong, f"{filename} disagrees with pyproject.toml: {'; '.join(wrong)}"
