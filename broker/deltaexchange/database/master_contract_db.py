# database/master_contract_db.py

import os
import time

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your database path

# Create engine with optimized settings for SQLite concurrency
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=50,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={"timeout": 30, "check_same_thread": False},
)

# Enable WAL mode for better concurrent access
try:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("PRAGMA temp_store=memory"))
        conn.execute(text("PRAGMA mmap_size=268435456"))  # 256MB
        conn.commit()
except Exception as e:
    logger.warning(f"Could not set SQLite pragmas for master_contract_db: {e}")

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
    symbol = Column(String, nullable=False, index=True)  # Single column index
    brsymbol = Column(String, nullable=False, index=True)  # Single column index
    name = Column(String)
    exchange = Column(String, index=True)  # Include this column in a composite index
    brexchange = Column(String, index=True)
    token = Column(String, index=True)  # Indexed for performance
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)
    contract_value = Column(Float, default=1.0)  # Underlying units per contract (e.g. 0.01 ETH for ETHUSD.P)

    # Define a composite index on symbol and exchange columns
    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)
    # Idempotent migration: add contract_value column if not already present.
    # Using Inspector (check-before-add) is more reliable than catching exceptions
    # because the error message for "column already exists" varies across SQLite versions.
    try:
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(engine)
        existing_cols = {c["name"] for c in insp.get_columns("symtoken")}
        if "contract_value" not in existing_cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE symtoken ADD COLUMN contract_value REAL DEFAULT 1.0"))
                conn.commit()
                logger.info("Migrated symtoken table: added contract_value column")
    except Exception as e:
        logger.error(
            f"contract_value migration FAILED — master contract insert will fail until "
            f"the column is added. Run: sqlite3 db/openalgo.db "
            f"\"ALTER TABLE symtoken ADD COLUMN contract_value REAL DEFAULT 1.0\" | Error: {e}"
        )


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient="records")

    # Determine which columns actually exist in the DB right now.
    # This guards against a failed/pending migration: if contract_value column
    # was not added yet, strip it from insert dicts rather than failing every chunk.
    try:
        from sqlalchemy import inspect as sa_inspect
        _db_cols = {c["name"] for c in sa_inspect(engine).get_columns("symtoken")}
    except Exception:
        _db_cols = None  # Can't introspect — proceed unfiltered (will fail loudly if needed)

    if _db_cols is not None:
        # Remove any DataFrame columns that don't have a matching DB column
        extra_cols = {k for k in (data_dict[0] if data_dict else {}) if k not in _db_cols}
        if extra_cols:
            logger.warning(f"Stripping unknown columns from insert (migration pending?): {extra_cols}")
            data_dict = [{k: v for k, v in row.items() if k not in extra_cols} for row in data_dict]

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row["token"] not in existing_tokens]

    # Insert in smaller chunks to minimize database lock time
    chunk_size = 500  # Reduced chunk size for shorter lock duration
    total_inserted = 0

    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            logger.info(
                f"Starting bulk insert of {len(filtered_data_dict)} records in chunks of {chunk_size}"
            )

            # Process data in chunks
            for i in range(0, len(filtered_data_dict), chunk_size):
                chunk = filtered_data_dict[i : i + chunk_size]

                # Use a separate transaction for each chunk with retry logic
                try:
                    # Insert chunk
                    db_session.bulk_insert_mappings(SymToken, chunk)
                    db_session.commit()  # Commit each chunk immediately

                    total_inserted += len(chunk)

                    # Log progress every 20 chunks (10,000 records)
                    if (i // chunk_size + 1) % 20 == 0:
                        logger.debug(f"Processed {total_inserted} records so far...")

                except Exception as chunk_error:
                    logger.warning(
                        f"Error inserting chunk {i // chunk_size + 1}, retrying: {chunk_error}"
                    )
                    db_session.rollback()

                    # Retry once for this chunk
                    try:
                        time.sleep(0.1)  # Brief pause before retry
                        db_session.bulk_insert_mappings(SymToken, chunk)
                        db_session.commit()
                        total_inserted += len(chunk)
                    except Exception as retry_error:
                        logger.error(
                            f"Failed to insert chunk {i // chunk_size + 1} after retry: {retry_error}"
                        )
                        db_session.rollback()
                        # Continue with next chunk instead of failing completely
                        continue

                # Small delay to allow other operations
                time.sleep(0.005)  # 5ms delay between chunks (reduced from 10ms)

            logger.info(f"Bulk insert completed successfully with {total_inserted} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()


def _to_canonical_symbol(delta_symbol: str, instrument_type: str, expiry: str) -> str:
    """
    Convert a Delta Exchange native symbol to the OpenAlgo canonical CRYPTO format.

    Canonical formats (standard Indian F&O-style symbology — no dashes):
        Perpetual future : BTCUSD.P             (delta: BTCUSD  — TradingView .P suffix)
        Dated future     : BTC28FEB25FUT        (delta: BTCUSD28Feb2025 — extract underlying + expiry)
        Call option      : BTC28FEB2580000CE    (delta: C-BTC-80000-280225)
        Put option       : BTC28FEB2580000PE    (delta: P-BTC-80000-280225)

    Args:
        delta_symbol:    Raw symbol string from the Delta Exchange API.
        instrument_type: Mapped type code (CE, PE, FUT, PERPFUT, TCE, TPE, SYNCE, SYNPE, ...).
        expiry:          Already-parsed expiry string in "DD-MON-YY" format (e.g. "28-FEB-25"),
                         or "" for perpetuals.

    Returns:
        OpenAlgo canonical symbol string.
    """
    # ── Options: C-BTC-80000-280225 + expiry "28-FEB-25" → BTC28FEB2580000CE ─
    if instrument_type in ("CE", "TCE", "SYNCE", "PE", "TPE", "SYNPE"):
        parts = delta_symbol.split("-")
        if len(parts) == 4 and expiry:
            # parts: [C/P, underlying, strike, DDMMYY_from_delta]
            underlying  = parts[1].upper()
            strike_part = parts[2]
            suffix = "CE" if instrument_type in ("CE", "TCE", "SYNCE") else "PE"
            # expiry is "DD-MON-YY" (e.g. "28-FEB-25") — strip dashes → "28FEB25"
            expiry_alpha = expiry.replace("-", "")
            return f"{underlying}{expiry_alpha}{strike_part}{suffix}"
        return delta_symbol  # unexpected format — fall back

    # ── Dated futures: extract underlying + alpha expiry ───────────────────
    if instrument_type == "FUT" and expiry:
        # expiry is "DD-MON-YY" (e.g. "28-FEB-25") — strip dashes → "28FEB25"
        expiry_alpha = expiry.replace("-", "")
        upper = delta_symbol.upper()

        # Delta dated futures embed the settlement date in the symbol:
        #   BTCUSD28Feb2025 → upper = BTCUSD28FEB2025
        # The suffix-stripping loop below would never match ("USD", "USDT" etc.)
        # because the symbol ends with the year digits, not the currency code.
        # Fix: reconstruct the date suffix from the already-parsed expiry and strip
        # it first, leaving only the underlying+quote base (e.g. "BTCUSD").
        day, mon, yr2 = expiry.split("-")        # ["28", "FEB", "25"]
        yr4 = "20" + yr2                          # "2025" (Delta API uses 4-digit year)
        date_suffix_in_symbol = day + mon + yr4   # "28FEB2025"

        if upper.endswith(date_suffix_in_symbol):
            base = upper[: -len(date_suffix_in_symbol)]   # "BTCUSD"
        else:
            base = upper   # unexpected format — use full symbol as base

        # Strip common quote-currency suffixes to get the underlying (e.g. BTCUSD → BTC)
        for suffix in ("USDT", "USD", "BTC", "ETH"):
            if base.endswith(suffix) and len(base) > len(suffix):
                return f"{base[:-len(suffix)]}{expiry_alpha}FUT"

        # Cannot reliably extract underlying — use the de-dated base to avoid
        # duplicating the expiry date in the canonical symbol.
        return f"{base}{expiry_alpha}FUT"

    # ── Perpetual futures: BTCUSD → BTCUSD.P (TradingView perpetual notation) ──
    # .P is the TradingView-standard suffix for perpetuals and avoids colliding
    # with BTCUSDT (Binance BTC/Tether spot pair — a completely different asset).
    if instrument_type == "PERPFUT":
        return delta_symbol + "FUT"

    # ── Spot: BTC_INR → BTCINR (strip underscores) ─────────────────────────
    if instrument_type == "SPOT":
        return delta_symbol.replace("_", "")

    # ── All other types (SPREAD, COMBO, IRS, …): keep as-is ────────────────
    return delta_symbol


# Maps Delta Exchange contract_type values to OpenAlgo instrument type codes
CONTRACT_TYPE_MAP = {
    "perpetual_futures": "PERPFUT",
    "futures": "FUT",
    "call_options": "CE",
    "put_options": "PE",
    "spot": "SPOT",
    "move_options": "MOVE",
    "interest_rate_swaps": "IRS",
    "spreads": "SPREAD",
    "options_combos": "COMBO",
    "turbo_call_options": "TCE",
    "turbo_put_options": "TPE",
    "synth_call_options": "SYNCE",
    "synth_put_options": "SYNPE",
}

# Common symbol aliases for fuzzy / familiar lookups.
# Maps user-supplied aliases → canonical Delta Exchange symbol prefix / exact match.
# Keys are stored upper-case; resolution happens case-insensitively.
# Add further pairs here as users report lookup failures.
# Maps user-supplied symbol aliases to the canonical Delta Exchange symbol prefix
# used in the database.  search_symbols() applies a LIKE query after alias resolution,
# so partial matches (e.g. "BTCUSD" → finds "BTCUSD.P") work without explicit entries.
# Only add entries here for genuinely-different ticker names (not convention variants).
SYMBOL_ALIASES: dict[str, str] = {
    "NEARBRC": "NEARUSD",   # alternative ticker heard on TradingView
}


def fetch_delta_products():
    """
    Fetch all live products from the Delta Exchange public GET /v2/products endpoint.
    No authentication required — this is a public endpoint.

    The Delta Exchange v2 API uses cursor-based pagination (NOT page_num).
    After each page we read meta.after; when it is None/null we have the last page.

    Server-side filters applied:
    - states=live          : skip expired/upcoming contracts (much fewer API calls)
    - page_size=500        : maximise records per round-trip (5× fewer calls than 100)

    A MAX_PAGES safety guard prevents an infinite loop if the API ever misbehaves.
    Returns the raw list of product dicts, or [] on failure.
    """
    url = "https://api.india.delta.exchange/v2/products"
    headers = {"Accept": "application/json"}
    all_products = []
    after_cursor = None   # cursor-based pagination — NOT page_num
    page_num = 0          # only used for logging / safety guard
    MAX_PAGES = 100       # 100 × 500 = 50,000 products — a very safe ceiling

    fetch_success = False  # Only set True when pagination completes without error

    while True:
        page_num += 1
        if page_num > MAX_PAGES:
            logger.warning(
                f"Reached max_pages limit ({MAX_PAGES}) fetching Delta products, stopping."
            )
            # Treat hitting the safety ceiling as an incomplete fetch — do not
            # overwrite the DB with potentially truncated data.
            break

        params = {
            "page_size": 500,
            "states": "live",   # server-side filter: only live contracts
        }
        if after_cursor:
            params["after"] = after_cursor

        try:
            response = get_httpx_client().get(
                url,
                params=params,
                headers=headers,
            )
            if response.status_code != 200:
                logger.error(
                    f"Failed to fetch products (page {page_num}): HTTP {response.status_code}"
                )
                break
            data = response.json()
            if not data.get("success", False):
                logger.error(f"Delta Exchange API error: {data.get('error', 'unknown')}")
                break
            batch = data.get("result", [])
            # Guard: single-product endpoint returns result as a dict, not a list.
            if not isinstance(batch, list):
                logger.error(
                    f"Unexpected result type from /v2/products (expected list, got "
                    f"{type(batch).__name__}). Check URL."
                )
                break
            if not batch:
                fetch_success = True  # Empty page = natural end of pagination
                break

            all_products.extend(batch)
            logger.debug(
                f"Fetched page {page_num}: {len(batch)} products "
                f"(total so far: {len(all_products)})"
            )

            # Cursor-based pagination: meta.after is None/null on the last page
            meta = data.get("meta") or {}
            after_cursor = meta.get("after")
            if not after_cursor:
                fetch_success = True  # Explicit last-page signal from the API
                break

        except Exception as e:
            logger.error(f"Exception fetching Delta products (page {page_num}): {e}")
            break

    if not fetch_success:
        logger.warning(
            f"fetch_delta_products completed with errors after page {page_num}. "
            f"Returning partial data ({len(all_products)} products) but marking as failed "
            f"to prevent overwriting the existing master contract DB."
        )

    logger.info(f"Fetched {len(all_products)} products from Delta Exchange in {page_num} page(s)")
    return all_products, fetch_success


def process_delta_products(products):
    """
    Convert a list of Delta Exchange product dicts to a DataFrame matching the
    OpenAlgo SymToken schema.  Only live + operational products are included.

    Field mapping (from GET /v2/products response):
        token          ← id                    (int → str)
        brsymbol       ← symbol                (Delta-native, e.g. "C-BTC-80000-280225")
        symbol         ← canonical             (OpenAlgo format, e.g. "BTC28FEB2580000CE")
        name           ← description
        exchange       ← "CRYPTO"              (OpenAlgo exchange abstraction)
        brexchange     ← "DELTAIN"             (broker identifier — Delta Exchange India)
        expiry         ← settlement_time       (None → "" for perpetuals;
                                                ISO string → "DD-MON-YY" for futures/options)
        strike         ← 0.0                   (strike is encoded in the symbol for options)
        lotsize        ← product_specs.min_order_size or 1  (fractional for spot, e.g. 0.0001 BTC)
        instrumenttype ← contract_type         (mapped via CONTRACT_TYPE_MAP)
        tick_size      ← tick_size             (string → float)
    """
    from datetime import datetime, timezone

    if not products:
        logger.error("No products to process")
        return pd.DataFrame()

    rows = []
    for p in products:
        # Only store live, operationally trading contracts
        if p.get("state") != "live":
            continue
        if p.get("trading_status") != "operational":
            continue

        # Skip products that only accept reduce-only orders.
        # These are contracts where the exchange has restricted new position opening
        # (e.g. pre-expiry wind-down or liquidation-only mode).  Storing them in the
        # master contract DB would allow order placement that the API would reject.
        product_specs = p.get("product_specs") or {}
        if product_specs.get("only_reduce_only_orders_allowed", False):
            logger.debug(
                f"Skipping {p.get('symbol')} — only_reduce_only_orders_allowed is true"
            )
            continue

        contract_type = p.get("contract_type", "")
        instrument_type = CONTRACT_TYPE_MAP.get(
            contract_type, contract_type.upper() if contract_type else "OTHER"
        )

        # Expiry: settlement_time is an ISO-8601 string or null for perpetuals
        settlement_time = p.get("settlement_time")
        if settlement_time:
            try:
                dt = datetime.fromisoformat(settlement_time.replace("Z", "+00:00"))
                expiry = dt.strftime("%d-%b-%y").upper()
            except Exception:
                expiry = str(settlement_time)
        else:
            expiry = ""  # Perpetual futures have no expiry

        # tick_size comes as a string (e.g. "0.5")
        try:
            tick_size = float(p.get("tick_size") or 0)
        except (ValueError, TypeError):
            tick_size = 0.0

        # Extract strike price — use the API field directly when available,
        # fall back to parsing from the symbol (e.g. C-BTC-80000-280225 -> 80000.0)
        symbol_str = p.get("symbol", "")
        strike_val = 0.0
        if instrument_type in ("CE", "PE", "TCE", "TPE", "SYNCE", "SYNPE"):
            try:
                strike_val = float(p.get("strike_price") or 0)
            except (ValueError, TypeError):
                strike_val = 0.0
            # Fallback: parse from symbol if API field missing
            if strike_val == 0.0:
                parts_s = symbol_str.split("-")
                if len(parts_s) >= 3:
                    try:
                        strike_val = float(parts_s[2])
                    except (ValueError, TypeError):
                        strike_val = 0.0

        # Lot size: use min_order_size from product_specs (important for spot
        # instruments where fractional quantities are allowed, e.g. 0.0001 BTC)
        try:
            lotsize = float(product_specs.get("min_order_size") or 1)
        except (ValueError, TypeError):
            lotsize = 1.0

        # Build OpenAlgo canonical symbol (exchange = CRYPTO, broker-agnostic format)
        canonical_symbol = _to_canonical_symbol(symbol_str, instrument_type, expiry)

        rows.append(
            {
                "token": str(p["id"]),
                "symbol": canonical_symbol,   # OpenAlgo canonical (e.g. BTC28FEB2580000CE)
                "brsymbol": symbol_str,        # Delta-native (e.g. C-BTC-80000-280225)
                "name": p.get("description", symbol_str),
                "exchange": "CRYPTO",          # OpenAlgo exchange abstraction
                "brexchange": "DELTAIN",       # Broker identifier (Delta Exchange India)
                "expiry": expiry,
                "strike": strike_val,
                "lotsize": lotsize,
                "instrumenttype": instrument_type,
                "tick_size": tick_size,
                "contract_value": float(p.get("contract_value") or 1.0),
            }
        )

    if not rows:
        logger.error("No live/operational products found in Delta Exchange response")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["token"], keep="first")
    logger.info(f"Processed {len(df)} live Delta Exchange instruments")
    return df


def master_contract_download():
    """
    Download and store Delta Exchange master contract data.
    Uses the public GET /v2/products endpoint — no authentication required.
    """
    logger.info("Downloading Master Contract from Delta Exchange")

    try:
        products, fetch_success = fetch_delta_products()

        if not products:
            return socketio.emit(
                "master_contract_download",
                {"status": "error", "message": "No products returned from Delta Exchange"},
            )

        if not fetch_success:
            # Pagination was interrupted mid-way (HTTP error, API error, exception,
            # or MAX_PAGES hit).  Returning partial data as success would silently
            # truncate the master contract DB — keep the existing table intact.
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "error",
                    "message": (
                        f"Master contract download incomplete — only {len(products)} products "
                        f"fetched before an error occurred. Existing master contract preserved."
                    ),
                },
            )

        token_df = process_delta_products(products)

        if token_df.empty:
            return socketio.emit(
                "master_contract_download",
                {"status": "error", "message": "No live instruments found on Delta Exchange"},
            )

        delete_symtoken_table()
        copy_from_dataframe(token_df)
        return socketio.emit(
            "master_contract_download",
            {
                "status": "success",
                "message": f"Successfully Downloaded {len(token_df)} Delta Exchange Instruments",
            },
        )

    except Exception as e:
        logger.exception(f"Error during Delta Exchange master contract download: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    """
    Search for symbols in the database.

    Supports SYMBOL_ALIASES: if the queried symbol matches a known alias
    (e.g. BTCUSDT) the lookup is transparently retried with the canonical
    Delta Exchange symbol (e.g. BTCUSD) so users don’t need to know
    exchange-specific naming conventions.
    """
    canonical = SYMBOL_ALIASES.get(symbol.upper())
    if canonical:
        logger.debug(
            f"[DeltaExchange] search_symbols: alias '{symbol}' → '{canonical}'"
        )
        symbol = canonical
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
