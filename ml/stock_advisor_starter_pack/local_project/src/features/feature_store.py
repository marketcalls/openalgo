"""
feature_store.py — Offline Parquet Feature Store
==================================================
Saves and loads versioned feature DataFrames as Parquet files with
schema validation against ``feature_schema.json``.

Store layout:
    {store_root}/{symbol}/{version}/features.parquet
    {store_root}/{symbol}/{version}/metadata.json

Usage:
    from features.feature_store import save_features, load_features, list_versions

    save_features(df, symbol="RELIANCE", version="v1", store_root=Path("feature_store"))
    df = load_features(symbol="RELIANCE", version="v1", store_root=Path("feature_store"))
    versions = list_versions(symbol="RELIANCE", store_root=Path("feature_store"))
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Canonical 12-feature schema produced by build_regime_features()
# (7 original + 5 new from Week 2: ist_hour, session_norm, rsi_14, atr_14, atr_pct)
_REQUIRED_FEATURES = [
    "return_1",
    "return_5",
    "volatility_10",
    "volume_zscore_10",
    "close_ma_5",
    "close_ma_20",
    "ma_spread",
    "rsi_14",
    "atr_14",
    "atr_pct",
    # time-of-day features are optional (only present when datetime column is available)
    # "ist_hour",
    # "session_norm",
]

# Columns that must always be present regardless of optional features
_CORE_REQUIRED = set(_REQUIRED_FEATURES)


def _version_dir(symbol: str, version: str, store_root: Path) -> Path:
    return store_root / symbol / version


def save_features(
    df: pd.DataFrame,
    symbol: str,
    version: str,
    store_root: Path,
    validate: bool = True,
) -> Path:
    """Persist feature DataFrame as Parquet with schema metadata.

    Parameters
    ----------
    df:
        Feature DataFrame produced by ``build_regime_features()``.
    symbol:
        Ticker symbol (e.g. ``"RELIANCE"``).
    version:
        Version string (e.g. ``"v1"`` or a timestamp).
    store_root:
        Root directory for the feature store.
    validate:
        When True, raises ``ValueError`` if required feature columns are missing.

    Returns
    -------
    Path to the saved features.parquet file.
    """
    if validate:
        missing = _CORE_REQUIRED - set(df.columns)
        if missing:
            raise ValueError(
                f"Feature DataFrame is missing required columns: {sorted(missing)}"
            )

    out_dir = _version_dir(symbol, version, store_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "features.parquet"
    df.to_parquet(parquet_path, index=False)

    metadata = {
        "symbol":          symbol,
        "version":         version,
        "n_rows":          len(df),
        "columns":         list(df.columns),
        "saved_at_utc":    datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return parquet_path


def load_features(
    symbol: str,
    version: str,
    store_root: Path,
    validate: bool = True,
) -> pd.DataFrame:
    """Load a versioned feature DataFrame from the store.

    Parameters
    ----------
    symbol:
        Ticker symbol.
    version:
        Version string.
    store_root:
        Root directory for the feature store.
    validate:
        When True, raises ``ValueError`` if required feature columns are missing.

    Returns
    -------
    The feature DataFrame.
    """
    parquet_path = _version_dir(symbol, version, store_root) / "features.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"No features found for symbol={symbol!r} version={version!r} "
            f"in store_root={store_root!r}"
        )

    df = pd.read_parquet(parquet_path)

    if validate:
        missing = _CORE_REQUIRED - set(df.columns)
        if missing:
            raise ValueError(
                f"Loaded features are missing required columns: {sorted(missing)}"
            )

    return df


def load_metadata(symbol: str, version: str, store_root: Path) -> dict:
    """Load the metadata JSON for a specific version."""
    meta_path = _version_dir(symbol, version, store_root) / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"No metadata found for symbol={symbol!r} version={version!r}"
        )
    return json.loads(meta_path.read_text(encoding="utf-8"))


def list_versions(symbol: str, store_root: Path) -> list[str]:
    """Return all saved versions for a symbol, sorted chronologically by save time.

    Versions without a valid metadata.json are skipped.
    """
    symbol_dir = store_root / symbol
    if not symbol_dir.exists():
        return []

    versions_with_time: list[tuple[str, str]] = []
    for version_dir in symbol_dir.iterdir():
        if not version_dir.is_dir():
            continue
        meta_path = version_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            saved_at = meta.get("saved_at_utc", "")
        except (json.JSONDecodeError, OSError):
            saved_at = ""
        versions_with_time.append((version_dir.name, saved_at))

    versions_with_time.sort(key=lambda t: t[1])
    return [v for v, _ in versions_with_time]
