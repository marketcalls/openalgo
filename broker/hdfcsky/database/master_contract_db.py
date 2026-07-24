# broker/hdfcsky/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from HDFC Sky's Security Master.
#
# Source (public, NO auth required):
#   GET https://hdfcsky.com/api/v1/contract/Compact?info=download
#     -> a ZIP archive containing a single CompactScrip.csv (~182k rows, 17 MB)
#
# CSV columns (verified against the live file):
#   exchange_token, trading_symbol, company_name, close_price, expiry, strike,
#   tick_size, lot_size, instrument_name, option_type, segment, exchange,
#   fin_instrm_pdct_tp_cd, asset_code, settlement_type, isin
#
# Facts established from the live file (do NOT re-derive from the docs):
#   - `exchange` is already NSE / BSE / NFO / BFO / CDS / MCX. Indices are NOT
#     a separate exchange: they are NSE rows with segment "INDICES" and BSE
#     rows with segment "IDX".
#   - Cash trading symbols carry the SERIES as a suffix: "RELIANCE-EQ",
#     "BAJAJ-AUTO-EQ", "M&M-EQ" on NSE and "RELIANCE-A", "M&M-A" on BSE. Only
#     the suffix may be stripped -- a naive split("-") destroys BAJAJ-AUTO.
#   - Derivative trading symbols are "<UNDERLYING><YY><EXPIRY><STRIKE?><TYPE>",
#     e.g. NIFTY26AUGFUT, M&M26AUG4050PE, SENSEX2681369500CE (weekly),
#     EURINR26O01FUT (Oct/Nov/Dec weeklies use the letters O/N/D). The
#     underlying is recovered by stripping that suffix, which resolves 100% of
#     the 157k derivative rows and agrees with `company_name` on every row
#     where company_name is meaningful (it is empty on MCX and a copy of the
#     trading symbol on CDS).
#   - `strike` is unscaled rupees on every segment; futures carry the
#     placeholder -0.01. `tick_size` is already in rupees.
#   - Timestamps: `expiry` is "DD-Mon-YYYY"; non-expiring rows use the sentinel
#     "01-Jan-0001".
#
# Processing is fully vectorized (pandas column ops, no iterrows) -- 182k rows
# in a couple of seconds.

import io
import os
import zipfile

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.hdfcsky.api.baseurl import SECURITY_MASTER_URL, USER_AGENT
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
    # Present in the canonical schema (database/symbol.py); always NULL here
    # but declared so a fresh-install create_all() matches the shared table.
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


# --- download -----------------------------------------------------------


def download_security_master():
    """Fetch and unzip the Security Master into a DataFrame.

    The endpoint is public (no Authorization header), which is why the master
    contract can be rebuilt even when the broker session has expired.
    """
    client = get_httpx_client()
    # Explicit generous timeout: the archive is ~2.4 MB compressed / 17 MB raw.
    response = client.get(
        SECURITY_MASTER_URL, headers={"User-Agent": USER_AGENT}, timeout=180
    )
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(
                f"HDFC Sky security master archive has no CSV member: {archive.namelist()}"
            )
        with archive.open(csv_names[0]) as fh:
            # dtype=str: skip pandas type inference entirely (mixed-type columns
            # like isin/segment would otherwise warn). Numerics are converted
            # explicitly below.
            df = pd.read_csv(fh, dtype=str, low_memory=False)

    df.columns = [str(c).strip() for c in df.columns]
    logger.info(f"Downloaded HDFC Sky security master: {len(df)} rows")
    return df


# --- parsing ------------------------------------------------------------

# Weekly-contract month codes, keyed by the uppercase month abbreviation the
# formatted expiry carries. Jan-Sep use the plain month digit; Oct/Nov/Dec use
# the letters O/N/D because a two-digit month would be ambiguous against the
# day that follows it.
_MONTH_ABBRS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_WEEKLY_MONTH_DIGITS = {
    abbr: (str(index + 1) if index < 9 else "") for index, abbr in enumerate(_MONTH_ABBRS)
}
_WEEKLY_MONTH_LETTERS = dict.fromkeys(_MONTH_ABBRS, "")
_WEEKLY_MONTH_LETTERS.update({"OCT": "O", "NOV": "N", "DEC": "D"})


def _format_strike_series(strike):
    """Render strikes the way symbols embed them: int when whole (4050), else
    decimal (262.5, 1.275)."""
    whole = strike == strike.astype("int64")
    return pd.Series(
        np.where(whole, strike.astype("int64").astype(str), strike.astype(str)),
        index=strike.index,
    )


def _strip_broker_suffix(trading_symbols, monthly_suffix, weekly_suffix, weekly_alpha_suffix, is_deriv):
    """Recover the underlying by removing the broker's expiry/strike suffix.

    Three suffix shapes exist in the live master:
      monthly       NIFTY   + 26AUG    + FUT
      weekly        SENSEX  + 26813    + 69500CE   (YY + month-number + DD)
      weekly alpha  EURINR  + 26O01    + FUT       (YY + O/N/D + DD)
    Returns "" when none matches, so the caller can fall back.
    """
    out = []
    for symbol, monthly, weekly, weekly_alpha, deriv in zip(
        trading_symbols, monthly_suffix, weekly_suffix, weekly_alpha_suffix, is_deriv, strict=True
    ):
        if not deriv:
            out.append("")
            continue
        base = ""
        for suffix in (monthly, weekly, weekly_alpha):
            if suffix and symbol.endswith(suffix):
                base = symbol[: -len(suffix)]
                break
        out.append(base)
    return out


# --- index symbol mapping -----------------------------------------------
#
# HDFC Sky flags index rows via the `segment` column: NSE indices carry
# "INDICES" and BSE indices carry "IDX". These are NOT a separate exchange in
# the CSV, so the master builder pulls them out of the parent cash exchange
# into OpenAlgo's NSE_INDEX / BSE_INDEX.
INDEX_SEGMENTS = {"NSE": "INDICES", "BSE": "IDX"}

# HDFC Sky ships index rows with human display names on NSE ("Nifty 50",
# "Nifty Bank") and short codes on BSE ("SENSEX", "SNSX50", "BSE HC").
# OpenAlgo standardizes both to the symbols documented in
# docs/prompt/symbol-format.md -- the same set the Zerodha reference
# implementation produces, so option tools that start from an index LTP
# (option chain, IV smile, max pain, GEX, OI tracker) resolve identically
# across brokers.
#
# Lookup keys are uppercased with all whitespace removed. Anything not listed
# falls back to its cleaned (uppercased, space-stripped) name, which keeps new
# indices addressable the moment HDFC adds them.

_NSE_INDEX_MAP = {
    # Derivative underlyings -- these five MUST match the NFO `name` column
    # so the options tools can join index spot to its option chain.
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "INDIAVIX": "INDIAVIX",
    # Broad market
    "NIFTY100": "NIFTY100",
    "NIFTY200": "NIFTY200",
    "NIFTY500": "NIFTY500",
    # Sectoral
    "NIFTYALPHA50": "NIFTYALPHA50",
    "NIFTYAUTO": "NIFTYAUTO",
    "NIFTYCHEMICALS": "NIFTYCHEMICALS",
    "NIFTYCOMMODITIES": "NIFTYCOMMODITIES",
    "NIFTYCONSUMPTION": "NIFTYCONSUMPTION",
    "NIFTYCPSE": "NIFTYCPSE",
    "NIFTYDIVOPPS50": "NIFTYDIVOPPS50",
    "NIFTYENERGY": "NIFTYENERGY",
    "NIFTYFMCG": "NIFTYFMCG",
    "NIFTYGROWSECT15": "NIFTYGROWSECT15",
    "NIFTYHEALTHCARE": "NIFTYHEALTHCARE",
    "NIFTYINFRA": "NIFTYINFRA",
    "NIFTYIT": "NIFTYIT",
    "NIFTYMEDIA": "NIFTYMEDIA",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYMNC": "NIFTYMNC",
    "NIFTYOILANDGAS": "NIFTYOILANDGAS",
    "NIFTYPHARMA": "NIFTYPHARMA",
    "NIFTYPSE": "NIFTYPSE",
    "NIFTYPSUBANK": "NIFTYPSUBANK",
    "NIFTYPVTBANK": "NIFTYPVTBANK",
    "NIFTYREALTY": "NIFTYREALTY",
    "NIFTYSERVSECTOR": "NIFTYSERVSECTOR",
    # Market cap
    "NIFTYMIDLIQ15": "NIFTYMIDLIQ15",
    "NIFTYMIDCAP50": "NIFTYMIDCAP50",
    "NIFTYMIDCAP100": "NIFTYMIDCAP100",
    "NIFTYMIDCAP150": "NIFTYMIDCAP150",
    "NIFTYMIDSML400": "NIFTYMIDSML400",
    "NIFTYSMLCAP50": "NIFTYSMLCAP50",
    "NIFTYSMLCAP100": "NIFTYSMLCAP100",
    "NIFTYSMLCAP250": "NIFTYSMLCAP250",
    # Strategy
    "NIFTY100EQLWGT": "NIFTY100EQLWGT",
    "NIFTY100LIQ15": "NIFTY100LIQ15",
    "NIFTY100LOWVOL30": "NIFTY100LOWVOL30",
    "NIFTY100QUALTY30": "NIFTY100QUALTY30",
    "NIFTY200QUALTY30": "NIFTY200QUALTY30",
    "NIFTY50DIVPOINT": "NIFTY50DIVPOINT",
    "NIFTY50EQLWGT": "NIFTY50EQLWGT",
    "NIFTY50PR1XINV": "NIFTY50PR1XINV",
    "NIFTY50PR2XLEV": "NIFTY50PR2XLEV",
    "NIFTY50TR1XINV": "NIFTY50TR1XINV",
    "NIFTY50TR2XLEV": "NIFTY50TR2XLEV",
    "NIFTY50VALUE20": "NIFTY50VALUE20",
    # Government securities
    "NIFTYGS10YR": "NIFTYGS10YR",
    "NIFTYGS10YRCLN": "NIFTYGS10YRCLN",
    "NIFTYGS1115YR": "NIFTYGS1115YR",
    "NIFTYGS15YRPLUS": "NIFTYGS15YRPLUS",
    "NIFTYGS48YR": "NIFTYGS48YR",
    "NIFTYGS813YR": "NIFTYGS813YR",
    "NIFTYGSCOMPSITE": "NIFTYGSCOMPSITE",
}

# BSE short codes (the CSV's `trading_symbol` for IDX rows) -> OpenAlgo symbol.
_BSE_INDEX_MAP = {
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SNSX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE100": "BSE100",
    "BSE200": "BSE200",
    "BSE500": "BSE500",
    "MID150": "BSE150MIDCAPINDEX",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "AUTO": "BSEAUTO",
    "BSECG": "BSECAPITALGOODS",
    "BSECD": "BSECONSUMERDURABLES",
    "CPSE": "BSECPSE",
    "ENERGY": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FINSER": "BSEFINANCIALSERVICES",
    "BSEHC": "BSEHEALTHCARE",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO": "BSEIPO",
    "METAL": "BSEMETAL",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "UTILS": "BSEUTILITIES",
    "ESG100": "ESG100",
    "BHRT22": "BHRT22",
    "FOCIT": "FOCIT",
}

_INDEX_MAPS = {"NSE_INDEX": _NSE_INDEX_MAP, "BSE_INDEX": _BSE_INDEX_MAP}


def _norm(name):
    return "".join(str(name).upper().split())


def classify_index_symbol(display_name, oa_exchange):
    """HDFC Sky index display name -> the OpenAlgo index symbol.

    Unmapped names fall back to their normalized (uppercase, space-free) form
    so newly listed indices are still addressable.
    """
    key = _norm(display_name)
    return _INDEX_MAPS.get(oa_exchange, {}).get(key, key)


def process_security_master(df):
    """Transform the Security Master DataFrame into SymToken rows."""
    logger.info("Processing HDFC Sky security master")

    df = df.fillna("")
    trading_symbol = df["trading_symbol"].str.strip()
    segment = df["segment"].str.strip()
    brexchange = df["exchange"].str.strip().str.upper()
    option_type = df["option_type"].str.strip().str.upper()
    company_name = df["company_name"].str.strip()

    # --- exchange: split indices out of the parent cash exchange ---------
    exchange = brexchange.copy()
    for cash_exchange, index_segment in INDEX_SEGMENTS.items():
        exchange = exchange.mask(
            (brexchange == cash_exchange) & (segment == index_segment),
            f"{cash_exchange}_INDEX",
        )
    is_index = exchange.isin([f"{e}_INDEX" for e in INDEX_SEGMENTS])

    # --- expiry: "25-Aug-2026" -> "25-AUG-26"; sentinel dates -> "" -------
    expiry_dt = pd.to_datetime(df["expiry"], format="%d-%b-%Y", errors="coerce")
    expiry_dt = expiry_dt.where(expiry_dt.dt.year > 1900)
    expiry = expiry_dt.dt.strftime("%d-%b-%y").str.upper().fillna("")
    expiry_compact = expiry.str.replace("-", "", regex=False)

    # --- numerics --------------------------------------------------------
    # Futures carry the placeholder strike -0.01; clip to 0 (the "+ 0.0"
    # normalizes the negative zero clip() leaves behind).
    strike = pd.to_numeric(df["strike"], errors="coerce").fillna(0.0).clip(lower=0.0) + 0.0
    tick_size = pd.to_numeric(df["tick_size"], errors="coerce").fillna(0.0)
    lotsize = pd.to_numeric(df["lot_size"], errors="coerce").fillna(0).astype("int64")
    strike_str = _format_strike_series(strike)

    is_option = option_type.isin(["CE", "PE"])
    is_future = (~is_option) & (expiry != "") & trading_symbol.str.endswith("FUT")
    is_deriv = is_option | is_future

    # --- underlying ------------------------------------------------------
    # Slice the already-formatted "DD-MMM-YY" expiry instead of calling
    # dt.strftime() three more times -- strftime dominates the runtime on a
    # 182k-row frame (~1.6s per call).
    day = expiry.str.slice(0, 2)
    month_abbr = expiry.str.slice(3, 6)
    year = expiry.str.slice(7, 9)
    month_weekly = month_abbr.map(_WEEKLY_MONTH_DIGITS).fillna("")
    month_weekly_alpha = month_abbr.map(_WEEKLY_MONTH_LETTERS).fillna("")

    tail = pd.Series(
        np.where(is_future, "FUT", np.where(is_option, strike_str + option_type, "")),
        index=df.index,
    )
    underlying = pd.Series(
        _strip_broker_suffix(
            trading_symbol,
            year + month_abbr + tail,
            (year + month_weekly + day + tail).where(month_weekly != "", ""),
            (year + month_weekly_alpha + day + tail).where(month_weekly_alpha != "", ""),
            is_deriv,
        ),
        index=df.index,
    )
    # Fall back to company_name for any row whose symbol does not follow the
    # documented shape (a handful of exchange test scrips carry an expiry that
    # disagrees with their own trading symbol).
    underlying = underlying.where(underlying != "", company_name)

    # --- symbol ----------------------------------------------------------
    symbol = trading_symbol.copy()

    # NSE cash: strip ONLY the "-EQ" series suffix. Every other series keeps
    # its suffix -- both BAJAJ-AUTO-EQ and BAJAJ-AUTO-T0 exist, and stripping
    # both would collide on "BAJAJ-AUTO". This matches the Zerodha-built table.
    nse_eq = (brexchange == "NSE") & trading_symbol.str.endswith("-EQ")
    symbol = symbol.mask(nse_eq, trading_symbol.str.slice(stop=-3))

    # BSE cash: strip the "-<group>" suffix (A/B/T/X/...) so BSE symbols read
    # RELIANCE / M&M / BAJAJ-AUTO like every other broker's BSE rows.
    bse_cash = (brexchange == "BSE") & (segment != INDEX_SEGMENTS["BSE"])
    bse_stripped = pd.Series(
        [
            row[: -(len(series) + 1)] if series and row.endswith(f"-{series}") else row
            for row, series in zip(trading_symbol, segment, strict=True)
        ],
        index=df.index,
    )
    symbol = symbol.mask(bse_cash, bse_stripped)

    # Derivatives -> the OpenAlgo common format.
    symbol = symbol.mask(is_future, underlying + expiry_compact + "FUT")
    symbol = symbol.mask(is_option, underlying + expiry_compact + strike_str + option_type)

    # Indices -> the documented OpenAlgo index symbols.
    if is_index.any():
        symbol.loc[is_index] = [
            classify_index_symbol(display, oa_exchange)
            for display, oa_exchange in zip(
                trading_symbol[is_index], exchange[is_index], strict=True
            )
        ]

    # OpenAlgo stores indices as instrumenttype "EQ" (the NSE_INDEX/BSE_INDEX
    # exchange is what distinguishes them). There is NO "INDEX" type.
    instrumenttype = pd.Series("EQ", index=df.index)
    instrumenttype = instrumenttype.mask(is_future, "FUT").mask(is_option, option_type)

    # `name`: underlying for derivatives, company/display name otherwise.
    name = company_name.where(company_name != "", trading_symbol)
    name = name.mask(is_deriv & (underlying != ""), underlying)

    out = pd.DataFrame(
        {
            "symbol": symbol,
            "brsymbol": trading_symbol,
            "name": name,
            "exchange": exchange,
            "brexchange": brexchange,
            "token": df["exchange_token"].str.strip(),
            "expiry": expiry,
            "strike": strike,
            "lotsize": lotsize,
            "instrumenttype": instrumenttype,
            "tick_size": tick_size,
        }
    )

    # MCX ships ~400 non-tradable "COM" rows (the underlying commodity
    # definitions, sentinel expiry 01-Jan-0001) alongside its real contracts.
    non_tradable_mcx = (brexchange == "MCX") & (~is_deriv)
    out = out[~non_tradable_mcx]

    out = out[(out["symbol"] != "") & (out["token"] != "") & out["exchange"].notna()]
    # Safety net: a duplicate (symbol, exchange) would make get_token()
    # ambiguous. The live master only produces these for exchange test scrips.
    before = len(out)
    out = out.drop_duplicates(subset=["symbol", "exchange"], keep="first")
    if before != len(out):
        logger.info(f"Dropped {before - len(out)} duplicate (symbol, exchange) rows")

    logger.info(f"Processed {len(out)} HDFC Sky instruments")
    return out.reset_index(drop=True)


def master_contract_download():
    """Entry point (called post-login). Downloads + rebuilds the SymToken table."""
    logger.info("Downloading HDFC Sky Master Contract")
    try:
        raw = download_security_master()
        token_df = process_security_master(raw)

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception(f"HDFC Sky master contract download failed: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
    finally:
        # Runs in a background thread, so the Flask app teardown will not
        # release the scoped session for us.
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
