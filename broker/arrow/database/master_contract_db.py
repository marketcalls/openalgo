# broker/arrow/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from Arrow's instrument master.
#
# Sources (both require auth):
#   1. GET https://edge.arrow.trade/all          -> full instrument CSV
#   2. GET https://edge.arrow.trade/info/index-list -> [{name, token}] indices
#
# The CSV layout and field scaling are verified against the live feed
# (221k+ rows): ExchSeg drives the exchange mapping, OptionType "XX" marks
# futures, currency-derivative strikes arrive x100000 and ticks in paise.
# Index rows (NSEIDX/BSEIDX/MCXIDX) carry display names in `Symbol` and are
# standardized to the documented OpenAlgo index symbols in mapping/exchange.py.
# The resulting `token` is what quotes, history and the websocket all key off.

import io
import os

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.arrow.api.baseurl import INSTRUMENTS_URL, ROOT_URL, get_arrow_headers
from broker.arrow.mapping.exchange import (
    ARROW_EXCHSEG_TO_OA,
    OA_INDEX_EXCHANGES,
    classify_index_symbol,
)
from database.auth_db import Auth, get_auth_token
from database.auth_db import db_session as auth_db_session
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
    """Resolve the stored Arrow JWT.

    Tries LOGIN_USERNAME first (legacy convention shared with Zerodha), then
    falls back to the single non-revoked arrow row in the Auth table --
    OpenAlgo is single-user, so there is at most one.
    """
    login_username = os.getenv("LOGIN_USERNAME")
    if login_username:
        token = get_auth_token(login_username)
        if token:
            return token

    auth_obj = Auth.query.filter_by(broker="arrow", is_revoked=False).first()
    if auth_obj:
        return get_auth_token(auth_obj.name)
    return None


def download_arrow_instruments(auth_token):
    """Download the full Arrow instrument CSV into a DataFrame."""
    if not auth_token:
        raise ValueError(
            "No Arrow auth token available - login to the broker before "
            "downloading the master contract."
        )
    client = get_httpx_client()
    headers = get_arrow_headers(auth_token)
    # Generous explicit timeout: the full instrument CSV can be several MB.
    response = client.get(INSTRUMENTS_URL, headers=headers, timeout=120)
    response.raise_for_status()
    # dtype=str: skip pandas type inference entirely (the CSV has mixed-type
    # columns like Series/ISIN that would otherwise warn). The vectorized
    # processing converts numeric columns explicitly.
    df = pd.read_csv(io.StringIO(response.text), dtype=str)
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
        data = payload.get("data") if isinstance(payload, dict) else payload
        # Guard the shape: an error/non-standard payload must yield [] here,
        # not leak a dict into build_index_rows and break the whole download.
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Error fetching Arrow index list: {e}")
        return []


# --- parsing ------------------------------------------------------------

# Currency-derivative segments quote with 4-decimal precision; their
# StrikePrice comes scaled x100000 (USDINR 65.50 -> 6550000) and TickSize in
# paise (0.25 -> Rs 0.0025). Every other segment sends both unscaled
# (verified against the live CSV: NFO strike 207.5 == real 207.5, futures
# carry -0.01/0 placeholders).
_CD_SEGMENTS = ["NSECD", "BSECD"]

# OpenAlgo exchanges whose instruments can be futures (used by the
# expiry-based FUT fallback when OptionType is missing).
_DERIVATIVE_EXCHANGES = ["NFO", "BFO", "MCX", "CDS", "BCD", "NCO"]


def process_arrow_csv(df):
    """Transform the Arrow instrument DataFrame into SymToken rows.

    Fully vectorized (mirrors the Zerodha implementation): pandas column
    operations over the whole frame instead of a per-row Python loop, which
    keeps the 220k-row master under a couple of seconds.
    """
    logger.info("Processing Arrow instrument master")

    exchseg = df["ExchSeg"].fillna("").str.strip().str.upper()
    exchange = exchseg.map(ARROW_EXCHSEG_TO_OA)

    base = df["Underlying"].fillna(df["Symbol"]).fillna("").str.strip()
    tradingsymbol = df["TradingSymbol"].fillna(df["Symbol"]).fillna("").str.strip()
    fullname = df["FullName"].fillna("").str.strip()
    option_type = df["OptionType"].fillna("").str.strip().str.upper()

    # Expiry "30-Jun-2026" -> "30-JUN-26" (DD-MMM-YY, the platform convention).
    expiry_dt = pd.to_datetime(df["Expiry"], format="%d-%b-%Y", errors="coerce")
    expiry = expiry_dt.dt.strftime("%d-%b-%y").str.upper().fillna("")
    expiry_compact = expiry.str.replace("-", "", regex=False)

    cd_mask = exchseg.isin(_CD_SEGMENTS)
    strike = pd.to_numeric(df["StrikePrice"], errors="coerce").fillna(0.0)
    strike = strike.where(~cd_mask, (strike / 100000.0).round(6))
    # Futures/equity placeholder strikes (-0.01 or 0) -> 0; the `+ 0.0`
    # normalizes the negative zero clip() leaves behind.
    strike = strike.clip(lower=0.0) + 0.0
    tick_size = pd.to_numeric(df["TickSize"], errors="coerce").fillna(0.0)
    tick_size = tick_size.where(~cd_mask, (tick_size / 100.0).round(6))
    lotsize = pd.to_numeric(df["LotSize"], errors="coerce").fillna(0).astype(int)

    is_option = option_type.isin(["CE", "PE"])
    # Futures: OptionType "XX" in the live CSV (TradingSymbol ends in "F",
    # e.g. BANKNIFTY28JUL26F). The expiry check is a fallback.
    is_future = ~is_option & (
        (option_type == "XX") | ((expiry != "") & exchange.isin(_DERIVATIVE_EXCHANGES))
    )
    is_deriv = is_option | is_future

    # NOTE: OpenAlgo stores indices with instrumenttype "EQ" (verified against
    # the live symtoken table); the *_INDEX exchange is what distinguishes
    # them. There is NO "INDEX" instrumenttype.
    instrumenttype = pd.Series("EQ", index=df.index)
    instrumenttype = instrumenttype.mask(is_future, "FUT").mask(is_option, option_type)

    # Strike rendered the way symbols embed it: int when whole, else decimal
    # (207.5 -> "207.5", 1.025 -> "1.025").
    whole = strike == strike.astype(int)
    strike_str = pd.Series(
        np.where(whole, strike.astype(int).astype(str), strike.astype(str)), index=df.index
    )

    # Equity symbols: strip the "-EQ" series suffix only ("RELIANCE-EQ" ->
    # "RELIANCE"); other series keep their suffix ("749AP39-SG"), matching
    # the Zerodha-built table convention.
    symbol = tradingsymbol.str.replace(r"-EQ$", "", regex=True)
    symbol = symbol.mask(is_future, base + expiry_compact + "FUT")
    symbol = symbol.mask(is_option, base + expiry_compact + strike_str + option_type)

    # `name` is the underlying for derivatives, the full/company name (or the
    # display name for indices) otherwise.
    name = fullname.where(fullname != "", base)
    name = name.mask(is_deriv & (base != ""), base)

    out = pd.DataFrame(
        {
            "symbol": symbol,
            "brsymbol": tradingsymbol,
            "name": name,
            "exchange": exchange,
            "brexchange": exchseg,
            "token": df["Token"].fillna("").str.strip(),
            "expiry": expiry,
            "strike": strike,
            "lotsize": lotsize,
            "instrumenttype": instrumenttype,
            "tick_size": tick_size,
        }
    )

    # Index rows carry a display name in `Symbol` ("Nifty 50", "BSE IT",
    # "CrudeOil"); standardize to the documented OpenAlgo index symbols.
    # Only ~200 rows, so a Python loop is fine here.
    idx_mask = out["exchange"].isin(OA_INDEX_EXCHANGES)
    if idx_mask.any():
        out.loc[idx_mask, "symbol"] = [
            classify_index_symbol(display, oa_exchange)[0]
            for display, oa_exchange in zip(
                out.loc[idx_mask, "brsymbol"], out.loc[idx_mask, "exchange"], strict=True
            )
        ]

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
            token_df = pd.concat(
                [token_df, pd.DataFrame.from_records(index_rows)], ignore_index=True
            )
            logger.info(f"Added {len(index_rows)} index instruments from /info/index-list")

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception(f"Arrow master contract download failed: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        # This runs in a background thread (not a Flask request), so the app
        # teardown won't clean up the scoped sessions -- release both the
        # local one and the auth_db one (used by _broker_auth_token).
        db_session.remove()
        auth_db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
