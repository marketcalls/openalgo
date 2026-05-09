#!/usr/bin/env python3
"""Persist normalized backtest runs and maintain index metadata."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RUNS_DIR_NAME = "runs"
INDEX_FILE_NAME = "index.json"


@dataclass(frozen=True)
class ArchiveResult:
    run_id: str
    run_dir: Path
    index_path: Path


class ArchiveError(RuntimeError):
    """Raised when run archival fails."""


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip())
    cleaned = cleaned.strip("-")
    return cleaned or "run"


def create_run_id(algorithm_type: str, when: datetime | None = None) -> str:
    instant = when or datetime.now(tz=UTC)
    return f"{instant.strftime('%Y%m%dT%H%M%SZ')}-{_slugify(algorithm_type)}"


def _ensure_dirs(results_dir: Path) -> tuple[Path, Path]:
    runs_dir = results_dir / RUNS_DIR_NAME
    runs_dir.mkdir(parents=True, exist_ok=True)
    index_path = results_dir / INDEX_FILE_NAME
    return runs_dir, index_path


def _read_index(index_path: Path) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []

    with index_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ArchiveError(f"Invalid index format at {index_path}: expected a list")

    return [entry for entry in data if isinstance(entry, dict)]


def _write_json_atomic(path: Path, payload: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    temp.replace(path)


def _copy_if_exists(source: Path | None, destination: Path) -> None:
    if source is None or not source.exists():
        return
    shutil.copy2(source, destination)


def archive_run(
    *,
    results_dir: Path,
    normalized_payload: dict[str, Any],
    artifacts: dict[str, Path | None],
) -> ArchiveResult:
    runs_dir, index_path = _ensure_dirs(results_dir)

    algorithm_type = str(normalized_payload.get("algorithmType", "unknown"))
    run_id = create_run_id(algorithm_type)
    run_dir = runs_dir / run_id

    # Handle possible same-second collisions by appending a counter.
    suffix = 1
    while run_dir.exists():
        run_dir = runs_dir / f"{run_id}-{suffix}"
        suffix += 1

    run_id = run_dir.name
    run_dir.mkdir(parents=True, exist_ok=False)

    normalized_payload = dict(normalized_payload)
    normalized_payload["runId"] = run_id

    payload_path = run_dir / "normalized.json"
    _write_json_atomic(payload_path, normalized_payload)

    _copy_if_exists(artifacts.get("summary_json"), run_dir / "raw-summary.json")
    _copy_if_exists(artifacts.get("detailed_json"), run_dir / "raw-detailed.json")
    _copy_if_exists(artifacts.get("log_txt"), run_dir / "run.log")

    summary = normalized_payload.get("summary") if isinstance(normalized_payload.get("summary"), dict) else {}
    date_range = normalized_payload.get("dateRange") if isinstance(normalized_payload.get("dateRange"), dict) else {}

    index_entries = _read_index(index_path)
    index_entries.append(
        {
            "runId": run_id,
            "algorithmType": algorithm_type,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "status": str(normalized_payload.get("status", "Unknown")),
            "dateRange": {
                "start": str(date_range.get("start", "")),
                "end": str(date_range.get("end", "")),
            },
            "metrics": {
                "netProfitPct": float(summary.get("netProfitPct", 0.0)),
                "drawdownPct": float(summary.get("drawdownPct", 0.0)),
                "sharpeRatio": float(summary.get("sharpeRatio", 0.0)),
                "totalOrders": int(summary.get("totalOrders", 0)),
            },
            "paths": {
                "normalized": str(payload_path.relative_to(results_dir)),
                "runDir": str(run_dir.relative_to(results_dir)),
            },
        }
    )

    index_entries.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    _write_json_atomic(index_path, index_entries)

    return ArchiveResult(run_id=run_id, run_dir=run_dir, index_path=index_path)
