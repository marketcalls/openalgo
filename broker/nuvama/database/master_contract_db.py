# broker/nuvama/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from Nuvama's contract file.
#
# Source: https://nc.nuvamawealth.com/app/toccontracts/instruments.zip (public,
# no session needed; the official SDK downloads the same file). One CSV,
# instruments.csv, with columns:
#   exchangetoken, tradingsymbol, symbolname, description, expiry, strikeprice,
#   ticksize, lotsize, optiontype, series, assettype, exchange, isin, qtyunits,
#   prcunits, prcqtn, multiplier, asmgsmflag, asmgsmmsg
#
# Checked against the live file (185k rows, November 2026):
# - Equity rows carry the ISIN in `tradingsymbol` and the exchange symbol in
#   `symbolname` (M&M, BAJAJ-AUTO). Orders send the ISIN as trdSym, so it is
#   brsymbol; the OpenAlgo symbol is symbolname.
# - Index rows have a bare negative exchangetoken (-29 for Nifty 50) and the
#   display name in tradingsymbol.
# - Futures have optiontype XX and strike -0.01 or 0.
# - expiry is DD/MMM/YY.
# - lotsize is in units for every segment (CRUDEOIL 100, COPPER 2500).
# - NSE rows can appear twice, identical; they are dropped on exchangetoken.

import io
import os
import zipfile

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.nuvama.api.baseurl import CONTRACT_URL
from broker.nuvama.mapping.exchange import oa_index_exchange, oa_index_symbol
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

COLUMNS = [
    "symbol",
    "brsymbol",
    "name",
    "exchange",
    "brexchange",
    "token",
    "expiry",
    "strike",
    "lotsize",
    "instrumenttype",
    "tick_size",
]


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
    # In the canonical schema (database/symbol.py); left NULL.
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
        raise


def download_nuvama_instruments():
    """Download and unzip instruments.csv into a DataFrame of strings."""
    client = get_httpx_client()
    response = client.get(CONTRACT_URL, timeout=120.0)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
        if not name:
            raise ValueError("The Nuvama contract file has no CSV inside")
        with archive.open(name) as handle:
            return pd.read_csv(handle, dtype=str, keep_default_na=False)


def _format_strike(values):
    """Strike text for a symbol: 2250 not 2250.0, 101.25 kept."""
    return values.map(lambda v: f"{v:f}".rstrip("0").rstrip("."))


def process_nuvama_csv(df):
    """Map the contract file onto the SymToken columns, vectorised."""
    logger.info("Processing Nuvama contract file")
    df = df.drop_duplicates(subset=["exchangetoken"], keep="first").copy()

    exchange = df["exchange"].str.strip().str.upper()
    asset = df["assettype"].str.strip().str.upper()
    opttype = df["optiontype"].str.strip().str.upper()

    tick = pd.to_numeric(df["ticksize"], errors="coerce").fillna(0.0)
    lot = pd.to_numeric(df["lotsize"], errors="coerce").fillna(1).astype(int)
    strike = pd.to_numeric(df["strikeprice"], errors="coerce").fillna(0.0).clip(lower=0) + 0.0
    expiry_dt = pd.to_datetime(df["expiry"], format="%d/%b/%y", errors="coerce")
    expiry = expiry_dt.dt.strftime("%d-%b-%y").str.upper().fillna("")
    expiry_code = expiry_dt.dt.strftime("%d%b%y").str.upper().fillna("")

    frames = []

    # Equity: symbol = exchange symbol, brsymbol = ISIN (what orders send).
    eq = asset == "EQUITY"
    frames.append(
        pd.DataFrame(
            {
                "symbol": df.loc[eq, "symbolname"].str.strip(),
                "brsymbol": df.loc[eq, "tradingsymbol"].str.strip(),
                "name": df.loc[eq, "description"].str.strip(),
                "exchange": exchange[eq],
                "brexchange": exchange[eq],
                "token": df.loc[eq, "exchangetoken"].str.strip(),
                "expiry": "",
                "strike": 0.0,
                "lotsize": lot[eq],
                "instrumenttype": "EQ",
                "tick_size": tick[eq],
            }
        )
    )

    # Indices: OpenAlgo index symbols, exchange NSE_INDEX / BSE_INDEX.
    ix = asset == "INDEX"
    idx = df.loc[ix]
    frames.append(
        pd.DataFrame(
            {
                "symbol": [
                    oa_index_symbol(n, e)
                    for n, e in zip(idx["tradingsymbol"], exchange[ix], strict=True)
                ],
                "brsymbol": idx["tradingsymbol"].str.strip(),
                "name": idx["symbolname"].str.strip(),
                "exchange": [oa_index_exchange(e) for e in exchange[ix]],
                "brexchange": exchange[ix],
                "token": idx["exchangetoken"].str.strip(),
                "expiry": "",
                "strike": 0.0,
                "lotsize": lot[ix],
                "instrumenttype": "EQ",
                "tick_size": tick[ix].where(tick[ix] > 0, 0.05),
            }
        )
    )

    # Derivatives: futures (optiontype XX) and options (CE/PE).
    der = ~(eq | ix)
    # NCDEX option rows carry the underlying's own expiry in symbolname
    # (TMCFGRNZM18DEC2026); strip it so the underlying reads TMCFGRNZM.
    underlying = (
        df.loc[der, "symbolname"].str.strip().str.replace(r"\d{2}[A-Z]{3}\d{4}$", "", regex=True)
    )
    is_opt = opttype[der].isin(["CE", "PE"])
    inst = np.where(is_opt, opttype[der], "FUT")
    strike_der = strike[der].where(is_opt, 0.0)
    oa_symbol = np.where(
        is_opt,
        underlying + expiry_code[der] + _format_strike(strike_der) + opttype[der],
        underlying + expiry_code[der] + "FUT",
    )
    frames.append(
        pd.DataFrame(
            {
                "symbol": oa_symbol,
                "brsymbol": df.loc[der, "tradingsymbol"].str.strip(),
                "name": underlying,
                "exchange": exchange[der],
                "brexchange": exchange[der],
                "token": df.loc[der, "exchangetoken"].str.strip(),
                "expiry": expiry[der],
                "strike": strike_der,
                "lotsize": lot[der],
                "instrumenttype": inst,
                "tick_size": tick[der],
            }
        )
    )

    out = pd.concat(frames, ignore_index=True)[COLUMNS]
    out = out[(out["symbol"] != "") & (out["token"] != "")]
    # A derivative with an unreadable expiry would get a symbol without one.
    bad = (out["instrumenttype"] != "EQ") & (out["expiry"] == "")
    if bad.any():
        logger.warning(f"Skipped {int(bad.sum())} Nuvama derivative rows without an expiry")
        out = out[~bad]
    before = len(out)
    out = out.drop_duplicates(subset=["symbol", "exchange"], keep="first")
    if len(out) != before:
        logger.info(f"Dropped {before - len(out)} rows that repeat a symbol on its exchange")
    return out


def master_contract_download():
    """Entry point (called after login): download, rebuild SymToken, tell the UI."""
    logger.info("Downloading Nuvama Master Contract")
    try:
        token_df = process_nuvama_csv(download_nuvama_instruments())
        delete_symtoken_table()
        copy_from_dataframe(token_df)
        logger.info(f"Nuvama master contract loaded with {len(token_df)} instruments")
        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception(f"Nuvama master contract download failed: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        # Runs on a background thread, outside the app teardown.
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
