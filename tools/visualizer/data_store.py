"""Data access helpers for archived Lean visualizer runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parser import extract_orders_from_detailed


def read_index(results_dir: Path) -> list[dict[str, Any]]:
    path = results_dir / "index.json"
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        return []

    return [entry for entry in data if isinstance(entry, dict)]


def load_run_payload(results_dir: Path, run_id: str) -> dict[str, Any] | None:
    run_file = results_dir / "runs" / run_id / "normalized.json"
    if not run_file.exists():
        return None

    with run_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        return None

    # Backward compatibility: older payloads may miss parsed orders.
    if not data.get("orders"):
        detailed_path = results_dir / "runs" / run_id / "raw-detailed.json"
        if detailed_path.exists():
            with detailed_path.open("r", encoding="utf-8") as handle:
                detailed = json.load(handle)
            if isinstance(detailed, dict):
                data["orders"] = extract_orders_from_detailed(detailed)

    if "orders" not in data:
        data["orders"] = []

    return data


def latest_run_id(results_dir: Path) -> str | None:
    entries = read_index(results_dir)
    if not entries:
        return None

    run_id = entries[0].get("runId")
    if isinstance(run_id, str) and run_id:
        return run_id
    return None
