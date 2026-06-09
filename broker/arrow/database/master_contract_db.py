# broker/arrow/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from Arrow's instrument master.
#
# Sources (both require auth):
#   1. GET https://edge.arrow.trade/all          -> full instrument CSV
#   2. GET https://edge.arrow.trade/info/index-list -> [{name, token}] indices
#
# Arrow collapses every index (NSE + BSE) into a single "INDEX" pseudo-exchange.
# OpenAlgo needs them split into NSE_INDEX / BSE_INDEX, so we classify index
# rows here (see mapping/exchange.py). The resulting `token` is what quotes,
# history and the websocket all key off, so getting indices into SymToken with
# correct tokens is the foundation for index support across the broker.
#
# NOTE: every field that depends on the exact (and inconsistently documented)
# CSV layout is read defensively via _pick() and flagged with TODO(arrow) so
# live data can confirm the column names/scaling once credentials arrive.

import io
import os

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.arrow.api.baseurl import INSTRUMENTS_URL, ROOT_URL, get_arrow_headers
from broker.arrow.mapping.exchange import arrow_exchange_to_oa, classify_index_symbol
from database.auth_db import get_auth_token
from database.engine_factory import create_db_engine
from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)
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
    # Present in the canonical schema (database/symbol.py); always NULL in
    # practice but declared so a fresh-install create_all() matches the
    # shared symtoken table other modules query.
    contract_value = Column(Float)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient="records")

    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered = [row for row in data_dict if row["token"] not in existing_tokens]

    try:
        if filtered:
            db_session.bulk_insert_mappings(SymToken, filtered)
            db_session.commit()
            logger.info(f"Bulk insert completed with {len(filtered)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


# --- download helpers ---------------------------------------------------

def _broker_auth_token():
    """Resolve the stored Arrow JWT for the configured user (same approach as
    the Zerodha master-contract download)."""
    login_username = os.getenv("LOGIN_USERNAME")
    return get_auth_token(login_username)


def download_arrow_instruments(auth_token):
    """Download the full Arrow instrument CSV into a DataFrame."""
    client = get_httpx_client()
    headers = get_arrow_headers(auth_token)
    # Generous explicit timeout: the full instrument CSV can be several MB.
    response = client.get(INSTRUMENTS_URL, headers=headers, timeout=120)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    # Normalize headers (the docs show inconsistent spacing/casing).
    df.columns = [str(c).strip() for c in df.columns]
    return df


def fetch_index_list(auth_token):
    """Fetch [{name, token}] indices from /info/index-list. Returns [] on error
    so a missing index feed never breaks the whole master-contract download."""
    try:
        client = get_httpx_client()
        headers = get_arrow_headers(auth_token)
        response = client.get(f"{ROOT_URL}/info/index-list", headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        return data or []
    except Exception as e:
        logger.error(f"Error fetching Arrow index list: {e}")
        return []


# --- parsing ------------------------------------------------------------

# Map possible Arrow column names (docs list two variants) to a canonical name.
_COLUMN_ALIASES = {
    "exchange": ["Exchange"],
    "segment": ["Segment"],
    "exchseg": ["ExchSeg"],
    "token": ["Token"],
    "fullname": ["FullName", "CompanyName"],
    "basesymbol": ["Symbol"],
    "tradingsymbol": ["TradingSymbol"],
    "series": ["Series"],
    "optiontype": ["OptionType"],
    "underlying": ["Underlying"],
    "strike": ["StrikePrice"],
    "expiry": ["Expiry", "ExpiryDate"],
    "lotsize": ["LotSize"],
    "ticksize": ["TickSize"],
}


def _pick(row, key, default=""):
    """Read a value from a row by canonical key, trying each documented alias."""
    for col in _COLUMN_ALIASES.get(key, [key]):
        if col in row and pd.notna(row[col]):
            return row[col]
    return default


def _format_expiry(value):
    """Format an Arrow expiry into OpenAlgo's DD-MMM-YY (e.g. 24APR24)."""
    if value in (None, "", "0") or pd.isna(value):
        return ""
    try:
        return pd.to_datetime(value).strftime("%d-%b-%y").upper()
    except Exception:
        return str(value)


def _format_strike(strike):
    """Strike is sent x100 by Arrow; preserve decimal strikes (187.5)."""
    try:
        val = float(strike) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return val


def _build_row(row):
    """Map one Arrow CSV row to a SymToken dict (OpenAlgo schema)."""
    exchseg = _pick(row, "exchseg")
    segment = _pick(row, "segment")
    exchange_raw = _pick(row, "exchange")
    option_type = str(_pick(row, "optiontype")).upper()

    oa_exchange = arrow_exchange_to_oa(exchseg, segment, exchange_raw)

    base = str(_pick(row, "underlying") or _pick(row, "basesymbol") or "").strip()
    tradingsymbol = str(_pick(row, "tradingsymbol") or _pick(row, "basesymbol") or "").strip()
    name = str(_pick(row, "fullname") or base).strip()
    expiry = _format_expiry(_pick(row, "expiry"))
    strike = _format_strike(_pick(row, "strike", 0))

    # Instrument type + OpenAlgo symbol construction.
    # NOTE: OpenAlgo stores indices with instrumenttype "EQ" (verified against
    # the live symtoken table); the NSE_INDEX/BSE_INDEX exchange is what
    # distinguishes them. There is NO "INDEX" instrumenttype.
    if oa_exchange in ("NSE_INDEX", "BSE_INDEX"):
        instrumenttype = "EQ"
        oa_symbol, oa_exchange2 = classify_index_symbol(name or tradingsymbol)
        oa_exchange = oa_exchange2 or oa_exchange
        symbol = oa_symbol
    elif option_type in ("CE", "PE"):
        instrumenttype = option_type
        strike_str = str(int(strike)) if float(strike) == int(strike) else str(strike)
        symbol = f"{base}{expiry.replace('-', '')}{strike_str}{option_type}"
    elif expiry and oa_exchange in ("NFO", "BFO", "MCX", "CDS", "BCD"):
        # Derivative with an expiry and no CE/PE -> a future.
        # TODO(arrow): confirm futures are identified by expiry + empty OptionType
        # (vs a Series/Segment flag like FUTSTK/FUTIDX).
        instrumenttype = "FUT"
        symbol = f"{base}{expiry.replace('-', '')}FUT"
    else:
        instrumenttype = "EQ"
        # Equity OpenAlgo symbol is the bare base (Arrow `Symbol`), e.g.
        # TradingSymbol "RELIANCE-EQ" -> base "RELIANCE".
        symbol = str(_pick(row, "basesymbol") or tradingsymbol.split("-")[0]).strip()

    # Match the live symtoken convention: for derivatives the `name` column is
    # the underlying (e.g. "NIFTY"); for equity/index it is the full/company name.
    if instrumenttype in ("FUT", "CE", "PE"):
        name = base or name

    try:
        lotsize = int(float(_pick(row, "lotsize", 0) or 0))
    except (TypeError, ValueError):
        lotsize = 0
    try:
        # TODO(arrow): confirm whether TickSize is scaled x100 like prices.
        tick_size = float(_pick(row, "ticksize", 0) or 0)
    except (TypeError, ValueError):
        tick_size = 0.0

    return {
        "symbol": symbol,
        "brsymbol": tradingsymbol,
        "name": name,
        "exchange": oa_exchange,
        "brexchange": str(exchseg or exchange_raw),
        "token": str(_pick(row, "token")),
        "expiry": expiry,
        "strike": strike,
        "lotsize": lotsize,
        "instrumenttype": instrumenttype,
        "tick_size": tick_size,
    }


def process_arrow_csv(df):
    """Transform the Arrow instrument DataFrame into SymToken rows."""
    logger.info("Processing Arrow instrument master")
    records = [_build_row(row) for _, row in df.iterrows()]
    out = pd.DataFrame.from_records(records)
    # Drop rows that failed to map to a valid OpenAlgo exchange.
    out = out[out["exchange"].notna() & (out["exchange"] != "")]
    return out


def build_index_rows(index_list, existing_tokens):
    """Build SymToken rows for indices from /info/index-list, skipping any
    token already present from the CSV. Splits into NSE_INDEX / BSE_INDEX."""
    rows = []
    for item in index_list or []:
        token = str(item.get("token", "")).strip()
        name = item.get("name", "")
        if not token or token in existing_tokens:
            continue
        oa_symbol, oa_exchange = classify_index_symbol(name)
        rows.append(
            {
                "symbol": oa_symbol,
                # TODO(arrow): confirm the symbol string the /info/quote endpoint
                # expects for an index (display name vs a trading symbol). The
                # websocket + history use the token, so those work regardless.
                "brsymbol": str(name),
                "name": str(name),
                "exchange": oa_exchange,
                "brexchange": "INDEX",
                "token": token,
                "expiry": "",
                "strike": 0.0,
                "lotsize": 0,
                # OpenAlgo stores indices as instrumenttype "EQ" (the
                # NSE_INDEX/BSE_INDEX exchange distinguishes them).
                "instrumenttype": "EQ",
                "tick_size": 0.0,
            }
        )
    return rows


def master_contract_download():
    """Entry point (called post-login). Downloads + rebuilds the SymToken table."""
    logger.info("Downloading Arrow Master Contract")
    try:
        auth_token = _broker_auth_token()

        df = download_arrow_instruments(auth_token)
        token_df = process_arrow_csv(df)

        # Merge in indices from /info/index-list that the CSV didn't already
        # carry (deduped by token).
        existing_tokens = set(token_df["token"].astype(str))
        index_rows = build_index_rows(fetch_index_list(auth_token), existing_tokens)
        if index_rows:
            token_df = pd.concat([token_df, pd.DataFrame.from_records(index_rows)], ignore_index=True)
            logger.info(f"Added {len(index_rows)} index instruments from /info/index-list")

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception(f"Arrow master contract download failed: {e}")
        return socketio.emit(
            "master_contract_download", {"status": "error", "message": str(e)}
        )
    finally:
        # This runs in a background thread (not a Flask request), so the app
        # teardown won't clean up the scoped session -- release it explicitly.
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
