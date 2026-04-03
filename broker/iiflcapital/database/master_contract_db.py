import os
import re
from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.iiflcapital.baseurl import BASE_URL
from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
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

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


SEGMENT_TO_EXCHANGE = {
    "NSEEQ": "NSE",
    "BSEEQ": "BSE",
    "NSEFO": "NFO",
    "BSEFO": "BFO",
    "NSECURR": "CDS",
    "BSECURR": "BCD",
    "NSECOMM": "MCX",
    "MCXCOMM": "MCX",
    "NCDEXCOMM": "MCX",
    "INDICES": "NSE_INDEX",
}

SEGMENTS = [
    "NSEEQ",
    "BSEEQ",
    "NSEFO",
    "BSEFO",
    "NSECURR",
    "BSECURR",
    "NSECOMM",
    "MCXCOMM",
    "NCDEXCOMM",
    "INDICES",
]


# Common NSE/BSE series suffixes used in broker tradingsymbols.
# OpenAlgo cash-equity symbol should be base symbol (e.g., INFY, RELIANCE).
_CASH_SERIES_SUFFIX_RE = re.compile(
    r"-(EQ|BE|BZ|BL|BT|SM|ST|TS|TB|T0|T1|T2|T3|T4)$", re.IGNORECASE
)

_DERIVATIVE_INSTRUMENT_RE = re.compile(
    r"^(.+?)(\d{2}[A-Z]{3}\d{2})(\d+(?:\.\d+)?)?(FUT|CE|PE)$", re.IGNORECASE
)

_FUTURE_TYPES = {
    "FUT",
    "FUTIDX",
    "FUTSTK",
    "FUTCUR",
    "FUTCOM",
    "FUTIRT",
    "FUTIRC",
    "FUTURE",
    "XX",
    "1",
}

_OPTION_TYPES = {
    "OPT",
    "OPTIDX",
    "OPTSTK",
    "OPTCUR",
    "OPTFUT",
    "OPTIRC",
    "OPTION",
}

_OPTION_TYPE_TO_STANDARD = {
    "3": "CE",
    "4": "PE",
    "CE": "CE",
    "PE": "PE",
    "CALL": "CE",
    "PUT": "PE",
}

_NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "NIFTYNXT50",
    "FINNIFTY",
    "BANKNIFTY",
    "MIDCPNIFTY",
    "INDIAVIX",
    "NIFTY100",
    "NIFTY200",
    "NIFTY500",
    "NIFTYIT",
    "NIFTYAUTO",
    "NIFTYFMCG",
    "NIFTYENERGY",
    "NIFTYMETAL",
    "NIFTYPHARMA",
    "NIFTYREALTY",
    "NIFTYPSE",
    "NIFTYPVTBANK",
    "NIFTYPSUBANK",
    "NIFTYMEDIA",
}

_BSE_INDEX_SYMBOLS = {
    "SENSEX",
    "BANKEX",
    "SENSEX50",
    "BSE100",
    "BSE200",
    "BSE500",
    "BSEAUTO",
    "BSEENERGY",
    "BSEMETAL",
    "BSEPOWER",
    "BSEPSU",
    "BSEMIDCAP",
    "BSESMALLCAP",
    "BSEHEALTHCARE",
    "BSETECK",
    "BSETELECOM",
}

_INDEX_SYMBOL_MAP = {
    # NSE canonical (as per openalgo_symbol_format.md)
    "NIFTY": "NIFTY",
    "NIFTYNXT50": "NIFTYNXT50",
    "FINNIFTY": "FINNIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "INDIAVIX": "INDIAVIX",
    "NIFTY100": "NIFTY100",
    "NIFTY200": "NIFTY200",
    "NIFTY500": "NIFTY500",
    "NIFTYIT": "NIFTYIT",
    "NIFTYAUTO": "NIFTYAUTO",
    "NIFTYFMCG": "NIFTYFMCG",
    "NIFTYENERGY": "NIFTYENERGY",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYPHARMA": "NIFTYPHARMA",
    "NIFTYREALTY": "NIFTYREALTY",
    "NIFTYPSE": "NIFTYPSE",
    "NIFTYPVTBANK": "NIFTYPVTBANK",
    "NIFTYPSUBANK": "NIFTYPSUBANK",
    "NIFTYMEDIA": "NIFTYMEDIA",
    # NSE aliases
    "NIFTY50": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYFINANCIALSERVICES": "FINNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMID50": "NIFTYMIDCAP50",
    "NIFTYINDIAVIX": "INDIAVIX",
    # BSE canonical (as per openalgo_symbol_format.md)
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SENSEX50": "SENSEX50",
    "BSE100": "BSE100",
    "BSE200": "BSE200",
    "BSE500": "BSE500",
    "BSEAUTO": "BSEAUTO",
    "BSEENERGY": "BSEENERGY",
    "BSEMETAL": "BSEMETAL",
    "BSEPOWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "BSEMIDCAP": "BSEMIDCAP",
    "BSESMALLCAP": "BSESMALLCAP",
    "BSEHEALTHCARE": "BSEHEALTHCARE",
    "BSETECK": "BSETECK",
    "BSETELECOM": "BSETELECOM",
    # BSE aliases
    "SENSEX30": "SENSEX",
    "SNSX50": "SENSEX50",
    "100": "BSE100",
    "200": "BSE200",
    "500": "BSE500",
    "AUTO": "BSEAUTO",
    "ENERGY": "BSEENERGY",
    "METAL": "BSEMETAL",
    "MIDCAP": "BSEMIDCAP",
    "POWER": "BSEPOWER",
    "PSU": "BSEPSU",
    "HC": "BSEHEALTHCARE",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "S&PBSESENSEX": "SENSEX",
    "S&PBSEBANKEX": "BANKEX",
    "S&PBSESENSEX50": "SENSEX50",
    "S&PBSE100": "BSE100",
    "S&PBSE200": "BSE200",
    "S&PBSE500": "BSE500",
    "S&PBSEAUTO": "BSEAUTO",
    "S&PBSEENERGY": "BSEENERGY",
    "S&PBSEMETAL": "BSEMETAL",
    "S&PBSEPOWER": "BSEPOWER",
    "S&PBSEPSU": "BSEPSU",
    "S&PBSEMIDCAP": "BSEMIDCAP",
    "S&PBSESMALLCAP": "BSESMALLCAP",
    "S&PBSEHEALTHCARE": "BSEHEALTHCARE",
    "S&PBSETECK": "BSETECK",
    "S&PBSETELECOM": "BSETELECOM",
}


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
    filtered_data = [row for row in data_dict if row["token"] not in existing_tokens]

    if not filtered_data:
        logger.info("No new records to insert")
        return

    try:
        db_session.bulk_insert_mappings(SymToken, filtered_data)
        db_session.commit()
        logger.info(f"Inserted {len(filtered_data)} records")
    except Exception as exc:
        db_session.rollback()
        logger.exception(f"Bulk insert failed: {exc}")
        raise


def _to_float(value, default=0.0):
    try:
        if value in (None, "", "-"):
            return default
        parsed = float(value)
        if not np.isfinite(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0):
    try:
        if value in (None, "", "-"):
            return default
        parsed = float(value)
        if not np.isfinite(parsed):
            return default
        return int(parsed)
    except (TypeError, ValueError):
        return default


def _clean_text(value):
    if value is None:
        return ""

    cleaned = str(value).strip()
    if cleaned.lower() in ("", "nan", "none", "nat"):
        return ""

    return cleaned


def _first(row, lower_row, keys, default=""):
    for key in keys:
        value = row.get(key)
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned

        lower_value = lower_row.get(str(key).lower())
        lower_cleaned = _clean_text(lower_value)
        if lower_cleaned:
            return lower_cleaned

    return default


def _normalize_expiry(value):
    if value in (None, "", "-"):
        return ""

    try:
        expiry = pd.to_datetime(value, errors="coerce")
        if pd.isna(expiry):
            return ""
        return expiry.strftime("%d-%b-%y").upper()
    except Exception:
        return ""


def _extract_rows(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in ("result", "data", "contracts", "instruments"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for sub_key in ("data", "contracts", "instruments", "rows"):
                sub_value = value.get(sub_key)
                if isinstance(sub_value, list):
                    return sub_value

    if payload.get("instrumentId") or payload.get("tradingSymbol"):
        return [payload]

    return []


def _extract_csv_rows(csv_text):
    if not csv_text or not str(csv_text).strip():
        return []

    try:
        csv_df = pd.read_csv(StringIO(csv_text), dtype=str, low_memory=False)
    except Exception as exc:
        logger.warning(f"Failed to parse contract CSV response: {exc}")
        return []

    if csv_df.empty:
        return []

    csv_df = csv_df.replace({np.nan: None})
    rows = csv_df.to_dict(orient="records")
    return [row for row in rows if isinstance(row, dict)]


def _extract_symbol(row, lower_row):
    return _first(
        row,
        lower_row,
        (
            "tradingSymbol",
            "tradingsymbol",
            "symbol",
            "displayName",
            "instrumentName",
            "name",
            "formattedInstrumentName",
            "displayname",
        ),
    )


def _extract_name(row, lower_row, fallback):
    return _first(
        row,
        lower_row,
        (
            "name",
            "companyName",
            "description",
            "formattedInstrumentName",
            "displayName",
            "underlyingSymbol",
            "underlying",
            "underlyingName",
        ),
        default=fallback,
    )


def _extract_token(row, lower_row, segment, brsymbol):
    # IIFL Capital contract-file rule: NCDEXCOMM uses tradingSymbol as instrumentId.
    if segment == "NCDEXCOMM":
        return _first(
            row,
            lower_row,
            ("tradingSymbol", "tradingsymbol", "symbol", "displayName", "instrumentName"),
            default=brsymbol,
        )

    return _first(
        row,
        lower_row,
        (
            "instrumentId",
            "token",
            "exchangeInstrumentID",
            "exchangeInstrumentId",
            "instrumentToken",
            "securityId",
            "securityID",
            "id",
        ),
    )


def _normalize_cash_equity_symbol(symbol: str, exchange: str) -> str:
    """
    Normalize cash-equity symbol to OpenAlgo format.

    Example:
    - INFY-EQ -> INFY
    - RELIANCE-EQ -> RELIANCE
    """
    if not symbol:
        return ""

    cleaned = _clean_text(symbol).upper()
    if exchange in ("NSE", "BSE"):
        cleaned = _CASH_SERIES_SUFFIX_RE.sub("", cleaned)

    return cleaned.replace(" ", "")


def _format_strike_for_symbol(strike_value) -> str:
    strike = _to_float(strike_value, 0.0)
    if strike <= 0:
        return ""

    if float(strike).is_integer():
        return str(int(strike))

    return f"{strike:.6f}".rstrip("0").rstrip(".")


def _normalize_index_symbol(value: str) -> str:
    raw = _clean_text(value).upper()
    if not raw:
        return ""

    # Follow Angel/Fyers style cleanup before applying common-index aliases.
    # Keep fallback as cleaned broker symbol for unmapped values.
    fallback = raw.replace(" ", "").replace("-", "")

    lookup = fallback
    if lookup.startswith("S&P"):
        lookup = lookup[3:]

    return _INDEX_SYMBOL_MAP.get(lookup, fallback)


def _infer_instrument_type_from_symbol(brsymbol: str) -> str:
    broker_symbol = _clean_text(brsymbol).upper()
    if broker_symbol.endswith("CE"):
        return "CE"
    if broker_symbol.endswith("PE"):
        return "PE"
    if broker_symbol.endswith("FUT"):
        return "FUT"
    return ""


def _build_expiry_suffix_candidates(expiry: str) -> list[str]:
    normalized_expiry = _clean_text(expiry)
    if not normalized_expiry:
        return []

    try:
        expiry_ts = pd.to_datetime(normalized_expiry, errors="coerce")
    except Exception:
        return []

    if pd.isna(expiry_ts):
        return []

    day = int(expiry_ts.day)
    month = int(expiry_ts.month)
    year = int(expiry_ts.year)
    yy = year % 100
    month_abbr = expiry_ts.strftime("%b").upper()

    candidates = [
        f"{day:02d}{month_abbr}{yy:02d}",
        f"{day:02d}{month_abbr}{year:04d}",
        f"{yy:02d}{month_abbr}",
        f"{yy:02d}{month_abbr}{day:02d}",
        f"{yy:02d}{month}{day:02d}",
        f"{yy:02d}{month:02d}{day:02d}",
        f"{yy:02d}{month}{day}",
        f"{yy:02d}{month:02d}{day}",
    ]

    # Remove duplicates while preserving order.
    unique = []
    seen = set()
    for value in candidates:
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _strip_derivative_contract_suffix(
    candidate: str, expiry: str, strike: float, instrument_type: str
) -> str:
    text = _clean_text(candidate).upper().replace(" ", "")
    if not text:
        return ""

    inferred_type = _clean_text(instrument_type).upper() or _infer_instrument_type_from_symbol(text)
    if inferred_type in ("FUT", "CE", "PE") and text.endswith(inferred_type):
        text = text[: -len(inferred_type)]

    if inferred_type in ("CE", "PE"):
        strike_text = _format_strike_for_symbol(strike)
        strike_variants = [strike_text] if strike_text else []
        if strike_text and "." in strike_text:
            strike_variants.append(strike_text.replace(".", ""))

        for strike_variant in strike_variants:
            if strike_variant and text.endswith(strike_variant):
                text = text[: -len(strike_variant)]
                break

    for expiry_suffix in _build_expiry_suffix_candidates(expiry):
        if text.endswith(expiry_suffix):
            text = text[: -len(expiry_suffix)]
            break

    return text


def _normalize_instrument_type(raw_instrument_type: str, option_type: str, exchange: str) -> str:
    """Normalize instrument type values to OpenAlgo standard."""
    instrument = _clean_text(raw_instrument_type).upper()
    option = _clean_text(option_type).upper()

    if option in _OPTION_TYPE_TO_STANDARD:
        return _OPTION_TYPE_TO_STANDARD[option]
    if option in _FUTURE_TYPES:
        return "FUT"

    if instrument in ("CE", "PE", "FUT"):
        return instrument
    if instrument in _OPTION_TYPES and option in _OPTION_TYPE_TO_STANDARD:
        return _OPTION_TYPE_TO_STANDARD[option]
    if instrument in _FUTURE_TYPES:
        return "FUT"

    if exchange in ("NSE", "BSE") and instrument in ("", "0", "E", "EQ"):
        return "EQ"
    if exchange in ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX"):
        return "INDEX"

    return instrument


def _extract_underlying_symbol(row, lower_row, brsymbol, name, expiry, strike, instrument_type):
    explicit = _first(
        row,
        lower_row,
        ("underlyingSymbol", "underlying", "underlyingName"),
    )
    if explicit:
        normalized_explicit = _strip_derivative_contract_suffix(
            explicit, expiry=expiry, strike=strike, instrument_type=instrument_type
        )
        if normalized_explicit:
            return normalized_explicit
        return explicit

    for candidate in (
        brsymbol,
        _first(row, lower_row, ("name", "symbol", "formattedInstrumentName", "displayName")),
    ):
        stripped = _strip_derivative_contract_suffix(
            candidate, expiry=expiry, strike=strike, instrument_type=instrument_type
        )
        if stripped:
            return stripped

    broker_symbol = _clean_text(brsymbol).upper()
    parsed = _DERIVATIVE_INSTRUMENT_RE.match(broker_symbol)
    if parsed:
        return parsed.group(1)

    return name or brsymbol


def _build_openalgo_symbol(
    exchange: str,
    instrument_type: str,
    base_symbol: str,
    brsymbol: str,
    expiry: str,
    strike: float,
):
    normalized_base = _normalize_cash_equity_symbol(base_symbol or brsymbol, exchange)
    compact_expiry = _clean_text(expiry).replace("-", "")

    if exchange in ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX"):
        return _normalize_index_symbol(normalized_base or brsymbol)

    if instrument_type == "FUT" and compact_expiry:
        return f"{normalized_base}{compact_expiry}FUT"

    if instrument_type in ("CE", "PE") and compact_expiry:
        strike_text = _format_strike_for_symbol(strike)
        if not strike_text:
            return _normalize_cash_equity_symbol(brsymbol, exchange)
        return f"{normalized_base}{compact_expiry}{strike_text}{instrument_type}"

    return _normalize_cash_equity_symbol(brsymbol, exchange)


def _resolve_exchange(segment, row, lower_row, brsymbol, name):
    if segment != "INDICES":
        return SEGMENT_TO_EXCHANGE.get(segment, segment)

    exchange_hint = _first(
        row,
        lower_row,
        ("exchange", "segment", "exchangeSegment", "market", "marketSegment"),
    ).upper()
    if "BSE" in exchange_hint:
        return "BSE_INDEX"
    if "MCX" in exchange_hint:
        return "MCX_INDEX"

    symbol_hint = _normalize_index_symbol(brsymbol or name)
    if symbol_hint in _BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if symbol_hint in _NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"

    return "NSE_INDEX"


def _parse_segment_data(segment, rows):
    records = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        lower_row = {str(key).lower(): value for key, value in row.items()}
        brsymbol = _extract_symbol(row, lower_row)
        name = _extract_name(row, lower_row, brsymbol)
        exchange = _resolve_exchange(segment, row, lower_row, brsymbol, name)
        token = _extract_token(row, lower_row, segment, brsymbol)

        if not token or not brsymbol:
            continue

        raw_instrument_type = _first(
            row,
            lower_row,
            ("instrumentType", "instrument", "series", "securityType", "type"),
        )
        option_type = _first(row, lower_row, ("optionType", "option_type"))
        option_type_upper = _clean_text(option_type).upper()
        instrument_type = _normalize_instrument_type(raw_instrument_type, option_type, exchange)

        inferred_instrument_type = _infer_instrument_type_from_symbol(brsymbol)
        if inferred_instrument_type in ("FUT", "CE", "PE"):
            instrument_type = inferred_instrument_type

        expiry = _normalize_expiry(
            _first(
                row,
                lower_row,
                (
                    "expiry",
                    "expiryDate",
                    "contractExpiry",
                    "contractExpiration",
                    "expirationDate",
                    "maturityDate",
                ),
            )
        )
        strike = _to_float(_first(row, lower_row, ("strike", "strikePrice", "strike_price")), 0.0)
        lotsize = _to_int(_first(row, lower_row, ("lotSize", "lotsize", "lot_size", "qtyLot")), 0)
        tick_size = _to_float(_first(row, lower_row, ("tickSize", "tick_size", "tick")), 0.0)

        if exchange in ("NSE", "BSE") and instrument_type not in ("FUT", "CE", "PE"):
            instrument_type = "EQ"
            expiry = ""
            strike = 0.0

        if exchange in ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX"):
            instrument_type = "INDEX"
            expiry = ""
            strike = 0.0

        if exchange in ("NFO", "BFO", "CDS", "BCD", "MCX") and instrument_type not in (
            "FUT",
            "CE",
            "PE",
        ):
            if strike > 0 and option_type_upper in _OPTION_TYPE_TO_STANDARD:
                instrument_type = _OPTION_TYPE_TO_STANDARD[option_type_upper]
            elif strike <= 0:
                instrument_type = "FUT"

        base_symbol = _extract_underlying_symbol(
            row=row,
            lower_row=lower_row,
            brsymbol=brsymbol,
            name=name,
            expiry=expiry,
            strike=strike,
            instrument_type=instrument_type,
        )
        normalized_symbol = _build_openalgo_symbol(
            exchange=exchange,
            instrument_type=instrument_type,
            base_symbol=base_symbol,
            brsymbol=brsymbol,
            expiry=expiry,
            strike=strike,
        )
        normalized_name = _normalize_cash_equity_symbol(base_symbol or name, exchange)

        if instrument_type not in ("FUT", "CE", "PE"):
            normalized_name = _normalize_cash_equity_symbol(name or brsymbol, exchange)
        if instrument_type == "INDEX":
            normalized_name = _normalize_index_symbol(name or brsymbol)

        record = {
            "symbol": normalized_symbol,
            "brsymbol": brsymbol,
            "name": normalized_name,
            "exchange": exchange,
            "brexchange": segment,
            "token": str(token),
            "expiry": expiry,
            "strike": strike,
            "lotsize": lotsize,
            "instrumenttype": instrument_type,
            "tick_size": tick_size,
        }

        records.append(record)

    return pd.DataFrame(records)


def _download_segment(segment):
    client = get_httpx_client()
    rows = []

    for ext in ("json", "csv"):
        url = f"{BASE_URL}/contractfiles/{segment}.{ext}"
        try:
            response = client.get(url)
        except Exception as exc:
            logger.warning(f"Contract download failed for {segment}.{ext}: {exc}")
            continue

        if response.status_code != 200:
            continue

        if ext == "json":
            try:
                payload = response.json()
            except Exception:
                logger.warning(f"Invalid JSON contract file for {segment}")
                continue
            rows = _extract_rows(payload)
        else:
            rows = _extract_csv_rows(response.text)

        if rows:
            logger.info(f"Loaded {len(rows)} contract rows for {segment} from {ext.upper()}")
            break

    if not rows:
        logger.warning(f"No contract rows returned for segment {segment}")
        return pd.DataFrame()

    df = _parse_segment_data(segment, rows)
    logger.info(f"Downloaded {len(df)} normalized records for {segment}")
    return df


def master_contract_download():
    try:
        logger.info("Starting IIFL Capital Master Contract download")

        init_db()
        delete_symtoken_table()

        frames = []
        for segment in SEGMENTS:
            try:
                df = _download_segment(segment)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:
                logger.warning(f"Failed segment {segment}: {exc}")

        if not frames:
            raise Exception("No contract data downloaded from any segment")

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.replace([np.inf, -np.inf], np.nan).fillna("")

        # Keep latest unique token per exchange
        combined = combined.drop_duplicates(subset=["exchange", "token"], keep="last")

        copy_from_dataframe(combined)

        logger.info("Master Contract download completed")
        return socketio.emit(
            "master_contract_download",
            {
                "status": "success",
                "message": f"Successfully downloaded {len(combined)} symbols",
                "timestamp": datetime.now().isoformat(),
            },
        )

    except Exception as exc:
        logger.exception(f"Error in master contract download: {exc}")
        return socketio.emit(
            "master_contract_download",
            {
                "status": "error",
                "message": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
        )
