"""Validated runtime map for NIFTY constituent futures subscriptions."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


MIN_RAW_WEIGHT_PCT = 90.0
TOP_N_REQUIRED = 10


class ContractMapError(ValueError):
    """Raised when a runtime futures map is unsafe to trade from."""


@dataclass(frozen=True)
class ResolvedFuture:
    nse_symbol: str
    openalgo_symbol: str
    broker_symbol: str
    broker_exchange: str
    token: str
    expiry: date
    lot_size: int
    tick_size: float
    weight_percent: float
    normalized_weight: float
    rank: int

    @property
    def is_top10(self) -> bool:
        return self.rank <= TOP_N_REQUIRED


@dataclass(frozen=True)
class FuturesContractMap:
    resolved_date: date
    common_expiry: date
    raw_weight_covered: float
    source_weight_total: float
    excluded_symbols: tuple[str, ...]
    contracts: tuple[ResolvedFuture, ...]


def load_contract_map(path: str | Path, expected_date: date) -> FuturesContractMap:
    """Load and validate one resolver-produced contract map for a live session."""
    map_path = Path(path)
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractMapError(f"contract map not found: {map_path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractMapError(f"invalid contract map JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ContractMapError("contract map root must be an object")

    resolved_date = _parse_date(payload.get("resolved_date"), "resolved_date")
    if resolved_date != expected_date:
        raise ContractMapError(
            f"contract map is for {resolved_date.isoformat()}, expected {expected_date.isoformat()}"
        )

    common_expiry = _parse_date(payload.get("common_expiry"), "common_expiry")
    if common_expiry < expected_date:
        raise ContractMapError("common expiry is before the session date")

    contracts_payload = payload.get("contracts")
    if not isinstance(contracts_payload, dict) or not contracts_payload:
        raise ContractMapError("contracts must be a non-empty object")

    contracts = tuple(
        _parse_contract(nse_symbol, raw, common_expiry)
        for nse_symbol, raw in contracts_payload.items()
    )
    declared_count = _positive_int(payload.get("resolved_count"), "resolved_count")
    if declared_count != len(contracts):
        raise ContractMapError(
            f"resolved_count={declared_count} does not match {len(contracts)} contracts"
        )

    openalgo_symbols = [contract.openalgo_symbol for contract in contracts]
    if len(openalgo_symbols) != len(set(openalgo_symbols)):
        raise ContractMapError("duplicate OpenAlgo futures symbols")

    top10_ranks = {contract.rank for contract in contracts if contract.is_top10}
    if top10_ranks != set(range(1, TOP_N_REQUIRED + 1)):
        raise ContractMapError("contract map does not contain every top-10 rank")

    raw_weight = _finite_float(payload.get("raw_weight_covered"), "raw_weight_covered")
    calculated_raw_weight = sum(contract.weight_percent for contract in contracts)
    if not math.isclose(raw_weight, calculated_raw_weight, abs_tol=0.011):
        raise ContractMapError(
            f"raw_weight_covered={raw_weight:.4f} does not match contracts={calculated_raw_weight:.4f}"
        )
    if raw_weight < MIN_RAW_WEIGHT_PCT:
        raise ContractMapError(
            f"raw weight coverage {raw_weight:.2f}% is below {MIN_RAW_WEIGHT_PCT:.2f}%"
        )

    normalized_total = sum(contract.normalized_weight for contract in contracts)
    if not math.isclose(normalized_total, 1.0, abs_tol=1e-6):
        raise ContractMapError(f"normalized weights sum to {normalized_total:.8f}, expected 1")

    return FuturesContractMap(
        resolved_date=resolved_date,
        common_expiry=common_expiry,
        raw_weight_covered=raw_weight,
        source_weight_total=_finite_float(payload.get("source_weight_total"), "source_weight_total"),
        excluded_symbols=tuple(str(value) for value in payload.get("excluded_symbols", [])),
        contracts=tuple(sorted(contracts, key=lambda contract: contract.rank)),
    )


def _parse_contract(nse_symbol: Any, raw: Any, common_expiry: date) -> ResolvedFuture:
    if not isinstance(nse_symbol, str) or not nse_symbol.strip():
        raise ContractMapError("contract key must be a non-empty NSE symbol")
    if not isinstance(raw, dict):
        raise ContractMapError(f"contract {nse_symbol} must be an object")

    expiry = _parse_date(raw.get("expiry"), f"{nse_symbol}.expiry")
    if expiry != common_expiry:
        raise ContractMapError(f"{nse_symbol} expiry does not match common_expiry")

    return ResolvedFuture(
        nse_symbol=nse_symbol.strip().upper(),
        openalgo_symbol=_required_string(raw.get("openalgo_symbol"), f"{nse_symbol}.openalgo_symbol"),
        broker_symbol=_required_string(raw.get("broker_symbol"), f"{nse_symbol}.broker_symbol"),
        broker_exchange=_required_string(raw.get("broker_exchange"), f"{nse_symbol}.broker_exchange"),
        token=_required_string(raw.get("token"), f"{nse_symbol}.token"),
        expiry=expiry,
        lot_size=_positive_int(raw.get("lotsize"), f"{nse_symbol}.lotsize"),
        tick_size=_positive_float(raw.get("tick_size"), f"{nse_symbol}.tick_size"),
        weight_percent=_positive_float(raw.get("weight_percent"), f"{nse_symbol}.weight_percent"),
        normalized_weight=_positive_float(
            raw.get("normalized_weight"), f"{nse_symbol}.normalized_weight"
        ),
        rank=_positive_int(raw.get("rank"), f"{nse_symbol}.rank"),
    )


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ContractMapError(f"{field} must be a date string")
    for date_format in ("%Y-%m-%d", "%d-%b-%y", "%d-%B-%y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ContractMapError(f"{field} has unsupported date value: {value}")


def _required_string(value: Any, field: str) -> str:
    if value is None or not str(value).strip():
        raise ContractMapError(f"{field} must be non-empty")
    return str(value).strip()


def _finite_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractMapError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ContractMapError(f"{field} must be finite")
    return parsed


def _positive_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed <= 0:
        raise ContractMapError(f"{field} must be positive")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    parsed = _positive_float(value, field)
    if not parsed.is_integer():
        raise ContractMapError(f"{field} must be an integer")
    return int(parsed)