"""Pocketful master contract: the exchange-wise instrument files mapped onto symtoken.

Source. Pocketful's "Security Id List" page (api.pocketful.in/docs/curl/
security-id-list, offline copy of 2026-11-17) links two downloads:

    https://media.pocketful.in/contracts_dump/latest/contracts_dump.csv
    https://algo.pocketful.in/api/v1/contract/Compact?info=download&exchanges=NSE,NFO,BSE,BFO,MCX

The second, the exchange-wise files, is the one used here (the same route the
plugin used on the old trade.pocketful.in host). The page offers both as plain
links, and the request needs no session: fetched on 2026-11-17 with no token
and no header naming an account, it answered 200 with a ZIP (CompactFile.zip)
holding NSECompactScrip.csv, NFOCompactScrip.csv, BSECompactScrip.csv,
BFOCompactScrip.csv and MCXCompactScrip.csv. So no credential is sent. The
official SDK (pocketful 0.1.2) has no contract download at all: its routes
cover search (/api/v1/search) and scrip info (/api/v1/contract/{exchange}
?info=scrip) only.

Columns. Every file has the same header (verified on the 2026-11-17 download):

    exchange_token, trading_symbol, company_name, close_price, expiry, strike,
    tick_size, lot_size, instrument_name, option_type, segment, exchange,
    fin_instrm_pdct_tp_cd, asset_code

How they land in symtoken:

    token           exchange_token, the instrument token quotes, depth, history
                    and the feed take (scrip-info.md: "instrument_token").
    brsymbol        trading_symbol, unchanged: what an order sends.
    brexchange      exchange: NSE, BSE, NFO, BFO or MCX. Index rows keep the
                    cash exchange they are listed under (NSE or BSE).
    exchange        the OpenAlgo exchange: as brexchange, except index rows,
                    which go to NSE_INDEX (NSE segment "INDICES") and BSE_INDEX
                    (BSE segment "IDX").
    symbol          built per docs/prompt/symbol-format.md, see below.
    name            company_name for cash rows, the underlying for derivatives,
                    the index name for an index.
    expiry          expiry ("19-Nov-2026") as "19-NOV-26", empty for cash.
    strike          strike for options. Futures carry the placeholder -0.01,
                    stored as 0.
    lotsize         lot_size as given. Already the exchange lot in units on
                    every segment, MCX included (CRUDEOIL 100, GOLD 1, GOLDM 100,
                    MCXBULLDEX 15), the convention broker/zerodha/mapping/
                    mcx_contract_size.py documents for OpenAlgo.
    tick_size       tick_size as given. It is in rupees on every segment
                    (RELIANCE 0.10, NFO options 0.05, MCX CRUDEOIL 1.0,
                    NATURALGAS 0.10), so it is not rescaled: Market Price
                    Protection snaps prices to it. Index rows carry 0.
    instrumenttype  EQ for cash and index rows, FUT, CE or PE for derivatives.

Not used: close_price (a stale last close), fin_instrm_pdct_tp_cd and
asset_code (exchange product codes, blank outside BFO).

What each file needs (all established from the real download, not the docs,
which describe none of these files):

* NSE. ``segment`` is NSE's series (it equals ``instrument_name`` on every
  row), and every trading symbol ends in "-<series>" (RELIANCE-EQ, HFCL-BE,
  BAJAJ-AUTO-EQ). The OpenAlgo symbol is NSE's base symbol, so the series is
  stripped for the equity series EQ, BE, BZ, RR, IV, SM and ST, and only that
  one suffix: BAJAJ-AUTO-EQ becomes BAJAJ-AUTO. Debt, government securities,
  bonds, mutual fund units, warrants and partly paid shares keep their trading
  symbol. A row keeps its suffix if the bare name is already a symbol, so no
  two NSE rows share one. Index rows (segment "INDICES") carry NSE's feed
  names ("Nifty 50", "Nifty Fin Service").
* BSE. ``segment`` is the BSE group (A, B, T, X, M, F, G ...) and every trading
  symbol ends in "-<group>" (RELIANCE-A, M&M-A, BAJAJ-AUTO-A). The group is
  stripped. Index rows (segment "IDX") carry BSE's short codes (SENSEX,
  SNSX50, "BSE CG").
* NFO and BFO. ``option_type`` is CE, PE or XX (futures). ``company_name`` is
  the underlying on every row (NIFTY, SENSEX50, M&M). Weekly trading symbols
  use the YY + month digit or O/N/D + DD form (NIFTY26D0125850PE), so the
  symbol is built from the underlying and the expiry column, never parsed.
* MCX. ``company_name`` is blank on every row, so the underlying is the trading
  symbol with its own expiry and strike suffix removed (SILVER10026NOVFUT is
  SILVER100, not SILVER). The 400 "COM" rows are spot definitions with the
  sentinel expiry 01-Jan-0001 and no option type: not tradable, not loaded.
"""

import io
import os
import re
import shutil
import tempfile
import zipfile

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.pocketful.api.baseurl import BASE_URL
from database.engine_factory import create_db_engine
from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# The exchange-wise download exactly as the Security Id List page links it.
# The exchanges are written into the address rather than passed as params, so
# the commas reach the server as the page has them.
CONTRACT_EXCHANGES = ("NSE", "NFO", "BSE", "BFO", "MCX")
CONTRACT_URL = (
    f"{BASE_URL}/api/v1/contract/Compact?info=download&exchanges={','.join(CONTRACT_EXCHANGES)}"
)
CONTRACT_FILES = {exchange: f"{exchange}CompactScrip.csv" for exchange in CONTRACT_EXCHANGES}
# The archive is about 4 MB compressed and 16 MB of CSV.
DOWNLOAD_TIMEOUT = 180.0

REQUIRED_COLUMNS = (
    "exchange_token",
    "trading_symbol",
    "company_name",
    "expiry",
    "strike",
    "tick_size",
    "lot_size",
    "instrument_name",
    "option_type",
    "segment",
    "exchange",
)

SYMTOKEN_COLUMNS = [
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

# NSE series in which a company's own shares (or a trust's units) trade. The
# OpenAlgo symbol is the base symbol without the series, as NSE lists it
# (Symbol HFCL, Series BE). See .claude/skills/broker-integration/references/
# master-contract.md, "series suffixes".
NSE_EQUITY_SERIES = ("EQ", "BE", "BZ", "RR", "IV", "SM", "ST")

NSE_INDEX_SEGMENT = "INDICES"
BSE_INDEX_SEGMENT = "IDX"

# Exchange test indices ("INDEX1 NSETEST"): not real indices, not loaded.
NSE_TEST_INDEX = re.compile(r"NSETEST", re.IGNORECASE)

# NSE index names whose OpenAlgo symbol is not simply the name in capitals with
# spaces and hyphens removed (docs/prompt/symbol-format.md). Keyed by that
# normalized form, so "Nifty 50" and "NIFTY 50" both resolve.
NSE_INDEX_SYMBOLS = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    # The index NFO lists as the NIFTYFPI underlying, and the NSE_INDEX symbol
    # symbol-format.md documents. The plain rule would give NIFTYFPI150, and
    # the options tools join an index to its option chain by that symbol.
    "NIFTYFPI150": "NIFTYFPI",
}

# BSE index short codes -> OpenAlgo symbols (docs/prompt/symbol-format.md). The
# same table broker/dhan carries for BSE's codes, plus BSHOSP (broker/sahi).
# Keyed with whitespace removed ("BSE CG" -> "BSECG"). A code not listed keeps
# its own name without spaces, so a newly listed index is still addressable.
BSE_INDEX_SYMBOLS = {
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
    "BSEHC": "BSEHEALTHCARE",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "CARBON": "BSECARBONEX",
    "CPSE": "BSECPSE",
    "DOL100": "BSEDOLLEX100",
    "DOL200": "BSEDOLLEX200",
    "DOL30": "BSEDOLLEX30",
    "ENERGY": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FINSER": "BSEFINANCIALSERVICES",
    "GREENX": "BSEGREENEX",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSEIPO": "BSEIPO",
    "LRGCAP": "BSELARGECAP",
    "METAL": "BSEMETAL",
    "MIDCAP": "BSEMIDCAP",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SMLCAP": "BSESMALLCAP",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "ALLCAP": "BSEALLCAP",
    "BHRT22": "BSEBHARAT22INDEX",
    "BSEDSI": "BSEDIVIDENDSTABILITY",
    "BSEEVI": "BSEENHANCEDVALUE",
    "BSELVI": "BSELOWVOLATILITY",
    "BSEMOI": "BSEMOMENTUM",
    "BSEPBI": "BSEPRIVATEBANKS",
    "BSEQUI": "BSEQUALITY",
    "BSHOSP": "BSEHOSPITALS",
    "COMDTY": "BSEBASICMATERIALS",
    "CONDIS": "BSECONSUMERDISCRETIONARYGOODS&SERVICES",
    "DFRGRI": "BSEDIVERSIFIEDFINANCIALSREVENUEGROWTHINDEX",
    "ESG100": "BSE100ESG",
    "FOCIT": "BSEFOCUSEDIT",
    "LCTMCI": "BSE100LARGECAPTMCINDEX",
    "MFG": "BSEINDIAMANUFACTURING",
    "SML250": "BSE250SMALLCAPINDEX",
    "UTILS": "BSEUTILITIES",
}

# Weekly derivative symbols carry the month as one character: 1 to 9 for
# January to September, O, N and D for October to December.
_MONTH_ABBRS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_WEEKLY_MONTH_CODES = dict(
    zip(_MONTH_ABBRS, ("1", "2", "3", "4", "5", "6", "7", "8", "9", "O", "N", "D"), strict=True)
)

FAILED_MESSAGE = (
    "Could not refresh the Pocketful symbol list. Symbols from the last successful "
    "download are still in use. Try again in a few minutes."
)

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
    # Part of the shared schema (database/symbol.py). Left NULL here; declared
    # so a fresh install's create_all() builds the same table.
    contract_value = Column(Float)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    """Delete every row, without committing.

    The delete and the insert share one transaction (replace_symtoken_table),
    so a failed insert rolls back to the previous master contract instead of
    leaving the table empty.
    """
    logger.info("Clearing Symtoken Table")
    SymToken.query.delete()


def copy_from_dataframe(df, batch_size=10000):
    """Insert the processed rows and commit. Raises if the insert fails.

    Every row is inserted. Tokens are unique per exchange, not across them: a
    BSE index and an NSE share both use token 13, and MCX tokens repeat NFO
    ones. Skipping any token already in the table, as this did before, lost 26
    BSE and 57 MCX instruments from the 2026-11-17 contract.
    """
    logger.info("Performing Bulk Insert")
    records = df[SYMTOKEN_COLUMNS].to_dict(orient="records")
    try:
        for start in range(0, len(records), batch_size):
            db_session.bulk_insert_mappings(SymToken, records[start : start + batch_size])
            db_session.flush()
        db_session.commit()
        logger.info(f"Bulk insert completed with {len(records)} records")
    except Exception:
        db_session.rollback()
        logger.exception("Pocketful master contract insert failed")
        raise


def replace_symtoken_table(df):
    """Swap the stored master contract for ``df`` in one transaction."""
    if df is None or df.empty:
        raise ValueError("The Pocketful contract produced no instruments")
    try:
        delete_symtoken_table()
        copy_from_dataframe(df)
    except Exception:
        db_session.rollback()
        raise


# --- download -----------------------------------------------------------


def download_pocketful_contract(output_path):
    """Download the exchange-wise contract and write its five CSV files.

    The files go into ``output_path``, a directory the caller owns and removes.
    Only the five expected names are written, whatever else the archive holds,
    so a member name never chooses where a file lands. Raises if the download
    fails or a file is missing: nothing is written to symtoken from a partial
    contract.

    Returns:
        dict: exchange -> path of its CSV file.
    """
    client = get_httpx_client()
    # No session header: the contract is public (see the module docstring).
    response = client.get(CONTRACT_URL, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()

    paths = {}
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = set(archive.namelist())
        missing = [name for name in CONTRACT_FILES.values() if name not in members]
        if missing:
            raise ValueError(f"Pocketful contract archive is missing {', '.join(missing)}")
        for exchange, name in CONTRACT_FILES.items():
            target = os.path.join(output_path, name)
            with archive.open(name) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination)
            paths[exchange] = target
    logger.info(f"Downloaded the Pocketful contract: {', '.join(CONTRACT_FILES.values())}")
    return paths


# --- parsing helpers ----------------------------------------------------


def _read_contract_csv(path, exchange):
    """One exchange's file as text columns (numbers are converted explicitly)."""
    file_path = os.path.join(path, CONTRACT_FILES[exchange])
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip().str.lower()
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"{CONTRACT_FILES[exchange]} has no column {', '.join(missing)}")
    for column in REQUIRED_COLUMNS:
        df[column] = df[column].str.strip()
    return df


def _numbers(series, default=0.0):
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _rows(df, symbol, name, exchange, instrumenttype="EQ", expiry="", strike=0.0):
    """symtoken rows for ``df`` with the columns every segment shares."""
    out = pd.DataFrame(index=df.index)
    out["symbol"] = symbol
    out["brsymbol"] = df["trading_symbol"]
    out["name"] = name
    out["exchange"] = exchange
    out["brexchange"] = df["exchange"]
    out["token"] = df["exchange_token"]
    out["expiry"] = expiry
    out["strike"] = strike
    out["lotsize"] = _numbers(df["lot_size"], 0).astype("int64")
    out["instrumenttype"] = instrumenttype
    out["tick_size"] = _numbers(df["tick_size"]).astype(float)
    return out[SYMTOKEN_COLUMNS]


def _strip_series(trading_symbols, series, strippable):
    """The trading symbol without its own "-<series>" suffix, where allowed.

    Rows are taken in order of ``strippable`` (a list of masks, highest
    priority first). A row keeps its full trading symbol when the bare name is
    already a symbol (a row that is not stripped, or a stripped row of higher
    priority) or when two rows of its priority would claim the same name.
    """
    suffix = "-" + series
    ends = pd.Series(
        [t.endswith(s) and len(t) > len(s) for t, s in zip(trading_symbols, suffix, strict=True)],
        index=trading_symbols.index,
    )
    bare = pd.Series(
        [t[: -len(s)] if e else t for t, s, e in zip(trading_symbols, suffix, ends, strict=True)],
        index=trading_symbols.index,
    )
    symbols = trading_symbols.copy()
    candidates = [mask & ends for mask in strippable]
    any_candidate = np.logical_or.reduce([m.to_numpy() for m in candidates])
    taken = set(trading_symbols[~any_candidate])
    kept = 0
    for mask in candidates:
        claims = bare[mask].value_counts()
        strip = mask & bare.map(lambda b, c=claims: b not in taken and c.get(b, 0) == 1)
        symbols[strip] = bare[strip]
        taken.update(bare[strip])
        kept += int(mask.sum() - strip.sum())
    return symbols, kept


def _format_strike(strikes):
    """Strike as a symbol carries it: 25000, 192.5, 0.25."""
    return strikes.map(lambda s: f"{s:.4f}".rstrip("0").rstrip("."))


def _underlying_from_symbol(trading_symbols, expiry, tails):
    """The trading symbol without its expiry and strike suffix.

    The suffix is rebuilt from the row's own expiry, in the monthly form
    (26NOV + tail) and the weekly form (26N19 + tail), so a digit inside an
    underlying (SILVER100, SENSEX50) is never mistaken for part of the date.
    Returns "" where neither form matches.
    """
    year = expiry.dt.strftime("%y")
    month = expiry.dt.strftime("%b").str.upper()
    day = expiry.dt.strftime("%d")
    weekly_month = month.map(_WEEKLY_MONTH_CODES).fillna("")
    monthly = year + month + tails
    weekly = year + weekly_month + day + tails
    out = []
    for symbol, m, w in zip(trading_symbols, monthly, weekly, strict=True):
        base = ""
        for suffix in (m, w):
            if isinstance(suffix, str) and symbol.endswith(suffix) and len(symbol) > len(suffix):
                base = symbol[: -len(suffix)]
                break
        out.append(base)
    return pd.Series(out, index=trading_symbols.index)


def _derivatives(df, exchange):
    """Futures and options of one F&O file in the OpenAlgo format.

    Futures: [underlying][DDMMMYY]FUT. Options: [underlying][DDMMMYY][strike]
    [CE|PE]. option_type tells them apart: CE or PE for options, XX for
    futures. Anything else (MCX spot rows) is not a contract and is skipped.
    """
    option_type = df["option_type"].str.upper()
    is_option = option_type.isin(["CE", "PE"])
    is_future = option_type == "XX"
    df = df[is_option | is_future].copy()
    is_option, is_future = is_option[df.index], is_future[df.index]

    expiry = pd.to_datetime(df["expiry"], format="%d-%b-%Y", errors="coerce")
    expiry = expiry.where(expiry.dt.year > 1900)
    unreadable = expiry.isna()
    if unreadable.any():
        logger.warning(
            f"Skipping {int(unreadable.sum())} {exchange} contracts with no readable expiry"
        )

    # Options keep their strike; futures carry -0.01 and store 0 (the + 0.0
    # turns the -0.0 that where() can leave into 0.0).
    strike = _numbers(df["strike"]).where(is_option, 0.0) + 0.0
    strike_text = _format_strike(strike)
    tails = pd.Series(
        np.where(is_option, strike_text + option_type[df.index], "FUT"), index=df.index
    )

    underlying = df["company_name"]
    blank = underlying == ""
    if blank.any():
        # MCX ships no company_name: take the underlying from the symbol.
        parsed = _underlying_from_symbol(
            df.loc[blank, "trading_symbol"], expiry[blank], tails[blank]
        )
        underlying = underlying.copy()
        underlying[blank] = parsed

    unnamed = (underlying == "") & ~unreadable
    if unnamed.any():
        logger.warning(f"Skipping {int(unnamed.sum())} {exchange} contracts with no underlying")
    keep = ~unreadable & ~unnamed
    df, expiry, strike, strike_text, underlying = (
        df[keep],
        expiry[keep],
        strike[keep],
        strike_text[keep],
        underlying[keep],
    )
    is_option, option_type = is_option[keep], option_type[df.index]

    datepart = expiry.dt.strftime("%d%b%y").str.upper()
    symbol = pd.Series(
        np.where(
            is_option,
            underlying + datepart + strike_text + option_type,
            underlying + datepart + "FUT",
        ),
        index=df.index,
    )
    return _rows(
        df,
        symbol=symbol,
        name=underlying,
        exchange=exchange,
        instrumenttype=pd.Series(np.where(is_option, option_type, "FUT"), index=df.index),
        expiry=expiry.dt.strftime("%d-%b-%y").str.upper(),
        strike=strike.astype(float),
    )


def _nse_index_symbol(name):
    key = re.sub(r"[\s-]", "", name.upper())
    return NSE_INDEX_SYMBOLS.get(key, key)


def _bse_index_symbol(code):
    key = re.sub(r"\s", "", code.upper())
    return BSE_INDEX_SYMBOLS.get(key, key)


# --- per-exchange processing --------------------------------------------


def process_pocketful_nse_csv(path):
    """NSE cash rows (every series; indices are in process_pocketful_indices_csv)."""
    logger.info("Processing Pocketful NSE contract")
    df = _read_contract_csv(path, "NSE")
    df = df[df["segment"] != NSE_INDEX_SEGMENT]

    series = df["segment"].str.upper()
    # EQ first, so a stock listed in EQ and in another series keeps the bare
    # symbol on its EQ row.
    symbol, kept = _strip_series(
        df["trading_symbol"],
        df["segment"],
        [series == "EQ", series.isin(NSE_EQUITY_SERIES) & (series != "EQ")],
    )
    if kept:
        logger.info(f"NSE series suffix kept on {kept} symbols whose bare name is in use")
    name = df["company_name"].where(df["company_name"] != "", df["trading_symbol"])
    return _rows(df, symbol=symbol, name=name, exchange="NSE")


def process_pocketful_bse_csv(path):
    """BSE cash rows, without the BSE group suffix (RELIANCE-A -> RELIANCE)."""
    logger.info("Processing Pocketful BSE contract")
    df = _read_contract_csv(path, "BSE")
    df = df[df["segment"] != BSE_INDEX_SEGMENT]

    symbol, kept = _strip_series(
        df["trading_symbol"], df["segment"], [pd.Series(True, index=df.index)]
    )
    if kept:
        logger.info(f"BSE group suffix kept on {kept} symbols whose bare name is in use")
    name = df["company_name"].where(df["company_name"] != "", df["trading_symbol"])
    return _rows(df, symbol=symbol, name=name, exchange="BSE")


def process_pocketful_indices_csv(path):
    """NSE and BSE index rows, as NSE_INDEX and BSE_INDEX."""
    logger.info("Processing Pocketful index rows")
    frames = []

    nse = _read_contract_csv(path, "NSE")
    nse = nse[nse["segment"] == NSE_INDEX_SEGMENT]
    nse = nse[~nse["trading_symbol"].str.contains(NSE_TEST_INDEX)]
    if not nse.empty:
        frames.append(
            _rows(
                nse,
                symbol=nse["trading_symbol"].map(_nse_index_symbol),
                name=nse["trading_symbol"],
                exchange="NSE_INDEX",
            )
        )

    bse = _read_contract_csv(path, "BSE")
    bse = bse[bse["segment"] == BSE_INDEX_SEGMENT]
    if not bse.empty:
        frames.append(
            _rows(
                bse,
                symbol=bse["trading_symbol"].map(_bse_index_symbol),
                name=bse["trading_symbol"],
                exchange="BSE_INDEX",
            )
        )

    if not frames:
        return pd.DataFrame(columns=SYMTOKEN_COLUMNS)
    return pd.concat(frames)


def process_pocketful_nfo_csv(path):
    logger.info("Processing Pocketful NFO contract")
    return _derivatives(_read_contract_csv(path, "NFO"), "NFO")


def process_pocketful_bfo_csv(path):
    logger.info("Processing Pocketful BFO contract")
    return _derivatives(_read_contract_csv(path, "BFO"), "BFO")


def process_pocketful_mcx_csv(path):
    logger.info("Processing Pocketful MCX contract")
    return _derivatives(_read_contract_csv(path, "MCX"), "MCX")


def process_pocketful_contract(path):
    """Every symtoken row from the five files in ``path``.

    A (symbol, exchange) pair must name one instrument, or get_token() picks
    one of two at random. The real contract produces none; should a new file
    ever do so, the first row is kept and the rest are logged and dropped.
    """
    frames = [
        process_pocketful_nse_csv(path),
        process_pocketful_bse_csv(path),
        process_pocketful_indices_csv(path),
        process_pocketful_nfo_csv(path),
        process_pocketful_bfo_csv(path),
        process_pocketful_mcx_csv(path),
    ]
    rows = pd.concat(frames, ignore_index=True)
    rows = rows[(rows["symbol"] != "") & (rows["token"] != "")]

    duplicated = rows.duplicated(subset=["symbol", "exchange"], keep="first")
    if duplicated.any():
        sample = rows.loc[duplicated, ["exchange", "symbol"]].head(10).to_dict(orient="records")
        logger.warning(
            f"Dropped {int(duplicated.sum())} Pocketful rows whose symbol repeats on its "
            f"exchange, for example {sample}"
        )
        rows = rows[~duplicated]

    counts = rows["exchange"].value_counts().to_dict()
    logger.info(f"Pocketful contract processed: {len(rows)} instruments {counts}")
    return rows.reset_index(drop=True)


def master_contract_download():
    """Download the contract, rebuild symtoken from it and tell the UI.

    Runs in a background thread after login. A failure leaves the stored
    contract as it was and is raised again, because the caller
    (utils/auth_utils) counts a normal return as success.
    """
    logger.info("Downloading Pocketful Master Contract")
    work_dir = tempfile.mkdtemp(prefix="pocketful_contract_")
    try:
        download_pocketful_contract(work_dir)
        token_df = process_pocketful_contract(work_dir)
        replace_symtoken_table(token_df)
        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )
    except Exception:
        logger.exception("Pocketful master contract download failed")
        try:
            socketio.emit(
                "master_contract_download", {"status": "error", "message": FAILED_MESSAGE}
            )
        except Exception:
            logger.exception("Could not send the master contract error to the UI")
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
