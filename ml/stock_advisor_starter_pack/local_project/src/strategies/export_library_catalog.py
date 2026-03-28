from __future__ import annotations

import json
from pathlib import Path

from core.constants import DEFAULT_STRATEGY_ROOT
from strategies.library_catalog import build_source_library_catalog


def export_library_catalog(output_path: str | Path) -> Path:
    catalog = build_source_library_catalog(DEFAULT_STRATEGY_ROOT)
    destination = Path(output_path)
    destination.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return destination


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    print(export_library_catalog(root / "examples" / "source_library_catalog.json"))
