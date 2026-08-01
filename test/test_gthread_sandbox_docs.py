"""Keeps the sandbox concurrency documentation honest (gate A9-11).

An architecture document's normal failure mode is not being wrong when written
-- it is drifting silently afterwards. These checks tie the document to the
code, so a lock that is renamed or removed fails the build instead of quietly
turning the docs into fiction.
"""

import importlib
import importlib.util
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "design" / "07-sandbox" / "README.md"


def _load_real_sandbox(name):
    """`test/sandbox/` shadows the real package under pytest."""
    saved = {k: v for k, v in sys.modules.items() if k == "sandbox" or k.startswith("sandbox.")}
    for key in list(saved):
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "sandbox",
        REPO / "sandbox" / "__init__.py",
        submodule_search_locations=[str(REPO / "sandbox")],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["sandbox"] = package
    spec.loader.exec_module(package)
    try:
        return importlib.import_module(f"sandbox.{name}")
    finally:
        for key in [k for k in sys.modules if k == "sandbox" or k.startswith("sandbox.")]:
            del sys.modules[key]
        sys.modules.update(saved)


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_section_exists(doc):
    assert "## Concurrency Model" in doc


# Every lock the document claims, and where it must actually live.
DOCUMENTED_LOCKS = [
    ("fund_manager", "FundManager", "_lock"),
    ("order_manager", "OrderManager", "_state_lock"),
    ("execution_engine", "ExecutionEngine", "_fill_lock"),
    ("position_manager", "PositionManager", "_settle_lock"),
    ("holdings_manager", "HoldingsManager", "_settlement_lock"),
    ("squareoff_manager", "SquareOffManager", "_squareoff_lock"),
]


@pytest.mark.parametrize("module_name,class_name,lock_name", DOCUMENTED_LOCKS)
def test_every_documented_lock_exists(module_name, class_name, lock_name, doc):
    assert lock_name in doc, f"{lock_name} is not documented"
    module = _load_real_sandbox(module_name)
    cls = getattr(module, class_name)
    assert hasattr(cls, lock_name), f"{class_name}.{lock_name} is documented but does not exist"


def test_documented_module_level_locks_exist(doc):
    for module_name, lock_name in (
        ("catch_up_processor", "_catch_up_lock"),
        ("execution_thread", "_thread_lock"),
    ):
        assert lock_name in doc, f"{lock_name} is not documented"
        module = _load_real_sandbox(module_name)
        assert hasattr(module, lock_name), f"{module_name}.{lock_name} is gone"


def test_no_sandbox_lock_is_undocumented():
    """The reverse direction: a lock added later must be written up, or the
    document quietly becomes a partial picture -- which is more misleading than
    having no table at all."""
    doc_text = DOC.read_text(encoding="utf-8")
    undocumented = []
    for path in sorted((REPO / "sandbox").glob("*.py")):
        for match in re.finditer(r"^\s*(_\w*lock\w*)\s*(?::\s*\w+)?\s*=\s*threading\.R?Lock\(\)",
                                 path.read_text(encoding="utf-8"), re.M | re.I):
            name = match.group(1)
            if name not in doc_text:
                undocumented.append(f"{path.name}:{name}")
    assert undocumented == [], f"locks missing from the concurrency section: {undocumented}"


def test_class_level_convention_is_stated_and_true(doc):
    """Managers are constructed per request, so a per-instance lock guards
    nothing. The document says so; this proves it."""
    assert "class-level, not per-instance" in doc

    for module_name, class_name, lock_name in DOCUMENTED_LOCKS:
        module = _load_real_sandbox(module_name)
        cls = getattr(module, class_name)
        assert lock_name in vars(cls), (
            f"{class_name}.{lock_name} is not defined on the class, so separate "
            "instances would each get their own lock"
        )


def test_the_join_rule_is_documented_and_followed(doc):
    """Rule 1: never hold a lock across a join()."""
    assert "Never hold a lock across a `join()`" in doc

    module = _load_real_sandbox("execution_thread")
    src = inspect.getsource(module.stop_execution_engine)
    assert src.index("_stop_websocket_upgrade_watcher()") < src.index("with _thread_lock:")


def test_the_retry_rules_are_documented(doc):
    """Rules 2 and 3 are the ones whose violation is silent."""
    assert "re-read, never replay" in doc
    assert "No broker or network call inside a retry boundary" in doc


def test_the_missing_unique_constraint_is_disclosed(doc):
    """The in-process lock is the only thing preventing a duplicate trade. That
    is worth stating, because it is the one guarantee that does not survive a
    second process."""
    assert "not** unique" in doc or "not unique" in doc
    assert "UNIQUE" in doc

    module = _load_real_sandbox("execution_engine")
    src = inspect.getsource(module)
    assert "UNIQUE constraint" in src, "the code no longer records the stronger fix"
