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

SKIP = (".venv", "node_modules", "__pycache__", "/test/")


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
        guards: dict[str, int] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Attribute):
                        guards[attr_chain(sub)] = node.lineno
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
                target = attr_chain(node.target)
                if target in guards:
                    # Protected only when BOTH the guard and the mutation sit
                    # inside a held lock in this function.
                    locked = guards[target] in covered and node.lineno in covered
                    hits.append(
                        (path.as_posix(), guards[target], node.lineno, target, fn.name, locked)
                    )
    return hits


def main() -> int:
    roots = [pathlib.Path(p) for p in sys.argv[1:]] or [pathlib.Path(".")]
    files: list[pathlib.Path] = []
    for root in roots:
        files.extend([root] if root.is_file() else root.rglob("*.py"))

    hits = []
    for path in sorted(set(files)):
        if any(skip in path.as_posix() for skip in SKIP):
            continue
        hits.extend(scan(path))

    print(f"check-then-act on persisted attributes: {len(hits)}\n")
    for file, guard_line, mutate_line, target, fn, locked in hits:
        state = "LOCKED  " if locked else "UNLOCKED"
        print(f"  {state} {file}:{guard_line}->{mutate_line}  {fn}()  guards+mutates {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
