from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any


def discover_strategy_paths(strategy_root: str | Path) -> list[Path]:
    return sorted(Path(strategy_root).glob("*.py"))


def extend_source_path(source_root: str | Path) -> list[str]:
    root = Path(source_root)
    added: list[str] = []
    for path in [root, *[candidate for candidate in root.rglob("*") if candidate.is_dir()]]:
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            added.append(path_str)
    return added


def extract_default_constants(path: str | Path) -> dict[str, Any]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="ignore"))
    defaults: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("DEFAULT_"):
                    try:
                        defaults[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        continue
    return defaults


def load_module(path: str | Path):
    module_path = Path(path)
    extend_source_path(module_path.parent)
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create import spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_path.stem] = module
    spec.loader.exec_module(module)
    return module


def get_calculate_signature_defaults(module) -> dict[str, Any]:
    if not hasattr(module, "calculate_indicators"):
        return {}
    signature = inspect.signature(module.calculate_indicators)
    defaults: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "df":
            continue
        if parameter.default is inspect._empty:
            continue
        defaults[name] = parameter.default
    return defaults
