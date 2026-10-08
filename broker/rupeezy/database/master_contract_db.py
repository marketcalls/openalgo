# broker/rupeezy/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from the Rupeezy Vortex instrument master
# (https://static.rupeezy.in/master.csv, public, ~160k rows).
#
# Layout verified against the live file:
#   token,exchange,symbol,instrument_name,series,expiry_date,option_type,
#   strike_price,tick,lot_size,eligibility,security_desc,asm_gsm_stage,
#   last_trading_date,isin_code,ticker,has_cas_session
#
#   exchange        NSE_EQ / BSE_EQ / NSE_FO / BSE_FO / MCX_FO
#   instrument_name EQUITIES, EQIDX (indices), FUTIDX/FUTSTK/FUTCOM,
#                   OPTIDX/OPTSTK/OPTFUT
#   expiry_date     YYYYMMDD, empty for cash/indices
#   option_type     CE / PE for options, XX for futures
#   strike_price    rupees, unscaled; futures carry -0.01 / 0 placeholders
#   tick            paise (5 -> Rs 0.05, MCX CRUDEOIL 100 -> Rs 1)
#   lot_size        real market lot, including MCX (CRUDEOIL 100)
#   ticker          "<NSE|BSE|MCX>:<symbol>", what every Vortex call takes
#
# brsymbol is the ticker without its prefix; brexchange is the Vortex exchange.

import io
import os

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.rupeezy.api.baseurl import MASTER_URL
from broker.rupeezy.mapping.exchange import (
    VORTEX_INDEX_EXCHANGE,
    VORTEX_TO_OA_EXCHANGE,
    to_oa_index_symbol,
)
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
    # Present in the canonical schema (database/symbol.py); always NULL here.
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
    records = df.to_dict(orient="records")
    try:
        if records:
            db_session.bulk_insert_mappings(SymToken, records)
            db_session.commit()
            logger.info(f"Bulk insert completed with {len(records)} records.")
        else:
            logger.info("No records to insert.")
    except Exception:
        logger.exception("Error during bulk insert")
        db_session.rollback()


def download_master():
    """Download master.csv into a string-typed DataFrame."""
    client = get_httpx_client()
    # Generous explicit timeout: the file is ~15 MB.
    response = client.get(MASTER_URL, timeout=120)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def process_master(df):
    """Vortex master DataFrame -> SymToken rows (vectorized)."""
    logger.info("Processing Rupeezy instrument master")

    brexchange = df["exchange"].fillna("").str.strip().str.upper()
    instrument = df["instrument_name"].fillna("").str.strip().str.upper()
    base = df["symbol"].fillna("").str.strip()
    ticker = df["ticker"].fillna("").str.strip()
    brsymbol = ticker.str.split(":", n=1).str[-1]
    option_type = df["option_type"].fillna("").str.strip().str.upper()
    desc = df["security_desc"].fillna("").str.strip()

    is_index = instrument == "EQIDX"
    exchange = brexchange.map(VORTEX_TO_OA_EXCHANGE)
    exchange = exchange.mask(is_index, brexchange.map(VORTEX_INDEX_EXCHANGE))

    is_deriv = brexchange.str.endswith("_FO")
    is_option = is_deriv & option_type.isin(["CE", "PE"])
    is_future = is_deriv & ~is_option

    expiry_dt = pd.to_datetime(df["expiry_date"], format="%Y%m%d", errors="coerce")
    expiry = expiry_dt.dt.strftime("%d-%b-%y").str.upper().fillna("")
    expiry_compact = expiry.str.replace("-", "", regex=False)

    strike = pd.to_numeric(df["strike_price"], errors="coerce").fillna(0.0)
    strike = strike.where(is_option, 0.0).clip(lower=0.0) + 0.0
    whole = strike == strike.round(0)
    strike_str = pd.Series(
        np.where(
            whole, strike.round(0).astype(np.int64).astype(str), strike.map(lambda s: f"{s:g}")
        ),
        index=df.index,
    )

    tick_size = (pd.to_numeric(df["tick"], errors="coerce").fillna(0.0) / 100.0).round(6)
    lotsize = pd.to_numeric(df["lot_size"], errors="coerce").fillna(0).astype(int)

    instrumenttype = pd.Series("EQ", index=df.index)
    instrumenttype = instrumenttype.mask(is_future, "FUT").mask(is_option, option_type)

    symbol = brsymbol.copy()
    symbol = symbol.mask(is_future, base + expiry_compact + "FUT")
    symbol = symbol.mask(is_option, base + expiry_compact + strike_str + option_type)

    name = desc.where(desc != "", base)
    name = name.mask(is_deriv, base)

    out = pd.DataFrame(
        {
            "symbol": symbol,
            "brsymbol": brsymbol,
            "name": name,
            "exchange": exchange,
            "brexchange": brexchange,
            "token": df["token"].fillna("").str.strip(),
            "expiry": expiry,
            "strike": strike,
            "lotsize": lotsize,
            "instrumenttype": instrumenttype,
            "tick_size": tick_size,
        }
    )

    # Indices: canonical OpenAlgo names (NIFTY, BANKNIFTY, SENSEX, NIFTYIT ...).
    # ~125 rows, so a Python loop is fine.
    if is_index.any():
        out.loc[is_index, "symbol"] = [
            to_oa_index_symbol(sym, oa_exchange)
            for sym, oa_exchange in zip(base[is_index], out.loc[is_index, "exchange"], strict=True)
        ]

    out = out[out["exchange"].notna() & (out["exchange"] != "") & (out["brsymbol"] != "")]
    out = out.drop_duplicates(subset=["symbol", "exchange"], keep="first")
    return out


def master_contract_download():
    """Entry point (called post-login). Downloads and rebuilds the SymToken table."""
    logger.info("Downloading Rupeezy Master Contract")
    try:
        token_df = process_master(download_master())
        delete_symtoken_table()
        copy_from_dataframe(token_df)
        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception("Rupeezy master contract download failed")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        # Runs in a background thread, so the Flask teardown never releases it.
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
