"""
Mudrex master contract download and symbol table management.

Fetches all tradeable perpetual futures from ``GET /fapi/v1/futures``
(paginated via offset/limit) and stores them in the shared ``symtoken``
table keyed by ``exchange = 'CRYPTO_FUT'`` and ``brexchange = 'MUDREX'``.

Symbol mapping convention:
    token      = Mudrex ``id`` (UUID string, e.g. "01903a7b-bf65-707d-...")
    brsymbol   = Mudrex/Bybit symbol (e.g. "BTCUSDT")
    symbol     = OpenAlgo canonical (same as brsymbol for Mudrex perps)
"""

import os
import time

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.mudrex.api.mudrex_http import mudrex_request
from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=50,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={"timeout": 30, "check_same_thread": False},
)

try:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("PRAGMA temp_store=memory"))
        conn.execute(text("PRAGMA mmap_size=268435456"))
        conn.commit()
except Exception as e:
    logger.warning(f"Could not set SQLite pragmas for master_contract_db: {e}")

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)
    contract_value = Column(Float, default=1.0)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)
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
        logger.error(f"contract_value migration FAILED: {e}")


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df: pd.DataFrame) -> tuple[int, bool]:
    """Bulk-insert symtoken rows. Returns ``(rows_inserted, all_expected_rows_inserted)``.

    If any chunk fails after retry, returns ``complete=False`` so callers do not
    report success with a partially empty table.
    """
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient="records")

    try:
        from sqlalchemy import inspect as sa_inspect
        _db_cols = {c["name"] for c in sa_inspect(engine).get_columns("symtoken")}
    except Exception:
        _db_cols = None

    if _db_cols is not None:
        extra_cols = {k for k in (data_dict[0] if data_dict else {}) if k not in _db_cols}
        if extra_cols:
            logger.warning(f"Stripping unknown columns from insert: {extra_cols}")
            data_dict = [{k: v for k, v in row.items() if k not in extra_cols} for row in data_dict]

    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data_dict = [row for row in data_dict if row["token"] not in existing_tokens]

    chunk_size = 500
    total_inserted = 0
    chunk_failures = 0
    expected = len(filtered_data_dict)

    try:
        if filtered_data_dict:
            logger.info(f"Starting bulk insert of {len(filtered_data_dict)} records")
            for i in range(0, len(filtered_data_dict), chunk_size):
                chunk = filtered_data_dict[i : i + chunk_size]
                try:
                    db_session.bulk_insert_mappings(SymToken, chunk)
                    db_session.commit()
                    total_inserted += len(chunk)
                except Exception as chunk_error:
                    logger.warning(f"Error inserting chunk, retrying: {chunk_error}")
                    db_session.rollback()
                    try:
                        time.sleep(0.1)
                        db_session.bulk_insert_mappings(SymToken, chunk)
                        db_session.commit()
                        total_inserted += len(chunk)
                    except Exception as retry_error:
                        logger.error(f"Failed to insert chunk after retry: {retry_error}")
                        db_session.rollback()
                        chunk_failures += 1
                        continue
                time.sleep(0.005)
            logger.info(f"Bulk insert completed with {total_inserted} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()
        return total_inserted, False

    complete = chunk_failures == 0 and total_inserted == expected
    if not complete and expected > 0:
        logger.error(
            f"[Mudrex] Incomplete symtoken insert: inserted={total_inserted}, "
            f"expected={expected}, chunk_failures={chunk_failures}"
        )
    return total_inserted, complete


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def fetch_mudrex_futures(auth: str | None = None) -> tuple[list[dict], bool]:
    """Fetch all tradeable futures from Mudrex ``GET /futures`` with offset pagination.

    Returns:
        ``(products_list, fetch_success)``
    """
    all_assets: list[dict] = []
    offset = 0
    page_size = 100
    max_pages = 50
    fetch_success = False

    for page in range(1, max_pages + 1):
        data = mudrex_request(
            "/futures",
            method="GET",
            params={"offset": str(offset), "limit": str(page_size), "sort": "popularity", "order": "asc"},
            auth=auth,
        )

        if data.get("success") is not True:
            logger.error(f"[Mudrex] Failed to fetch futures page {page}: {data}")
            break

        batch = data.get("data", [])
        if not isinstance(batch, list):
            logger.error(f"[Mudrex] Unexpected data type from /futures: {type(batch)}")
            break

        if not batch:
            fetch_success = True
            break

        all_assets.extend(batch)
        logger.debug(f"[Mudrex] Fetched page {page}: {len(batch)} assets (total: {len(all_assets)})")

        if len(batch) < page_size:
            fetch_success = True
            break

        offset += page_size

    logger.info(f"[Mudrex] Fetched {len(all_assets)} futures in {page} page(s)")
    return all_assets, fetch_success


def process_mudrex_futures(assets: list[dict]) -> pd.DataFrame:
    """Convert Mudrex asset dicts to a DataFrame matching the SymToken schema."""
    if not assets:
        logger.error("No assets to process")
        return pd.DataFrame()

    rows = []
    for a in assets:
        asset_id = a.get("id", "")
        symbol = a.get("symbol", "")
        name = a.get("name", symbol)

        if not asset_id or not symbol:
            continue

        rows.append({
            "token": str(asset_id),
            "symbol": symbol,
            "brsymbol": symbol,
            "name": name,
            "exchange": "CRYPTO_FUT",
            "brexchange": "MUDREX",
            "expiry": "",
            "strike": 0.0,
            "lotsize": _safe_float(a.get("min_contract"), 1.0),
            "instrumenttype": "PERPFUT",
            "tick_size": _safe_float(a.get("price_step")),
            "contract_value": 1.0,
        })

    if not rows:
        logger.error("No tradeable instruments found in Mudrex response")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["token"], keep="first")
    logger.info(f"[Mudrex] Processed {len(df)} instruments")
    return df


def master_contract_download():
    """Download and store Mudrex master contract data."""
    logger.info("Downloading Master Contract from Mudrex")

    try:
        auth = os.getenv("BROKER_API_SECRET", "")
        assets, fetch_success = fetch_mudrex_futures(auth=auth or None)

        if not assets:
            return socketio.emit(
                "master_contract_download",
                {"status": "error", "message": "No assets returned from Mudrex"},
            )

        if not fetch_success:
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "error",
                    "message": (
                        f"Incomplete download — only {len(assets)} assets fetched. "
                        f"Existing master contract preserved."
                    ),
                },
            )

        token_df = process_mudrex_futures(assets)

        if token_df.empty:
            return socketio.emit(
                "master_contract_download",
                {"status": "error", "message": "No tradeable instruments found on Mudrex"},
            )

        delete_symtoken_table()
        inserted, complete = copy_from_dataframe(token_df)
        if not complete or inserted < len(token_df):
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "error",
                    "message": (
                        f"Master contract insert incomplete ({inserted}/{len(token_df)} rows). "
                        "Try downloading again; symtoken may be partial."
                    ),
                },
            )

        return socketio.emit(
            "master_contract_download",
            {
                "status": "success",
                "message": f"Successfully Downloaded {len(token_df)} Mudrex Instruments",
            },
        )

    except Exception as e:
        logger.exception(f"Error during Mudrex master contract download: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol: str, exchange: str):
    """Search for symbols in the database."""
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
