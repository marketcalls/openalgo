"""Put the current kit into strategy files, or check that it is there.

Every strategy built by this skill carries the kit (kit.py) as its last block,
from the "# ====" rule above "openalgo-strategy-kit <version> BEGIN" to the end
of the file. Replacing that block is how a strategy takes a newer kit; the
settings and signals above it are never touched.

    uv run python .claude/skills/python-strategy/kit_sync.py --write <file> [...]
    uv run python .claude/skills/python-strategy/kit_sync.py --check [<file> ...]

--check with no files checks the skill's own templates. Exit 1 when a file's
block differs from kit.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent
KIT = SKILL / "kit.py"
MARKER = re.compile(r"^# openalgo-strategy-kit (\S+) BEGIN$")


def kit_text() -> str:
    return KIT.read_text(encoding="utf-8")


def kit_version(text: str | None = None) -> str | None:
    for line in (text if text is not None else kit_text()).splitlines():
        found = MARKER.match(line)
        if found:
            return found.group(1)
    return None


def split(text: str) -> tuple[str, str | None]:
    """(strategy part, kit block or None)."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if MARKER.match(line.rstrip("\n")):
            start = i - 1 if i and lines[i - 1].startswith("# ====") else i
            return "".join(lines[:start]), "".join(lines[start:])
    return text, None


def with_kit(text: str) -> str:
    strategy, _old = split(text)
    return strategy.rstrip() + "\n\n\n" + kit_text()


def check(path: Path) -> list[str]:
    strategy, block = split(path.read_text(encoding="utf-8"))
    if block is None:
        return [f"{path}: no kit block"]
    if block != kit_text():
        have, want = kit_version(block), kit_version()
        if have != want:
            return [f"{path}: kit {have}, current is {want}"]
        return [f"{path}: kit {have} block was edited by hand"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="replace or append the kit block")
    mode.add_argument("--check", action="store_true", help="report files whose block differs")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    files = args.files or sorted((SKILL / "templates").glob("*.py"))
    if args.write:
        for path in files:
            path.write_text(with_kit(path.read_text(encoding="utf-8")), encoding="utf-8")
            print(f"kit {kit_version()} written to {path}")
        return 0
    problems = [p for path in files for p in check(path)]
    for problem in problems:
        print(problem)
    if not problems:
        print(f"{len(files)} file(s) carry kit {kit_version()} unchanged")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
