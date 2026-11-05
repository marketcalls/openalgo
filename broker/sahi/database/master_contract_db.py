"""Sahi master contract: the daily scrip master mapped onto OpenAlgo's symtoken.

Sahi publishes one public CSV, rebuilt around 06:00 IST each trading day
(broker-api-docs/sahi-api-docs, Scrip master):

    https://assets.sahi.com/external/instruments.csv
    id,isin,symbol,company_name,series,underlying_symbol,exchange,segment,token,
    instrument_type,option_type,expiry_date,strike_price,lot_size,tick_size,
    freeze_quantity,price_precision,price_multiplier

How the columns land in symtoken:

    token       Sahi's ``id``. Market data (quotes, candles, the tick stream)
                is addressed by this id, never by the exchange token.
    brsymbol    Sahi's ``symbol``, which is what orders take together with
                ``exchange_segment``. Index rows carry no symbol (they cannot be
                traded), so their display name (``Nifty 50``, ``Sensex``) is
                used instead.
    brexchange  Sahi's ``segment``: NSE, BSE, NFO or BFO.

Only the NSE, BSE, NFO and BFO segments are loaded. The file also lists MCX and
NCOM contracts, but Sahi's order API rejects commodity orders and its market
data enum has no commodity segment.
"""

import os
import re
from io import StringIO

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.sahi.api.baseurl import SCRIP_MASTER_URL, USER_AGENT
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
    contract_value = Column(Float)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


SUPPORTED_SEGMENTS = ("NSE", "BSE", "NFO", "BFO")

# NSE index display names whose OpenAlgo symbol is not simply the name in
# capitals with spaces and punctuation removed (docs/prompt/symbol-format.md).
NSE_INDEX_SYMBOLS = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
    "INDIA VIX": "INDIAVIX",
    "NIFTY SMALLCAP 50": "NIFTYSMLCAP50",
    "NIFTY SMALLCAP 100": "NIFTYSMLCAP100",
    "NIFTY SMALLCAP 250": "NIFTYSMLCAP250",
    "NIFTY MIDSMALLCAP 400": "NIFTYMIDSML400",
    "NIFTY MIDCAP LIQUID 15": "NIFTYMIDLIQ15",
    "NIFTY INFRASTRUCTURE": "NIFTYINFRA",
    "NIFTY INDIA CONSUMPTION": "NIFTYCONSUMPTION",
    "NIFTY DIVIDEND OPPORTUNITIES 50": "NIFTYDIVOPPS50",
    "NIFTY GROWTH SECTORS 15": "NIFTYGROWSECT15",
    "NIFTY PRIVATE BANK": "NIFTYPVTBANK",
    "NIFTY SERVICES SECTOR": "NIFTYSERVSECTOR",
    "NIFTY 10 YR BENCHMARK G-SEC": "NIFTYGS10YR",
    "NIFTY 10 YR BENCHMARK G-SEC (CLEAN PRICE)": "NIFTYGS10YRCLN",
    "NIFTY 4-8 YR G-SEC INDEX": "NIFTYGS48YR",
    "NIFTY 8-13 YR G-SEC": "NIFTYGS813YR",
    "NIFTY 11-15 YR G-SEC INDEX": "NIFTYGS1115YR",
    "NIFTY 15 YR AND ABOVE G-SEC INDEX": "NIFTYGS15YRPLUS",
    "NIFTY COMPOSITE G-SEC INDEX": "NIFTYGSCOMPSITE",
    "NIFTY100 EQUAL WEIGHT": "NIFTY100EQLWGT",
    "NIFTY100 LIQUID 15": "NIFTY100LIQ15",
    "NIFTY100 LOW VOLATILITY 30": "NIFTY100LOWVOL30",
    "NIFTY100 QUALITY 30": "NIFTY100QUALTY30",
    "NIFTY200 QUALITY 30": "NIFTY200QUALTY30",
    "NIFTY50 DIVIDEND POINTS": "NIFTY50DIVPOINT",
    "NIFTY50 EQUAL WEIGHT": "NIFTY50EQLWGT",
    "NIFTY50 PR 1X INVERSE": "NIFTY50PR1XINV",
    "NIFTY50 PR 2X LEVERAGE": "NIFTY50PR2XLEV",
    "NIFTY50 TR 1X INVERSE": "NIFTY50TR1XINV",
    "NIFTY50 TR 2X LEVERAGE": "NIFTY50TR2XLEV",
}

# BSE index rows carry the exchange's short code as their name; these are the
# OpenAlgo symbols for the codes listed in docs/prompt/symbol-format.md.
BSE_INDEX_SYMBOLS = {
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX 50": "SENSEX50",
    "BSE100": "BSE100",
    "MID150": "BSE150MIDCAPINDEX",
    "BSE200": "BSE200",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "BSE500": "BSE500",
    "AUTO": "BSEAUTO",
    "BSE CG": "BSECAPITALGOODS",
    "CARBON": "BSECARBONEX",
    "BSE CD": "BSECONSUMERDURABLES",
    "CPSE": "BSECPSE",
    "ENERGY": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FINSER": "BSEFINANCIALSERVICES",
    "GREENX": "BSEGREENEX",
    "BSE HC": "BSEHEALTHCARE",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSE IT": "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO": "BSEIPO",
    "LRGCAP": "BSELARGECAP",
    "METAL": "BSEMETAL",
    "MIDCAP": "BSEMIDCAP",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SNXT50": "BSESENSEXNEXT50",
    "SMLCAP": "BSESMALLCAP",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "ALLCAP": "BSEALLCAP",
    "BHRT22": "BSEBHARAT22INDEX",
    "SML250": "BSE250SMALLCAPINDEX",
    "UTILS": "BSEUTILITIES",
    "ESG100": "BSE100ESG",
    "LCTMCI": "BSE100LARGECAPTMCINDEX",
    "DFRGRI": "BSEDIVERSIFIEDFINANCIALSREVENUEGROWTHINDEX",
    "BSEDSI": "BSEDIVIDENDSTABILITY",
    "BSEEVI": "BSEENHANCEDVALUE",
    "BSELVI": "BSELOWVOLATILITY",
    "BSEMOI": "BSEMOMENTUM",
    "BSEPBI": "BSEPRIVATEBANKS",
    "BSEQUI": "BSEQUALITY",
    "BSHOSP": "BSEHOSPITALS",
    "FOCIT": "BSEFOCUSEDIT",
    "CONDIS": "BSECONSUMERDISCRETIONARYGOODS&SERVICES",
}


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    """Bulk insert the processed rows in batches."""
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient="records")
    batch_size = 10000
    try:
        total = len(data_dict)
        for i in range(0, total, batch_size):
            db_session.bulk_insert_mappings(SymToken, data_dict[i : i + batch_size])
            db_session.flush()
        db_session.commit()
        logger.info(f"Bulk insert completed successfully with {total} records.")
    except Exception:
        db_session.rollback()
        logger.exception("Error during Sahi master contract bulk insert")
        raise


def download_sahi_scrip_master():
    """Fetch the day's scrip master CSV and return it as a string DataFrame."""
    client = get_httpx_client()
    response = client.get(SCRIP_MASTER_URL, headers={"User-Agent": USER_AGENT}, timeout=120)
    response.raise_for_status()
    # Read every column as text; numerics are converted explicitly below.
    return pd.read_csv(StringIO(response.text), dtype=str, keep_default_na=False)


def _index_symbol(name, exchange):
    """OpenAlgo index symbol for a Sahi index display name."""
    key = " ".join(name.upper().split())
    table = NSE_INDEX_SYMBOLS if exchange == "NSE" else BSE_INDEX_SYMBOLS
    if key in table:
        return table[key]
    return re.sub(r"[^A-Z0-9&]", "", key)


def _format_strike(strikes):
    """Strike text as it appears in an OpenAlgo symbol: 25000, 187.5, 0.25."""
    return strikes.map(lambda s: f"{s:.4f}".rstrip("0").rstrip("."))


def process_sahi_scrip_master(df):
    """Map the raw scrip master onto symtoken rows (vectorized)."""
    df = df[df["segment"].isin(SUPPORTED_SEGMENTS)].copy()

    df["strike_num"] = pd.to_numeric(df["strike_price"], errors="coerce").fillna(0.0)
    df["lot_num"] = pd.to_numeric(df["lot_size"], errors="coerce").fillna(0).astype(int)
    df["tick_num"] = pd.to_numeric(df["tick_size"], errors="coerce").fillna(0.0)
    df["id_num"] = pd.to_numeric(df["id"], errors="coerce")

    itype = df["instrument_type"]
    is_index = itype == "IDX"
    is_cash = itype.isin(["STK", "ETF"])
    is_fut = itype.isin(["FUTIDX", "FUTSTK"])
    is_opt = itype.isin(["OPTIDX", "OPTSTK"]) & df["option_type"].isin(["CE", "PE"])
    df = df[is_index | is_cash | is_fut | is_opt].copy()
    is_index, is_cash, is_fut, is_opt = (
        m.loc[df.index] for m in (is_index, is_cash, is_fut, is_opt)
    )

    out = pd.DataFrame(index=df.index)
    out["token"] = df["id"]
    out["brexchange"] = df["segment"]
    out["brsymbol"] = df["symbol"]
    out["name"] = df["company_name"]
    out["exchange"] = df["segment"]
    out["expiry"] = ""
    out["strike"] = 0.0
    out["lotsize"] = df["lot_num"]
    out["tick_size"] = df["tick_num"]
    out["instrumenttype"] = "EQ"
    out["symbol"] = df["symbol"]

    # Cash: Sahi drops the -EQ suffix on NSE but keeps other series
    # (3IINFOLTD-BE); OpenAlgo's symbol is the bare name, as on other brokers.
    # Only a suffix equal to the row's own series is stripped, so names with a
    # hyphen of their own (BAJAJ-AUTO) are untouched.
    series_suffix = "-" + df["series"]
    strip = is_cash & (df["segment"] == "NSE") & (df["series"] != "") & (df["series"] != "EQ")
    strip &= np.array(
        [s.endswith(x) for s, x in zip(df["symbol"], series_suffix, strict=True)], dtype=bool
    )
    out.loc[strip, "symbol"] = [
        s[: -len(x)] for s, x in zip(df.loc[strip, "symbol"], series_suffix[strip], strict=True)
    ]

    # Indices: no tradable symbol, so the display name is the broker symbol.
    if is_index.any():
        names = df.loc[is_index, "company_name"]
        out.loc[is_index, "brsymbol"] = names
        out.loc[is_index, "exchange"] = df.loc[is_index, "segment"] + "_INDEX"
        out.loc[is_index, "symbol"] = [
            _index_symbol(n, seg) for n, seg in zip(names, df.loc[is_index, "segment"], strict=True)
        ]

    # Derivatives: built from underlying + expiry (+ strike + CE/PE) rather than
    # parsed from Sahi's symbol, whose shape differs between NFO and BFO.
    deriv = is_fut | is_opt
    expiry = pd.to_datetime(df["expiry_date"].where(deriv, ""), format="%d-%m-%Y", errors="coerce")
    bad = deriv & expiry.isna()
    if bad.any():
        logger.warning(f"Skipping {int(bad.sum())} Sahi derivative rows with an unreadable expiry")
        keep = ~bad
        df, out, expiry = df[keep], out[keep], expiry[keep]
        is_fut, is_opt, deriv = is_fut[keep], is_opt[keep], deriv[keep]

    if deriv.any():
        datepart = expiry.dt.strftime("%d%b%y").str.upper()
        underlying = df["underlying_symbol"]
        out.loc[deriv, "expiry"] = expiry[deriv].dt.strftime("%d-%b-%y").str.upper()
        out.loc[deriv, "name"] = underlying[deriv]

        out.loc[is_fut, "instrumenttype"] = "FUT"
        out.loc[is_fut, "symbol"] = underlying[is_fut] + datepart[is_fut] + "FUT"

        out.loc[is_opt, "instrumenttype"] = df.loc[is_opt, "option_type"]
        out.loc[is_opt, "strike"] = df.loc[is_opt, "strike_num"]
        out.loc[is_opt, "symbol"] = (
            underlying[is_opt]
            + datepart[is_opt]
            + _format_strike(df.loc[is_opt, "strike_num"])
            + df.loc[is_opt, "option_type"]
        )

    # The BSE index list repeats some codes under several ids with the same
    # exchange token; keep the oldest id. Cash rows can also repeat a symbol
    # across series; keep the lowest id there too.
    out["id_num"] = df["id_num"]
    out = out[(out["symbol"] != "") & (out["brsymbol"] != "")]
    out = out.sort_values("id_num").drop_duplicates(subset=["symbol", "exchange"], keep="first")
    out = out.drop(columns=["id_num"])

    out["strike"] = out["strike"].astype(float) + 0.0
    out["contract_value"] = None
    columns = [
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
        "contract_value",
    ]
    return out[columns].reset_index(drop=True)


def master_contract_download():
    """Download, map and store the Sahi master contract, then tell the UI."""
    logger.info("Downloading Sahi Master Contract")
    try:
        raw = download_sahi_scrip_master()
        token_df = process_sahi_scrip_master(raw)
        logger.info(f"Sahi master contract mapped: {len(token_df)} instruments")
        delete_symtoken_table()
        copy_from_dataframe(token_df)
        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )
    except Exception as e:
        logger.exception("Sahi master contract download failed")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
