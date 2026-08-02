#!/usr/bin/env python3
"""Detect unlocked check-then-act on persisted state.

Finds an ``if <attr> ...`` guard followed by an augmented assignment to the
*same* attribute inside one function, and reports whether the module holds any
lock at all. Under eventlet these sequences cannot interleave; under gthread
they can, so a guard-then-mutate on a balance, quantity or counter becomes a
lost update.

This class of defect lives in transaction boundaries rather than in shared
objects, so sweeps that look for module-level mutable state do not find it.

Usage:
    uv run python scripts/gthread_check_then_act.py services blueprints database sandbox
"""

import ast
import pathlib
import sys

SKIP = (
    ".venv",
    "node_modules",
    "__pycache__",
    "/test/",
    ".claude/",
    "examples/",
    "scripts/",
    "download/",
)
# Application code only. Passing explicit paths overrides this.
DEFAULT_ROOTS = (
    "services",
    "blueprints",
    "database",
    "sandbox",
    "utils",
    "subscribers",
    "websocket_proxy",
    "broker",
    # Added after the SIP backtester merged: these were never scanned, so the
    # gate reported "clean" while three application packages sat outside it.
    # A gate is only as good as what it looks at.
    "portfolio",
    "sip",
    "events",
    "restx_api",
    "upgrade",
)
ALLOWLIST = "scripts/gthread_check_then_act_reviewed.txt"


def load_allowlist() -> set[str]:
    """``path:lineno`` entries already classified as safe, one per line.

    Keeping the classification next to the detector is what turns this from a
    report into a gate: a new unlocked pair fails CI until someone records a
    decision for it.
    """
    path = pathlib.Path(ALLOWLIST)
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def attr_chain(node: ast.AST) -> str:
    """Render a dotted attribute path, e.g. ``funds.available_balance``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def lock_guarded_lines(fn: ast.AST) -> set[int]:
    """Line numbers inside a ``with <...lock...>:`` block within this function.

    Module-level lock usage is not sufficient: what matters is whether the
    guard and the mutation are both inside the *same* held lock.
    """
    covered: set[int] = set()
    for node in ast.walk(fn):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        text = " ".join(ast.dump(item.context_expr) for item in node.items).lower()
        if "lock" not in text:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if hasattr(sub, "lineno"):
                    covered.add(sub.lineno)
    return covered


def scan(path: pathlib.Path) -> list[tuple]:
    """Return every guard-then-mutate pair found in one file."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    hits = []
    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for fn in functions:
        covered = lock_guarded_lines(fn)

        # Collect guards and mutations separately, then pair them by source
        # order. ast.walk yields breadth-first, so pairing during the walk can
        # report a mutation that textually precedes its "guard".
        guards: list[tuple[int, str]] = []
        mutations: list[tuple[int, str]] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Attribute):
                        guards.append((node.lineno, attr_chain(sub)))
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
                mutations.append((node.lineno, attr_chain(node.target)))
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                # Plain self-referential assignment: x.attr = x.attr - amount
                target = node.targets[0]
                if not isinstance(target, ast.Attribute):
                    continue
                name = attr_chain(target)
                reads = {
                    attr_chain(s) for s in ast.walk(node.value) if isinstance(s, ast.Attribute)
                }
                if name in reads:
                    mutations.append((node.lineno, name))

        for mut_line, target in mutations:
            # A guard only counts when it textually precedes the mutation.
            preceding = [ln for ln, name in guards if name == target and ln < mut_line]
            if not preceding:
                continue
            guard_line = max(preceding)
            # Protected only when BOTH the guard and the mutation sit inside a
            # held lock in this function.
            locked = guard_line in covered and mut_line in covered
            hits.append((path.as_posix(), guard_line, mut_line, target, fn.name, locked))
    return hits


def main() -> int:
    roots = [pathlib.Path(p) for p in (sys.argv[1:] or DEFAULT_ROOTS)]
    files: list[pathlib.Path] = []
    for root in roots:
        files.extend([root] if root.is_file() else root.rglob("*.py"))

    hits = []
    for path in sorted(set(files)):
        if any(skip in path.as_posix() for skip in SKIP):
            continue
        hits.extend(scan(path))

    allowlist = load_allowlist()
    unlocked = [h for h in hits if not h[5]]
    unreviewed = [h for h in unlocked if f"{h[0]}:{h[2]}" not in allowlist]

    print(
        f"check-then-act pairs: {len(hits)}  unlocked: {len(unlocked)}  "
        f"unreviewed: {len(unreviewed)}\n"
    )
    for file, guard_line, mutate_line, target, fn, locked in hits:
        if locked:
            state = "LOCKED    "
        elif f"{file}:{mutate_line}" in allowlist:
            state = "REVIEWED  "
        else:
            state = "UNREVIEWED"
        print(f"  {state} {file}:{guard_line}->{mutate_line}  {fn}()  guards+mutates {target}")

    if unreviewed:
        print(
            f"\nFAIL: {len(unreviewed)} unreviewed unlocked check-then-act pair(s). "
            f"Classify each in {ALLOWLIST} or add a lock."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
