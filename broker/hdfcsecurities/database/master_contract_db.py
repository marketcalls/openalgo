# broker/hdfcsecurities/database/master_contract_db.py
#
# Builds the OpenAlgo SymToken table from HDFC Securities InvestRight's
# Security Master.
#
# Source (public, NO auth required -- no api_key, no Authorization, no
# User-Agent):
#   GET https://developer.hdfcsec.com/oapi/v1/security-master
#     -> a plain CSV (~117.5k rows, ~8 MB), Content-Disposition
#        "ir-security-master.csv"
#
# CSV columns (verified against the live file):
#   exchange, security_id, instrument_segment, expiry_date, strike_price,
#   option_type, lot_size, tick_size, close_price, exch_security_id,
#   symbol_name, underline_symbol, open_price
#
# Facts established from the live file (do NOT re-derive from the docs):
#   - `exchange` is only NSE / BSE / MCX. OpenAlgo's NFO / BFO / CDS come from
#     `instrument_segment`, and indices are NOT flagged at all -- they are
#     EQUITY rows whose exchange token falls in a reserved band (NSE
#     26000-26999, BSE below 1000). NSE reuses 27000+ for new equity listings,
#     so the NSE band must be bounded on BOTH sides.
#   - `symbol_name` is already the clean exchange trading symbol, special
#     characters intact: "M&M", "BAJAJ-AUTO", "NIFTY". There is no series
#     suffix to strip, unlike HDFC Sky's CompactScrip.
#   - `symbol_name` is EMPTY on 3 NSE and 2164 BSE cash rows. 987 of the BSE
#     blanks are recoverable from the NSE row that shares the same
#     `security_id` (both exchanges use the same broker code, e.g.
#     MAHMAHEQNR -> "M&M"); the rest fall back to `security_id`.
#   - `symbol_name` is NOT unique within a cash exchange: 671 NSE rows (228
#     names) and 51 BSE rows (21 names) collide, because bonds, NCDs and MF
#     units are listed under the issuer's display name -- "SBIN" is both the
#     equity and three State Bank bonds. `_cash_rank` picks the real equity
#     (see below); verified to recover the correct row for all 208 F&O
#     underlyings.
#   - `exch_security_id` is sometimes the literal "DUMMY<token>" on MF/NCD
#     rows. Those cannot be quoted or streamed and are dropped.
#   - Derivative rows carry the underlying in `symbol_name` already in
#     OpenAlgo form (NIFTY, BANKNIFTY, M&M, GOLD), so no suffix-stripping is
#     needed; the resulting OpenAlgo symbols are collision-free across all
#     113k derivative rows.
#   - `security_id` is the order-placement identifier and `exch_security_id`
#     the market-data token. They differ on cash rows (BHAENGEQNR / 419) and
#     on BSE derivatives ("B" prefix: B826625 / 826625).
#   - `strike_price` is unscaled rupees; futures carry the placeholders -0.01
#     (NSE equity/index), -0.0000001 (currency) or 0 (MCX).
#   - `expiry_date` is "YYYY-MM-DD", empty on cash/underlying rows.
#
# Processing is fully vectorized (pandas column ops, no iterrows).

import io
import os

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.hdfcsecurities.api.baseurl import SECURITY_MASTER_URL, USER_AGENT
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
    """Clear the table WITHOUT committing.

    The delete and the reinsert deliberately share one transaction (see
    replace_symtoken_table): committing here would destroy the working master
    before the replacement is known to be insertable.
    """
    logger.info("Clearing Symtoken Table")
    SymToken.query.delete()


def copy_from_dataframe(df):
    """Insert the processed rows and commit. Raises if the insert fails.

    The failure must propagate: master_contract_download reports success to the
    UI on return, and the previous master has already been deleted inside this
    transaction, so swallowing the error would leave every HDFC Securities
    symbol lookup dead behind a success toast.
    """
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient="records")

    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered = [row for row in data_dict if row["token"] not in existing_tokens]

    try:
        if filtered:
            db_session.bulk_insert_mappings(SymToken, filtered)
            logger.info(f"Bulk insert prepared with {len(filtered)} new records.")
        else:
            logger.info("No new records to insert.")
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()
        raise


def replace_symtoken_table(df):
    """Swap the master contract atomically.

    The delete and the insert run in a single transaction, so a failure at any
    point rolls back to the previous master rather than leaving the table
    empty.
    """
    if df is None or df.empty:
        raise ValueError(
            "HDFC Securities security master produced no usable instruments; "
            "keeping the existing master contract."
        )
    try:
        delete_symtoken_table()
        copy_from_dataframe(df)
    except Exception:
        db_session.rollback()
        raise


# --- download -----------------------------------------------------------


def download_security_master():
    """Fetch the Security Master CSV into a DataFrame.

    The endpoint is public, which is why the master contract can be rebuilt
    even when the broker session has expired.
    """
    client = get_httpx_client()
    # Explicit generous timeout: the CSV is ~8 MB and served uncompressed.
    response = client.get(
        SECURITY_MASTER_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=180,
        follow_redirects=True,
    )
    response.raise_for_status()

    # dtype=str: skip pandas type inference entirely (mixed-type columns like
    # strike_price/tick_size would otherwise warn). Numerics are converted
    # explicitly below.
    df = pd.read_csv(io.BytesIO(response.content), dtype=str, low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    logger.info(f"Downloaded HDFC Securities security master: {len(df)} rows")
    return df


# --- segment / exchange mapping -----------------------------------------

# (broker exchange, instrument_segment) -> OpenAlgo exchange. Cash rows are
# resolved separately because their index/non-index split is token-based.
_SEGMENT_EXCHANGE = {
    ("NSE", "FUTIDX"): "NFO",
    ("NSE", "OPTIDX"): "NFO",
    ("NSE", "FUTSTK"): "NFO",
    ("NSE", "OPTSTK"): "NFO",
    ("NSE", "FUTCUR"): "CDS",
    ("NSE", "OPTCUR"): "CDS",
    ("BSE", "FUTIDX"): "BFO",
    ("BSE", "OPTIDX"): "BFO",
    ("MCX", "FUTCOM"): "MCX",
    ("MCX", "OPTFUT"): "MCX",
    ("MCX", "FUTIDX"): "MCX",
    ("MCX", "OPTIDX"): "MCX",
}

_CASH_SEGMENT = "EQUITY"

# Reserved index token bands. NSE indices occupy 26000-26999 exactly (the next
# equity token above the band is 27008, the last below it is 25996), and BSE
# indices sit below 1000 while BSE scrip codes are 5-6 digits.
_NSE_INDEX_TOKEN_RANGE = (26000, 26999)
_BSE_INDEX_TOKEN_MAX = 999

# InvestRight index display names that differ from the OpenAlgo symbol, plus
# the three NSE index rows that ship with an empty `symbol_name` and must be
# named from their `security_id`. Anything unlisted keeps its own name, so a
# newly added index is addressable the moment HDFC lists it.
_INDEX_SYMBOL_OVERRIDES = {
    "NIFTYMID50": "NIFTYMIDCAP50",
    "MINIFTYEQ": "MINIFTY",
    "DEFTYEQ": "DEFTY",
    "CNX100EQ": "NIFTY100",
}


def classify_index_symbol(display_name, security_id):
    """InvestRight index row -> the OpenAlgo index symbol."""
    key = "".join(str(display_name).upper().split())
    if not key:
        key = "".join(str(security_id).upper().split())
    return _INDEX_SYMBOL_OVERRIDES.get(key, key)


# --- cash-row ranking ---------------------------------------------------
#
# When several cash rows share a display name, exactly one of them is the
# tradable equity and the others are the issuer's bonds, NCDs or MF units.
# InvestRight encodes the instrument class in `security_id`:
#
#   <6 chars>EQNR / EQTT   equity, rolling / trade-to-trade   (STABANEQNR)
#   ...EQNR / ...EQTT      equity, longer broker code         (IDFCFIREQNR)
#   plain code             newer listings, no class suffix    (SWIGGY, IREDA)
#   ...MFNR, ...N<d>NR     MF units, NCDs, bonds              (STABANN6NR)
#
# Lower rank wins. Verified against every F&O underlying: the rank rule
# recovers the exact `underline_symbol` the derivative rows expect for all 208
# of them.

_EQUITY_SUFFIXES = ("EQNR", "EQTT")


def _cash_rank(security_id):
    code = str(security_id).upper()
    if len(code) == 10 and code.endswith(_EQUITY_SUFFIXES):
        return 0
    if code.endswith(_EQUITY_SUFFIXES):
        return 1
    # Bond / NCD / MF codes always end in "NR" or "TT" after a class letter;
    # a plain listing code does not.
    if not code.endswith(("NR", "TT")):
        return 2
    return 3


def _format_strike_series(strike):
    """Render strikes the way symbols embed them: int when whole (4050), else
    decimal (126.25)."""
    whole = strike == strike.astype("int64")
    return pd.Series(
        np.where(whole, strike.astype("int64").astype(str), strike.astype(str)),
        index=strike.index,
    )


def _tick_size_series(raw):
    """InvestRight tick sizes are paise when integral and rupees when decimal.

    "1" -> 0.01, "5" -> 0.05, "100" -> 1.00, but ".0025" is already the
    currency tick of 0.0025. The paise reading reproduces NSE's tiered cash
    tick regime exactly (IDFCFIRSTB at 86 -> 0.01, ANGELONE at 300 -> 0.05,
    M&M at 3433 -> 0.10, BAJAJ-AUTO at 11600 -> 1.00) and MCX's contract ticks
    (GOLD -> 1.00, SILVERM -> 0.50), so it is applied uniformly.
    """
    value = pd.to_numeric(raw, errors="coerce").fillna(0.0)
    is_decimal = raw.str.contains(".", regex=False)
    return value.where(is_decimal, value / 100.0)


# --- parsing ------------------------------------------------------------


def process_security_master(df):
    """Transform the Security Master DataFrame into SymToken rows."""
    logger.info("Processing HDFC Securities security master")

    df = df.fillna("")
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()

    brexchange = df["exchange"].str.upper()
    segment = df["instrument_segment"].str.upper()
    security_id = df["security_id"]
    option_type = df["option_type"].str.upper()

    # Drop the MF/NCD placeholder rows: their token is "DUMMY<n>", so they can
    # neither be quoted nor streamed.
    token = df["exch_security_id"]
    token_num = pd.to_numeric(token, errors="coerce")
    usable = token_num.notna() & (security_id != "")

    # --- exchange --------------------------------------------------------
    exchange = pd.Series(
        [_SEGMENT_EXCHANGE.get((e, s), "") for e, s in zip(brexchange, segment, strict=True)],
        index=df.index,
    )
    is_cash = segment == _CASH_SEGMENT
    exchange = exchange.mask(is_cash, brexchange)

    low, high = _NSE_INDEX_TOKEN_RANGE
    is_nse_index = is_cash & (brexchange == "NSE") & token_num.between(low, high)
    is_bse_index = is_cash & (brexchange == "BSE") & (token_num <= _BSE_INDEX_TOKEN_MAX)
    exchange = exchange.mask(is_nse_index, "NSE_INDEX").mask(is_bse_index, "BSE_INDEX")
    is_index = is_nse_index | is_bse_index

    # Unmapped segments (COM commodity underlyings, UNDCUR currency
    # underlyings) are not tradable and carry no OpenAlgo exchange.
    usable &= exchange != ""

    # --- expiry: "2026-08-11" -> "11-AUG-26"; blank on cash --------------
    expiry_dt = pd.to_datetime(df["expiry_date"], format="%Y-%m-%d", errors="coerce")
    expiry = expiry_dt.dt.strftime("%d-%b-%y").str.upper().fillna("")
    expiry_compact = expiry.str.replace("-", "", regex=False)

    # --- numerics --------------------------------------------------------
    # Futures carry placeholder strikes (-0.01 / -1e-7 / 0); clip to 0 (the
    # "+ 0.0" normalizes the negative zero clip() leaves behind).
    strike = pd.to_numeric(df["strike_price"], errors="coerce").fillna(0.0).clip(lower=0.0) + 0.0
    strike_str = _format_strike_series(strike)
    tick_size = _tick_size_series(df["tick_size"])
    # A handful of MF rows carry the sentinel lot size 999999999.
    lotsize = pd.to_numeric(df["lot_size"], errors="coerce").fillna(0).astype("int64")
    lotsize = lotsize.where((lotsize > 0) & (lotsize < 100_000_000), 1)

    is_option = option_type.isin(["CE", "PE"])
    is_future = (~is_option) & (~is_cash) & (expiry != "")
    is_deriv = is_option | is_future

    # --- cash display names ---------------------------------------------
    # BSE leaves `symbol_name` empty on 2164 rows; the NSE listing of the same
    # broker code carries the real trading symbol (MAHMAHEQNR -> "M&M").
    symbol_name = df["symbol_name"]
    nse_names = (
        df.loc[is_cash & (brexchange == "NSE") & (symbol_name != "")]
        .drop_duplicates(subset=["security_id"], keep="first")
        .set_index("security_id")["symbol_name"]
    )
    borrowed = security_id.map(nse_names).fillna("")
    cash_symbol = symbol_name.where(symbol_name != "", borrowed)
    cash_symbol = cash_symbol.where(cash_symbol != "", security_id)

    # --- symbol ----------------------------------------------------------
    symbol = cash_symbol.copy()
    symbol = symbol.mask(is_future, symbol_name + expiry_compact + "FUT")
    symbol = symbol.mask(is_option, symbol_name + expiry_compact + strike_str + option_type)
    if is_index.any():
        symbol = symbol.mask(
            is_index,
            pd.Series(
                [
                    classify_index_symbol(display, code)
                    for display, code in zip(symbol_name, security_id, strict=True)
                ],
                index=df.index,
            ),
        )

    # OpenAlgo stores indices as instrumenttype "EQ" (the NSE_INDEX/BSE_INDEX
    # exchange is what distinguishes them). There is NO "INDEX" type.
    instrumenttype = pd.Series("EQ", index=df.index)
    instrumenttype = instrumenttype.mask(is_future, "FUT").mask(is_option, option_type)

    # `name`: the underlying for derivatives, the trading symbol otherwise.
    name = symbol.where(~is_deriv, symbol_name)

    out = pd.DataFrame(
        {
            "symbol": symbol,
            "brsymbol": security_id,
            "name": name,
            "exchange": exchange,
            "brexchange": brexchange,
            "token": token,
            "expiry": expiry,
            "strike": strike,
            "lotsize": lotsize,
            "instrumenttype": instrumenttype,
            "tick_size": tick_size,
            # Sort key only -- dropped before the frame is returned.
            "_rank": pd.Series(
                np.where(is_deriv, 0, [_cash_rank(code) for code in security_id]),
                index=df.index,
            ),
        }
    )
    out = out[usable & (out["symbol"] != "")]

    # A duplicate (symbol, exchange) would make get_token() ambiguous. On cash
    # exchanges the collisions are bonds/NCDs listed under the issuer's display
    # name, so keep the best-ranked row rather than whichever came first.
    before = len(out)
    out = (
        out.sort_values("_rank", kind="stable")
        .drop_duplicates(subset=["symbol", "exchange"], keep="first")
        .drop(columns=["_rank"])
        .sort_index()
    )
    if before != len(out):
        logger.info(f"Dropped {before - len(out)} duplicate (symbol, exchange) rows")

    logger.info(f"Processed {len(out)} HDFC Securities instruments")
    return out.reset_index(drop=True)


def master_contract_download():
    """Entry point (called post-login). Downloads + rebuilds the SymToken table."""
    logger.info("Downloading HDFC Securities Master Contract")
    try:
        raw = download_security_master()
        token_df = process_security_master(raw)

        replace_symtoken_table(token_df)

        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )
    except Exception as e:
        logger.exception(f"HDFC Securities master contract download failed: {e}")
        try:
            socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
        except Exception as emit_error:
            # Never let the notification displace the real cause.
            logger.debug(f"Could not emit master contract error event: {emit_error}")
        # Re-raise: utils/auth_utils.async_master_contract_download decides
        # success purely by "no exception was raised", so returning normally
        # here would mark the broker ready and kick off symbol cache loading
        # against a master that was never refreshed.
        raise
    finally:
        # Runs in a background thread, so the Flask app teardown will not
        # release the scoped session for us.
        db_session.remove()


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
