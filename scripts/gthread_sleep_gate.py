#!/usr/bin/env python3
"""Find sleeps that would hold a gthread request thread or stall a lock.

Under gthread every request runs on one of a fixed number of real threads, so
a sleep on the request path holds that thread for its whole length, and a
sleep while holding a lock holds every other thread that wants the lock too.
Under eventlet the same sleep only parked a greenlet. This gate fails on:

1. **A sleep inside ``with <lock>:``** (``time.sleep`` or ``eventlet.sleep``)
   in code request threads run. Copy what you need, release, then wait.
2. **``eventlet.sleep`` outside an eventlet-only branch.** Under gthread it is
   a plain ``time.sleep`` at best and imports eventlet at worst. It is allowed
   inside an ``if`` whose test mentions eventlet or monkey patching.
3. **A long or unbounded sleep** in ``blueprints``, ``restx_api`` or
   ``services``: a constant of 5 seconds or more, or any sleep inside
   ``while True``. Background loops legitimately do this.

A site that has been looked at is recorded once per function in
``scripts/gthread_sleep_reviewed.txt`` as ``path::qualname  # reason`` and is
then reported, never failed: ``benign`` for a background thread or a bounded,
intended wait, ``pending <owner>`` for a real cost whose fix belongs to
another change. A sleep under a lock should only ever be recorded as pending.

It also prints an inventory of every sleep by folder, for information only:
it is not a count the tree must match.

Not scanned: ``websocket_proxy/`` and ``broker/*/streaming/`` (their own
process or thread, per CLAUDE.md), ``test/`` and ``scripts/``.

Exit status 1 when a site fails and is not reviewed, 0 otherwise.

Usage:
    uv run python scripts/gthread_sleep_gate.py [--strict] [paths...]
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "gthread_sleep_reviewed.txt"

REQUEST_ROOTS = (
    "app.py",
    "extensions.py",
    "blueprints",
    "restx_api",
    "services",
    "database",
    "sandbox",
    "utils",
    "subscribers",
    "events",
    "portfolio",
    "sip",
    "openscript_host",
    "mcp",
    "broker/*/api",
)
LONG_SLEEP_ROOTS = ("blueprints", "restx_api", "services")
EXEMPT_TOP = {"websocket_proxy", "test", "scripts"}
EXEMPT_ANY = {"streaming", "__pycache__"}
LONG_SECONDS = 5.0


@dataclass(frozen=True)
class Site:
    path: str
    qualname: str
    line: int
    rule: str
    call: str

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}"


def _source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _sleep_names(tree: ast.Module) -> dict[str, str]:
    """Bare names bound to a sleep function by ``from X import sleep``."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("time", "eventlet", "gevent"):
            for alias in node.names:
                if alias.name == "sleep":
                    names[alias.asname or alias.name] = node.module
    return names


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str, sleep_names: dict[str, str], long_rules: bool):
        self.path = path
        self.sleep_names = sleep_names
        self.long_rules = long_rules
        self.stack: list[str] = []
        self.lock_depth = 0
        self.loop_depth = 0
        self.eventlet_branch = 0
        self.sites: list[Site] = []
        self.inventory: Counter = Counter()

    @property
    def qualname(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _scope(self, node, name):
        self.stack.append(name)
        saved = (self.lock_depth, self.loop_depth)
        self.lock_depth = self.loop_depth = 0
        self.generic_visit(node)
        self.lock_depth, self.loop_depth = saved
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._scope(node, node.name)

    def visit_With(self, node):
        locked = any("lock" in _source(item.context_expr).lower() for item in node.items)
        self.lock_depth += locked
        self.generic_visit(node)
        self.lock_depth -= locked

    visit_AsyncWith = visit_With

    def visit_While(self, node):
        endless = isinstance(node.test, ast.Constant) and bool(node.test.value)
        self.loop_depth += endless
        self.generic_visit(node)
        self.loop_depth -= endless

    def visit_If(self, node):
        test = _source(node.test).lower()
        eventlet_only = "eventlet" in test or "monkey_patched" in test
        self.visit(node.test)
        self.eventlet_branch += eventlet_only
        for stmt in node.body:
            self.visit(stmt)
        self.eventlet_branch -= eventlet_only
        for stmt in node.orelse:
            self.visit(stmt)

    def _module_of(self, call: ast.Call) -> str | None:
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            owner = _source(func.value)
            if owner in ("time", "eventlet", "eventlet.greenthread", "gevent"):
                return owner.split(".")[0]
            if owner.endswith("real_threading"):
                return "time"
            return None
        if isinstance(func, ast.Name) and func.id in self.sleep_names:
            return self.sleep_names[func.id]
        return None

    def visit_Call(self, node):
        module = self._module_of(node)
        if module is not None:
            call = _source(node)
            self.inventory[module] += 1
            if self.lock_depth:
                self.sites.append(Site(self.path, self.qualname, node.lineno, "under-lock", call))
            if module == "eventlet" and not self.eventlet_branch:
                self.sites.append(
                    Site(self.path, self.qualname, node.lineno, "eventlet-outside-branch", call)
                )
            if self.long_rules:
                seconds = node.args[0] if node.args else None
                constant = (
                    isinstance(seconds, ast.Constant)
                    and isinstance(seconds.value, (int, float))
                    and seconds.value >= LONG_SECONDS
                )
                if constant:
                    self.sites.append(Site(self.path, self.qualname, node.lineno, "long", call))
                elif self.loop_depth:
                    self.sites.append(Site(self.path, self.qualname, node.lineno, "loop", call))
        self.generic_visit(node)


def _files(roots) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        matches = sorted(ROOT.glob(root)) if any(c in root for c in "*?[") else [ROOT / root]
        for match in matches:
            if match.is_file() and match.suffix == ".py":
                files.append(match)
            elif match.is_dir():
                files.extend(sorted(match.rglob("*.py")))
    seen, unique = set(), []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        parts = rel.split("/")
        if rel in seen or parts[0] in EXEMPT_TOP or EXEMPT_ANY & set(parts[:-1]):
            continue
        seen.add(rel)
        unique.append(path)
    return unique


def scan_file(path: Path, display: str, long_rules: bool) -> tuple[list[Site], Counter]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return [], Counter()
    scanner = _Scanner(display, _sleep_names(tree), long_rules)
    scanner.visit(tree)
    return scanner.sites, scanner.inventory


def load_allowlist(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for raw in path.read_text(encoding="utf-8").splitlines():
        body, _, comment = raw.partition("#")
        if body.strip():
            entries[body.strip()] = comment.strip()
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--allowlist", default=str(ALLOWLIST))
    parser.add_argument("--strict", action="store_true", help="fail on stale allowlist entries")
    args = parser.parse_args(argv)

    if args.paths:
        files = []
        for raw in args.paths:
            path = Path(raw).resolve()
            files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    else:
        files = _files(REQUEST_ROOTS)

    sites: list[Site] = []
    inventory: Counter = Counter()
    for path in files:
        try:
            display = path.relative_to(ROOT).as_posix()
        except ValueError:
            display = path.as_posix()
        long_rules = bool(args.paths) or display.split("/")[0] in LONG_SLEEP_ROOTS
        found, counts = scan_file(path, display, long_rules)
        sites.extend(found)
        folder = display.split("/")[0] if "/" in display else display
        for module, count in counts.items():
            inventory[(folder, module)] += count

    allowlist = load_allowlist(Path(args.allowlist))
    hard = [s for s in sites if s.rule in ("under-lock", "eventlet-outside-branch")]
    soft = [s for s in sites if s.rule in ("long", "loop")]
    failing = [s for s in sites if s.key not in allowlist]
    matched = {s.key for s in sites}
    stale = sorted(key for key in allowlist if key not in matched)

    print("Sleep inventory (information only):")
    for (folder, module), count in sorted(inventory.items()):
        print(f"  {folder:<20} {module:<10} {count:>4}")
    print(
        f"\nsleep gate: {len(files)} files, {len(hard)} under a lock or outside an eventlet "
        f"branch, {len(soft)} long or looping, {len(sites) - len(failing)} reviewed"
    )
    for site in sorted(sites, key=lambda s: (s.path, s.line)):
        reviewed = site.key in allowlist
        state = "REVIEWED" if reviewed else "FAIL    "
        print(f"  {state} {site.path}:{site.line}  {site.qualname}  {site.rule}  {site.call}")
        if reviewed and allowlist[site.key]:
            print(f"           {allowlist[site.key]}")
    if stale:
        print(f"\n{len(stale)} allowlist entr{'y' if len(stale) == 1 else 'ies'} no longer match:")
        for key in stale:
            print(f"  STALE {key}")
    if failing:
        print(
            f"\nFAIL: {len(failing)} sleep(s). Never sleep while holding a lock; keep "
            "eventlet.sleep inside an eventlet-only branch; record a reviewed background "
            f"loop in {Path(args.allowlist).name}."
        )
        return 1
    if stale and args.strict:
        print("\nFAIL: stale allowlist entries (--strict).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
