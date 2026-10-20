#!/usr/bin/env python3
"""Find check-then-act on shared state that request threads can race on.

Under the eventlet worker a check and the write after it cannot be split by
another request unless something in between yields. Under gthread every
request is a real thread, so ``if X is None: X = make()`` can make two, and
``if key not in cache: cache[key] = load()`` can load twice and keep the
wrong one. This gate finds three shapes of it:

1. **Lazy module globals.** A function declares ``global X``, tests
   ``X is None`` (or ``not X``) and assigns ``X`` in that branch, without a
   lock around the test. A re-check inside ``with <lock>:`` in the branch
   (double-checked locking) counts as locked.
2. **Module-level dict or set check-then-act.** ``if k not in D:`` (or
   ``D.get(k) is None``) followed by ``D[k] = ...``, ``D.add`` or
   ``D.setdefault`` on a dict or set created at module scope, outside a lock.
3. **Guard then augmented assignment** on the same attribute
   (``if acct.balance >= x: acct.balance -= x``), outside a lock.

A "lock" is any ``with`` whose context expression mentions ``lock``
(``with _lock:``, ``with self._lock:``, ``with SYMBOL_LOCKS.hold(...)``).

Scanned: the code request threads run. Not scanned: ``websocket_proxy/`` and
``broker/*/streaming/``, which run in their own process or on their own
thread (CLAUDE.md), plus ``test/`` and ``scripts/``.

**Reviewed sites** live in ``scripts/gthread_check_then_act_reviewed.txt`` as
``path::qualname::target  # reason``, keyed by function rather than line
number so an edit above a site does not invalidate it. A reviewed site is
reported and never fails the gate. Two kinds are recorded: ``benign`` (safe
as written, with the reason) and ``pending`` (a real hazard whose fix belongs
to the named owner). An entry that no longer matches anything is reported
as stale so it can be removed; ``--strict`` makes stale entries fail too.

Exit status 1 when an unreviewed site is found, 0 otherwise.

Usage:
    uv run python scripts/gthread_check_then_act.py [--strict] [paths...]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "gthread_check_then_act_reviewed.txt"

DEFAULT_ROOTS = (
    "app.py",
    "extensions.py",
    "limiter.py",
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
    "upgrade",
    "broker/*/api",
)

#: Top-level folders, and any folder named here anywhere in the path, not scanned.
EXEMPT_TOP = {"websocket_proxy", "test", "scripts"}
EXEMPT_ANY = {"streaming", "__pycache__"}

CONTAINER_CALLS = {"dict", "set", "defaultdict", "OrderedDict", "WeakValueDictionary"}


@dataclass(frozen=True)
class Hit:
    path: str
    qualname: str
    target: str
    rule: str
    line: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}::{self.target}"


def _source(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _is_lock(with_node: ast.With | ast.AsyncWith) -> bool:
    return any("lock" in _source(item.context_expr).lower() for item in with_node.items)


def _walk_shallow(node: ast.AST):
    """Like ast.walk, without descending into nested functions, lambdas or classes."""
    todo = list(ast.iter_child_nodes(node))
    while todo:
        child = todo.pop()
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            todo.extend(ast.iter_child_nodes(child))


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _attr_chain(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _module_containers(tree: ast.Module) -> set[str]:
    """Names bound at module scope to a dict or set."""
    found: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        is_container = isinstance(value, (ast.Dict, ast.Set, ast.DictComp, ast.SetComp))
        if isinstance(value, ast.Call):
            func = value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            is_container = name in CONTAINER_CALLS
        if is_container:
            found.update(t.id for t in targets if isinstance(t, ast.Name))
    return found


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str, containers: set[str]):
        self.path = path
        self.containers = containers
        self.stack: list[str] = []
        self.lock_depth = 0
        self.globals_stack: list[set[str]] = []
        self.hits: list[Hit] = []

    # scopes ---------------------------------------------------------------
    def _scoped(self, node, name: str, is_function: bool):
        self.stack.append(name)
        if is_function:
            declared = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Global):
                    declared.update(sub.names)
            self.globals_stack.append(declared)
            saved_depth, self.lock_depth = self.lock_depth, 0
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._rule_augassign(node)
        self.generic_visit(node)
        if is_function:
            self.globals_stack.pop()
            self.lock_depth = saved_depth
        self.stack.pop()

    def visit_ClassDef(self, node):
        self._scoped(node, node.name, False)

    def visit_FunctionDef(self, node):
        self._scoped(node, node.name, True)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node):
        locked = _is_lock(node)
        self.lock_depth += locked
        self.generic_visit(node)
        self.lock_depth -= locked

    visit_AsyncWith = visit_With

    @property
    def qualname(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _hit(self, target: str, rule: str, line: int):
        self.hits.append(Hit(self.path, self.qualname, target, rule, line))

    # rules 1 and 2 --------------------------------------------------------
    def visit_If(self, node):
        if self.lock_depth == 0 and self.globals_stack:
            self._rule_lazy_global(node)
            self._rule_container(node)
        self.generic_visit(node)

    def _rule_lazy_global(self, node: ast.If):
        declared = self.globals_stack[-1]
        if not declared:
            return
        tested = _names_in(node.test) & declared
        test_src = _source(node.test)
        for name in sorted(tested):
            if f"{name} is None" not in test_src and f"not {name}" not in test_src:
                continue
            assigned = any(
                isinstance(sub, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in sub.targets)
                for stmt in node.body
                for sub in ast.walk(stmt)
            )
            if not assigned:
                continue
            rechecked = any(
                isinstance(sub, (ast.With, ast.AsyncWith)) and _is_lock(sub)
                for stmt in node.body
                for sub in ast.walk(stmt)
            )
            if not rechecked:
                self._hit(name, "lazy-global", node.lineno)

    def _rule_container(self, node: ast.If):
        test = node.test
        candidates: set[str] = set()
        for sub in ast.walk(test):
            if isinstance(sub, ast.Compare) and any(isinstance(op, ast.NotIn) for op in sub.ops):
                for comparator in sub.comparators:
                    if isinstance(comparator, ast.Name) and comparator.id in self.containers:
                        candidates.add(comparator.id)
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get"
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id in self.containers
            ):
                candidates.add(sub.func.value.id)
        for name in sorted(candidates):
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    writes = (
                        isinstance(sub, ast.Assign)
                        and any(
                            isinstance(t, ast.Subscript)
                            and isinstance(t.value, ast.Name)
                            and t.value.id == name
                            for t in sub.targets
                        )
                    ) or (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in ("add", "setdefault")
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == name
                    )
                    if writes:
                        self._hit(name, "container", node.lineno)
                        break
                else:
                    continue
                break

    # rule 3 ---------------------------------------------------------------
    def _rule_augassign(self, fn):
        locked_lines: set[int] = set()
        for sub in _walk_shallow(fn):
            if isinstance(sub, (ast.With, ast.AsyncWith)) and _is_lock(sub):
                for stmt in sub.body:
                    for inner in ast.walk(stmt):
                        if hasattr(inner, "lineno"):
                            locked_lines.add(inner.lineno)
        guards: list[tuple[int, str]] = []
        mutations: list[tuple[int, str]] = []
        for sub in _walk_shallow(fn):
            if isinstance(sub, ast.If):
                for inner in ast.walk(sub.test):
                    if isinstance(inner, ast.Attribute):
                        chain = _attr_chain(inner)
                        if chain:
                            guards.append((sub.lineno, chain))
            elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Attribute):
                chain = _attr_chain(sub.target)
                if chain:
                    mutations.append((sub.lineno, chain))
            elif (
                isinstance(sub, ast.Assign)
                and len(sub.targets) == 1
                and isinstance(sub.targets[0], ast.Attribute)
            ):
                # The same thing spelled out: acct.balance = acct.balance - x
                chain = _attr_chain(sub.targets[0])
                reads = {
                    _attr_chain(inner)
                    for inner in ast.walk(sub.value)
                    if isinstance(inner, ast.Attribute)
                }
                if chain and chain in reads:
                    mutations.append((sub.lineno, chain))
        reported: set[str] = set()
        for line, target in mutations:
            preceding = [g for g, name in guards if name == target and g < line]
            if not preceding or target in reported:
                continue
            guard = max(preceding)
            if guard in locked_lines and line in locked_lines:
                continue
            reported.add(target)
            self.hits.append(
                Hit(self.path, ".".join(self.stack) or "<module>", target, "guard-augassign", line)
            )


def _files(roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        for match in sorted(ROOT.glob(root)) if any(c in root for c in "*?[") else [ROOT / root]:
            if match.is_file() and match.suffix == ".py":
                files.append(match)
            elif match.is_dir():
                files.extend(sorted(match.rglob("*.py")))
    unique = []
    seen = set()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        parts = rel.split("/")
        if rel in seen or parts[0] in EXEMPT_TOP or EXEMPT_ANY & set(parts[:-1]):
            continue
        seen.add(rel)
        unique.append(path)
    return unique


def scan_file(path: Path, display: str | None = None) -> list[Hit]:
    """Return every check-then-act site in one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    scanner = _Scanner(display or path.relative_to(ROOT).as_posix(), _module_containers(tree))
    scanner.visit(tree)
    return scanner.hits


def load_allowlist(path: Path) -> dict[str, str]:
    """Reviewed entries: key to the comment that explains them."""
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for raw in path.read_text(encoding="utf-8").splitlines():
        body, _, comment = raw.partition("#")
        key = body.strip()
        if key:
            entries[key] = comment.strip()
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="files or folders (default: request-path code)")
    parser.add_argument("--allowlist", default=str(ALLOWLIST))
    parser.add_argument("--strict", action="store_true", help="fail on stale allowlist entries")
    args = parser.parse_args(argv)

    if args.paths:
        files = []
        for raw in args.paths:
            path = Path(raw).resolve()
            files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    else:
        files = _files(list(DEFAULT_ROOTS))

    hits: list[Hit] = []
    for path in files:
        try:
            display = path.relative_to(ROOT).as_posix()
        except ValueError:
            display = path.as_posix()
        hits.extend(scan_file(path, display))

    allowlist = load_allowlist(Path(args.allowlist))
    matched = {hit.key for hit in hits}
    unreviewed = [hit for hit in hits if hit.key not in allowlist]
    stale = sorted(key for key in allowlist if key not in matched)

    print(
        f"check-then-act: {len(files)} files, {len(hits)} sites, "
        f"{len(hits) - len(unreviewed)} reviewed, {len(unreviewed)} unreviewed"
    )
    for hit in sorted(hits, key=lambda h: (h.path, h.line)):
        note = allowlist.get(hit.key)
        state = "REVIEWED  " if note is not None else "UNREVIEWED"
        print(f"  {state} {hit.path}:{hit.line}  {hit.qualname}  {hit.rule} {hit.target}")
        if note:
            print(f"             {note}")
    if stale:
        print(f"\n{len(stale)} allowlist entr{'y' if len(stale) == 1 else 'ies'} no longer match:")
        for key in stale:
            print(f"  STALE {key}")
    if unreviewed:
        print(
            f"\nFAIL: {len(unreviewed)} unreviewed check-then-act site(s). Put a lock around "
            f"the check and the write, or record a reason in {Path(args.allowlist).name}."
        )
        return 1
    if stale and args.strict:
        print("\nFAIL: stale allowlist entries (--strict).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
