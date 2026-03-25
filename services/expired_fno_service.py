# services/expired_fno_service.py
"""
Expired F&O Service Layer

Orchestrates 3-phase pipeline for downloading historical OHLCV data
for expired Futures & Options contracts via Upstox's expired-instruments API.

Phase 1 - Expiry Discovery:   fetch available expiry dates from Upstox API
Phase 2 - Contract Mapping:   fetch all CE/PE/FUT contracts per expiry, generate symbols
Phase 3 - Data Download:      fetch 1-minute OHLCV for each contract, store in DuckDB

Currently supports Upstox only (requires Plus Plan).
Other brokers can be added by extending EXPIRED_FNO_CAPABLE_BROKERS.
"""

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd

from broker.upstox.api.expired_data import (
    SUPPORTED_UNDERLYINGS,
    UNDERLYING_EXCHANGE,
    UPSTOX_INSTRUMENT_KEYS,
    UpstoxExpiredDataClient,
    resolve_underlying_key,
)
from database.auth_db import get_auth_token_broker
from database.historify_db import (
    create_expired_fno_job,
    get_all_expired_fno_jobs,
    get_expired_fno_contracts,
    get_expired_fno_expiries,
    get_expired_fno_job,
    get_expired_fno_stats,
    get_last_candle_timestamp,
    get_pending_expired_fno_contracts,
    mark_expired_fno_contract_done,
    update_expired_fno_job,
    upsert_expired_fno_contracts,
    upsert_expired_fno_expiries,
    upsert_market_data,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Brokers with verified expired F&O API support
EXPIRED_FNO_CAPABLE_BROKERS: set[str] = {"upstox"}

# Job cancellation signal: set of job IDs that have been cancelled
_cancelled_jobs: set[str] = set()


# =============================================================================
# OpenAlgo Symbol Generator (ported from ExpiryTrack)
# =============================================================================

_SYMBOL_MAPPING: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
    "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX50": "SENSEX50",
    "Nifty 50": "NIFTY",
    "Nifty Bank": "BANKNIFTY",
    "Bank Nifty": "BANKNIFTY",
}


def _format_expiry_date(expiry_date: str) -> str:
    """Convert YYYY-MM-DD expiry date to DDMMMYY format (e.g., 28MAR24)."""
    try:
        dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        return dt.strftime("%d%b%y").upper()
    except Exception:
        return expiry_date


def _extract_base_symbol(trading_symbol: str) -> str:
    """Extract base underlying symbol from an Upstox trading symbol string."""
    pattern = r"(\d{2}[A-Z]{3}\d{2,4}|\d{5,}CE|\d{5,}PE|FUT$)"
    base = re.sub(pattern, "", trading_symbol).strip()
    for upstox_sym, oa_sym in _SYMBOL_MAPPING.items():
        if upstox_sym.upper() in base.upper() or base.upper() in upstox_sym.upper():
            return oa_sym
    return re.sub(r"[\s\-_]", "", base).upper()


def _generate_future_symbol(trading_symbol: str, expiry_date: str) -> str:
    """Generate OpenAlgo future symbol: e.g., BANKNIFTY28MAR24FUT."""
    base = _extract_base_symbol(trading_symbol)
    date_str = _format_expiry_date(expiry_date)
    return f"{base}{date_str}FUT"


def _generate_option_symbol(
    trading_symbol: str, expiry_date: str, strike_price: float, option_type: str
) -> str:
    """Generate OpenAlgo option symbol: e.g., NIFTY28MAR2420800CE."""
    base = _extract_base_symbol(trading_symbol)
    date_str = _format_expiry_date(expiry_date)
    strike_str = (
        str(int(strike_price)) if strike_price == int(strike_price) else str(strike_price)
    )
    option_type = option_type.upper()
    if option_type not in ("CE", "PE"):
        option_type = "CE" if "CE" in trading_symbol.upper() else "PE"
    return f"{base}{date_str}{strike_str}{option_type}"


def _candles_to_df(candles: list[list]) -> pd.DataFrame:
    """
    Convert Upstox candle list to a pandas DataFrame.

    Upstox returns: [[ISO_timestamp, open, high, low, close, volume, oi], ...]
    Output DataFrame: timestamp (Unix epoch int), open, high, low, close, volume, oi
    """
    if not candles:
        return pd.DataFrame()

    rows = []
    for c in candles:
        try:
            ts = int(pd.to_datetime(c[0]).timestamp())
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": int(c[5]),
                    "oi": int(c[6]) if len(c) > 6 else 0,
                }
            )
        except Exception as e:
            logger.debug(f"Skipping malformed candle {c}: {e}")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# =============================================================================
# Broker Capability
# =============================================================================


def get_expired_fno_capability(api_key: str) -> tuple[bool, dict[str, Any], int]:
    """
    Check if the user's active broker supports expired F&O data.

    Args:
        api_key: OpenAlgo API key for the logged-in user

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        result = get_auth_token_broker(api_key)
        auth_token, broker = result[0], result[1]

        supported = broker in EXPIRED_FNO_CAPABLE_BROKERS if broker else False
        return (
            True,
            {
                "status": "success",
                "supported": supported,
                "broker": broker,
                "note": (
                    "Requires Upstox Plus Plan" if broker == "upstox" and supported else None
                ),
                "supported_underlyings": SUPPORTED_UNDERLYINGS if supported else [],
            },
            200,
        )
    except Exception as e:
        logger.exception(f"Error checking expired F&O capability: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Phase 1 — Expiry Discovery
# =============================================================================


def fetch_expiries(
    underlying: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Phase 1: Fetch available expiry dates from Upstox and cache in DuckDB.

    Args:
        underlying: OpenAlgo underlying symbol (e.g., "NIFTY", "BANKNIFTY")
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        underlying = underlying.upper()
        resolved = resolve_underlying_key(underlying)
        if resolved is None:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Cannot resolve '{underlying}'. "
                    "Ensure master contracts are downloaded and the symbol is correct. "
                    f"Supported indices: {', '.join(SUPPORTED_UNDERLYINGS)}",
                },
                400,
            )
        upstox_key, exchange = resolved

        result = get_auth_token_broker(api_key)
        auth_token, broker = result[0], result[1]
        if not auth_token or broker not in EXPIRED_FNO_CAPABLE_BROKERS:
            return (
                False,
                {
                    "status": "error",
                    "message": "Expired F&O data requires an active Upstox broker session.",
                },
                400,
            )

        client = UpstoxExpiredDataClient(auth_token)
        expiries = client.get_expiries(upstox_key)

        if not expiries:
            return (
                False,
                {
                    "status": "error",
                    "message": "No expiries returned from Upstox. "
                    "Verify your Upstox Plus Plan is active.",
                },
                422,
            )

        rows = [
            {
                "upstox_key": upstox_key,
                "openalgo_symbol": underlying,
                "exchange": exchange,
                "expiry_date": e,
                "is_weekly": _is_weekly_expiry(e),
            }
            for e in expiries
        ]

        upsert_expired_fno_expiries(rows)

        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "expiry_count": len(expiries),
                "expiries": expiries,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error fetching expiries for {underlying}: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_cached_expiries(underlying: str) -> tuple[bool, dict[str, Any], int]:
    """
    Return expiry dates cached in DuckDB for an underlying.

    Args:
        underlying: OpenAlgo underlying symbol

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        underlying = underlying.upper()
        resolved = resolve_underlying_key(underlying)
        if resolved is None:
            return (
                False,
                {"status": "error", "message": f"Unsupported underlying '{underlying}'"},
                400,
            )
        upstox_key, _exchange = resolved
        expiries = get_expired_fno_expiries(upstox_key)

        from database.historify_db import get_expired_fno_expiry_stats
        stats = get_expired_fno_expiry_stats(upstox_key)
        for exp in expiries:
            exp_stats = stats.get(exp["expiry_date"], {})
            exp["total_contracts"] = exp_stats.get("total_contracts", 0)
            exp["downloaded_contracts"] = exp_stats.get("downloaded_contracts", 0)

        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "expiries": expiries,
                "count": len(expiries),
            },
            200,
        )
    except Exception as e:
        logger.exception(f"Error getting cached expiries: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Phase 2 — Contract Mapping
# =============================================================================


def fetch_contracts_for_expiry(
    underlying: str,
    expiry_dates: str | list[str],
    contract_types: list[str],
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Phase 2: Fetch contracts for one or more expiries and cache in DuckDB.

    Args:
        underlying: OpenAlgo underlying symbol (e.g., "NIFTY")
        expiry_dates: One expiry date or list in YYYY-MM-DD format
        contract_types: List from ["CE", "PE", "FUT"]
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        underlying = underlying.upper()
        contract_types = [c.upper() for c in contract_types]
        # Normalise to list and strip time component
        if isinstance(expiry_dates, str):
            expiry_dates = [expiry_dates]
        expiry_dates = [d.split("T")[0] for d in expiry_dates]
        # Keep compat: first expiry_date for legacy single-expiry callers
        expiry_date = expiry_dates[0]

        resolved = resolve_underlying_key(underlying)
        if resolved is None:
            return (
                False,
                {"status": "error", "message": f"Unsupported underlying '{underlying}'"},
                400,
            )
        upstox_key, exchange = resolved

        result = get_auth_token_broker(api_key)
        auth_token, broker = result[0], result[1]
        if not auth_token or broker not in EXPIRED_FNO_CAPABLE_BROKERS:
            return (
                False,
                {
                    "status": "error",
                    "message": "Expired F&O data requires an active Upstox broker session.",
                },
                400,
            )

        client = UpstoxExpiredDataClient(auth_token)

        needs_options = any(c in contract_types for c in ("CE", "PE"))
        needs_futures = "FUT" in contract_types

        all_contract_rows: list[dict[str, Any]] = []

        for exp in expiry_dates:
            contract_rows: list[dict[str, Any]] = []

            if needs_options:
                raw_options = client.get_option_contracts(upstox_key, exp)
                for c in raw_options:
                    option_type = _infer_option_type(c)
                    if option_type not in contract_types:
                        continue
                    strike = float(c.get("strike_price", 0))
                    trading_sym = c.get("trading_symbol", "")
                    contract_rows.append(
                        {
                            "expired_instrument_key": c.get("instrument_key", ""),
                            "upstox_key": upstox_key,
                            "openalgo_symbol": _generate_option_symbol(
                                underlying, exp, strike, option_type
                            ),
                            "exchange": exchange,
                            "expiry_date": exp,
                            "contract_type": option_type,
                            "strike_price": strike,
                            "trading_symbol": trading_sym,
                            "lot_size": c.get("lot_size"),
                        }
                    )

            if needs_futures:
                raw_futures = client.get_future_contracts(upstox_key, exp)
                for c in raw_futures:
                    trading_sym = c.get("trading_symbol", "")
                    contract_rows.append(
                        {
                            "expired_instrument_key": c.get("instrument_key", ""),
                            "upstox_key": upstox_key,
                            "openalgo_symbol": _generate_future_symbol(underlying, exp),
                            "exchange": exchange,
                            "expiry_date": exp,
                            "contract_type": "FUT",
                            "strike_price": None,
                            "trading_symbol": trading_sym,
                            "lot_size": c.get("lot_size"),
                        }
                    )

            # Filter out rows with empty expired_instrument_key
            all_contract_rows.extend(r for r in contract_rows if r["expired_instrument_key"])

        upsert_expired_fno_contracts(all_contract_rows)

        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "expiry_dates": expiry_dates,
                "contract_count": len(all_contract_rows),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error fetching contracts for {underlying} {expiry_dates}: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_cached_contracts(
    underlying: str, expiry_dates: str | list[str]
) -> tuple[bool, dict[str, Any], int]:
    """
    Return contracts cached in DuckDB for an underlying + one or more expiries.

    Args:
        underlying: OpenAlgo underlying symbol
        expiry_dates: One or more expiry dates in YYYY-MM-DD format

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        underlying = underlying.upper()
        if isinstance(expiry_dates, str):
            expiry_dates = [expiry_dates]
        expiry_dates = [d.split("T")[0] for d in expiry_dates]

        resolved = resolve_underlying_key(underlying)
        if resolved is None:
            return (
                False,
                {"status": "error", "message": f"Unsupported underlying '{underlying}'"},
                400,
            )
        upstox_key, _exchange = resolved
        contracts: list[dict[str, Any]] = []
        for exp in expiry_dates:
            contracts.extend(get_expired_fno_contracts(upstox_key, exp))

        return (
            True,
            {
                "status": "success",
                "underlying": underlying,
                "expiry_dates": expiry_dates,
                "contracts": contracts,
                "count": len(contracts),
            },
            200,
        )
    except Exception as e:
        logger.exception(f"Error getting cached contracts: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Phase 3 — Data Download
# =============================================================================


def start_expired_fno_download(
    underlying: str,
    expiry_dates: list[str] | str | None,
    contract_types: list[str],
    api_key: str,
    look_back: str = "6M",
    incremental: bool = True,
) -> tuple[bool, dict[str, Any], int]:
    """
    Phase 3: Create a download job and submit it to the shared thread executor.

    Args:
        underlying: OpenAlgo underlying (e.g., "NIFTY")
        expiry_dates: One or more expiries in YYYY-MM-DD, or None for all expiries
        contract_types: List from ["CE", "PE", "FUT"]
        api_key: OpenAlgo API key
        look_back: Period to fetch ('1M','3M','6M','1Y','2Y','5Y')
        incremental: If True, only download candles newer than the last stored timestamp

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        underlying = underlying.upper()
        contract_types = [c.upper() for c in contract_types]

        resolved = resolve_underlying_key(underlying)
        if resolved is None:
            return (
                False,
                {"status": "error", "message": f"Unsupported underlying '{underlying}'"},
                400,
            )
        upstox_key, exchange = resolved

        result = get_auth_token_broker(api_key)
        auth_token, broker = result[0], result[1]
        if not auth_token or broker not in EXPIRED_FNO_CAPABLE_BROKERS:
            return (
                False,
                {
                    "status": "error",
                    "message": "Expired F&O data requires an active Upstox broker session.",
                },
                400,
            )

        # Normalise expiry_dates
        if isinstance(expiry_dates, str):
            expiry_dates = [expiry_dates]
        if expiry_dates:
            expiry_dates = [d.split("T")[0] for d in expiry_dates]

        # When incremental=True include already-downloaded contracts (for top-up)
        pending = get_pending_expired_fno_contracts(
            upstox_key, expiry_dates, contract_types,
            include_downloaded=incremental,
        )
        if not pending:
            return (
                False,
                {
                    "status": "error",
                    "message": "No contracts found. "
                    "Fetch contracts first (Phase 2), or all contracts are already downloaded.",
                },
                400,
            )

        job_id = str(uuid.uuid4())
        # Store multiple expiries as pipe-separated string (or None for "all")
        expiry_str = "|".join(expiry_dates) if expiry_dates else None
        job_record = {
            "id": job_id,
            "underlying": underlying,
            "exchange": exchange,
            "expiry_date": expiry_str,
            "contract_types": ",".join(contract_types),
            "interval": "1m",
            "status": "pending",
            "total_contracts": len(pending),
        }
        create_expired_fno_job(job_record)

        _get_executor().submit(
            _process_expired_fno_job, job_id, auth_token, pending, look_back, incremental
        )

        return (
            True,
            {
                "status": "success",
                "job_id": job_id,
                "total_contracts": len(pending),
                "underlying": underlying,
                "expiry_dates": expiry_dates,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error starting expired F&O download: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def _process_expired_fno_job(
    job_id: str,
    auth_token: str,
    contracts: list[dict[str, Any]],
    look_back: str = "6M",
    incremental: bool = True,
) -> None:
    """
    Background worker: download OHLCV for each contract and store in DuckDB.

    Uses 4 parallel threads for API calls (I/O bound) with a shared lock
    serialising DuckDB writes.  The Upstox rate-limiter is already thread-safe
    so all workers share the same request budget.

    Emits historify_progress Socket.IO events so the frontend progress bar
    picks them up automatically (same event used by regular Historify jobs).
    """
    from extensions import socketio

    NUM_WORKERS = 4

    update_expired_fno_job(job_id, {"status": "running", "started_at": _now_iso()})
    client = UpstoxExpiredDataClient(auth_token)
    total = len(contracts)
    completed = 0
    failed = 0
    db_lock = threading.Lock()

    logger.info(f"[job:{job_id}] Starting parallel download ({NUM_WORKERS} workers) for {total} contracts")

    def _download_one(contract):
        """Download a single contract. Returns ('ok'|'fail'|'cancel', symbol, candle_count)."""
        if job_id in _cancelled_jobs:
            return ("cancel", contract["openalgo_symbol"], 0)

        expired_key = contract["expired_instrument_key"]
        oa_symbol = contract["openalgo_symbol"]
        exchange = contract["exchange"]
        expiry_date = contract["expiry_date"]

        last_ts = (
            get_last_candle_timestamp(oa_symbol, exchange, "1m")
            if incremental
            else None
        )
        to_date, from_date = _calculate_date_range(expiry_date, look_back, last_ts)

        try:
            candles = client.get_historical_data(
                expired_key, from_date=from_date, to_date=to_date
            )
            if candles:
                df = _candles_to_df(candles)
                if not df.empty:
                    with db_lock:
                        records = upsert_market_data(df, oa_symbol, exchange, "1m")
                        mark_expired_fno_contract_done(expired_key, records)
                    return ("ok", oa_symbol, records)
            logger.warning(f"[job:{job_id}] No candles for {oa_symbol}")
            with db_lock:
                mark_expired_fno_contract_done(expired_key, 0)
            return ("fail", oa_symbol, 0)
        except Exception as e:
            logger.exception(f"[job:{job_id}] Error for {oa_symbol}: {e}")
            return ("fail", oa_symbol, 0)

    try:
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            futures = {pool.submit(_download_one, c): c for c in contracts}

            for future in as_completed(futures):
                status, oa_symbol, records = future.result()

                if status == "cancel":
                    logger.info(f"[job:{job_id}] Cancelled by user")
                    # Cancel any futures not yet started
                    for f in futures:
                        f.cancel()
                    update_expired_fno_job(job_id, {"status": "cancelled", "completed_at": _now_iso()})
                    return

                if status == "ok":
                    completed += 1
                    logger.debug(f"[job:{job_id}] {oa_symbol}: {records} candles stored")
                else:
                    failed += 1

                update_expired_fno_job(
                    job_id,
                    {"completed_contracts": completed, "failed_contracts": failed},
                )

                percent = int((completed + failed) / total * 100)
                try:
                    socketio.emit(
                        "historify_progress",
                        {
                            "job_id": job_id,
                            "job_type": "expired_fno",
                            "current": completed + failed,
                            "total": total,
                            "completed": completed,
                            "failed": failed,
                            "percent": percent,
                            "symbol": oa_symbol,
                        },
                    )
                except Exception:
                    pass

        # Only write final status if job was not cancelled mid-run
        if job_id not in _cancelled_jobs:
            final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "completed")
            update_expired_fno_job(
                job_id,
                {"status": final_status, "completed_at": _now_iso()},
            )
            try:
                socketio.emit(
                    "historify_job_complete",
                    {
                        "job_id": job_id,
                        "job_type": "expired_fno",
                        "status": final_status,
                        "completed": completed,
                        "failed": failed,
                        "total": total,
                    },
                )
            except Exception:
                pass
            logger.info(
                f"[job:{job_id}] Finished: {completed} downloaded, {failed} failed / {total} total"
            )
    finally:
        _cancelled_jobs.discard(job_id)


def get_job_status(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get status of an expired F&O download job.

    Args:
        job_id: UUID of the job

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        job = get_expired_fno_job(job_id)
        if job is None:
            return False, {"status": "error", "message": "Job not found"}, 404

        total = job.get("total_contracts", 0)
        done = job.get("completed_contracts", 0) + job.get("failed_contracts", 0)
        percent = int(done / total * 100) if total > 0 else 0

        return (
            True,
            {"status": "success", "job": job, "percent": percent},
            200,
        )
    except Exception as e:
        logger.exception(f"Error getting job status for {job_id}: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def list_jobs(status: str = None, limit: int = 20) -> tuple[bool, dict[str, Any], int]:
    """List recent expired F&O download jobs."""
    try:
        jobs = get_all_expired_fno_jobs(status=status, limit=limit)
        return True, {"status": "success", "jobs": jobs, "count": len(jobs)}, 200
    except Exception as e:
        logger.exception(f"Error listing expired F&O jobs: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def cancel_job(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Request cancellation of a running expired F&O job.

    Args:
        job_id: UUID of the job

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        job = get_expired_fno_job(job_id)
        if job is None:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job.get("status") not in ("pending", "running"):
            return (
                False,
                {"status": "error", "message": f"Cannot cancel job in status '{job['status']}'"},
                400,
            )

        # Signal the background thread to stop at the next contract boundary.
        # Also write to DB here so orphaned jobs (thread dead) and edge cases
        # where the thread finishes just as cancel arrives are handled correctly.
        # The thread's final-status write is guarded by `job_id not in _cancelled_jobs`
        # so it will never overwrite this 'cancelled' write.
        _cancelled_jobs.add(job_id)
        update_expired_fno_job(job_id, {
            "status": "cancelled",
            "completed_at": _now_iso(),
            "error_message": "Cancelled by user",
        })
        return (
            True,
            {"status": "success", "message": "Cancellation requested", "job_id": job_id},
            200,
        )
    except Exception as e:
        logger.exception(f"Error cancelling job {job_id}: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_stats() -> tuple[bool, dict[str, Any], int]:
    """
    Get summary statistics for expired F&O data.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        stats = get_expired_fno_stats()
        return True, {"status": "success", "data": stats}, 200
    except Exception as e:
        logger.exception(f"Error getting expired F&O stats: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Private Helpers
# =============================================================================


def _is_weekly_expiry(expiry_date: str) -> bool:
    """Heuristic: weekly expiries are typically on Thursdays (weekday 3)."""
    try:
        dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        return dt.weekday() == 3  # Thursday
    except Exception:
        return False


def _infer_option_type(contract: dict[str, Any]) -> str:
    """Infer CE/PE from a contract dict's instrument_type or trading_symbol."""
    instrument_type = str(contract.get("instrument_type", "")).upper()
    if instrument_type in ("CE", "PE"):
        return instrument_type
    trading_sym = str(contract.get("trading_symbol", "")).upper()
    if trading_sym.endswith("CE"):
        return "CE"
    if trading_sym.endswith("PE"):
        return "PE"
    return "CE"


_LOOK_BACK_MONTHS: dict[str, int] = {
    "1M": 1,
    "3M": 3,
    "6M": 6,
    "1Y": 12,
    "2Y": 24,
    "5Y": 60,
}


def _calculate_date_range(
    expiry_date: str,
    look_back: str = "6M",
    from_timestamp: int | None = None,
) -> tuple[str, str]:
    """
    Calculate the to/from date range for fetching historical data.

    Args:
        expiry_date: Expiry date in YYYY-MM-DD (used as to_date)
        look_back: Period string '1M'|'3M'|'6M'|'1Y'|'2Y'|'5Y'
        from_timestamp: If provided, use this Unix timestamp as from_date
                        (incremental update — only fetch new candles)

    Returns:
        Tuple of (to_date, from_date) both in YYYY-MM-DD format
    """
    expiry = datetime.strptime(expiry_date, "%Y-%m-%d")

    if from_timestamp is not None:
        # Incremental: start one second after last stored candle
        from_dt = datetime.utcfromtimestamp(from_timestamp + 1)
        return expiry_date, from_dt.strftime("%Y-%m-%d")

    months_back = _LOOK_BACK_MONTHS.get(look_back.upper(), 6)
    month = expiry.month - months_back
    year = expiry.year
    while month <= 0:
        month += 12
        year -= 1
    from_dt = expiry.replace(day=1, year=year, month=month)
    return expiry_date, from_dt.strftime("%Y-%m-%d")


def _now_iso() -> str:
    """Return current UTC datetime as ISO string."""
    return datetime.utcnow().isoformat()


# Shared executor for submitting expired F&O download jobs (one job at a time).
# Parallelism lives inside each job (4 threads per job in _process_expired_fno_job).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="expired_fno_job")


def _get_executor() -> ThreadPoolExecutor:
    """Return the module-level background executor."""
    return _executor
