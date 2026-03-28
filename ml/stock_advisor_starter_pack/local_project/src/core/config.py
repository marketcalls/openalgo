from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_structured_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    suffix = config_path.suffix.lower()

    if suffix == ".json":
        return json.loads(text)

    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"YAML support requires PyYAML for config file: {config_path}"
        ) from exc


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
