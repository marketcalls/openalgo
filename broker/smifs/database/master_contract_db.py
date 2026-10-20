"""Download the SMIFS scrip master into OpenAlgo's shared symtoken table.

The master comes from GET /v1/instruments/master, one exchange segment at a
time so that no single response holds all 320,000 or more rows. Each row is
turned into OpenAlgo's symbol format:

    equity    RELIANCE
    future    NIFTY30OCT26FUT
    option    NIFTY30OCT2625000CE
    index     NIFTY, BANKNIFTY, SENSEX (exchange NSE_INDEX or BSE_INDEX)

When the scrip master service is down, SMIFS answers the same URL with the
platform's own instruments in the same column layout. Older servers answered
with a different layout, or only offered the compact GET /v1/instruments list,
so the parser accepts all three.

The full master carries no lot size or tick size. The compact list does for
the instruments the platform trades, so its values are merged in by security
id; any other contract falls back to a lot size of 1 and a tick of 0.05.
"""
import csv
import io
import re
from datetime import date

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from broker.smifs.api.baseurl import get_url

logger = get_logger(__name__)

try:
    from database.symbol import SymToken, db_session
    from extensions import socketio
except Exception:  # noqa: BLE001 (importable standalone for review and tests)
    SymToken = db_session = socketio = None

# SMIFS segment -> OpenAlgo exchange. IDX_I is split into NSE_INDEX and
# BSE_INDEX per row in _index_exchange.
_EXCH = {"NSE_EQ": "NSE", "NSE_FNO": "NFO", "NSE_CURRENCY": "CDS",
         "BSE_EQ": "BSE", "BSE_FNO": "BFO", "BSE_CURRENCY": "BCD",
         "MCX_COMM": "MCX", "IDX_I": "NSE_INDEX"}

SEGMENTS = list(_EXCH)

# Exchange index names -> the short names OpenAlgo uses for the common ones.
_INDEX_NAMES = {
    "NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY MID SELECT": "MIDCPNIFTY", "NIFTY NEXT 50": "NIFTYNXT50", "INDIA VIX": "INDIAVIX",
    "SENSEX": "SENSEX", "BANKEX": "BANKEX", "SNSX50": "SENSEX50",
}
_BSE_INDICES = {"SENSEX", "BANKEX", "SENSEX50", "BSE100", "SNXN30", "FOCIT", "FOCMID"}

# The BSE derivatives master carries strikes in paise (a SENSEX strike of
# 80000 arrives as 8000000.0), unlike every other segment, and names its
# contracts with exchange codes (BSX, BKX) rather than the underlying.
# Divide strikes back to rupees and rename the index codes OpenAlgo knows.
_STRIKE_DIVISOR = {"BSE_FNO": 100.0}
_BSE_FNO_CODES = {"BSX": "SENSEX", "BKX": "BANKEX", "SX50": "SENSEX50"}

# The NSE derivatives master also lists every BSE derivative a second time,
# under NSE_FNO with the BSE security id plus 100,000,000 and the underlying
# spelt out with a rupee strike. Those rows are not NSE contracts, so they are
# dropped from NFO and used only to name the matching BFO rows.
_BSE_COPY_OFFSET = 100_000_000

# Cash symbols repeat across series (EQ, BE, BL, ...). Keep the tradeable one.
_SERIES_RANK = {"EQ": 0, "A": 0, "B": 1, "BE": 2, "BZ": 3, "SM": 4, "ST": 4}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _fetch(path):
    client = get_httpx_client()
    r = client.get(get_url(path), timeout=120)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _expiry_parts(value):
    """ISO yyyy-mm-dd -> date, or None."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _strike_text(strike):
    return f"{strike:.2f}".rstrip("0").rstrip(".")


def _index_exchange(symbol, security_id):
    # BSE indices are numbered from 2000000000 in the SMIFS master.
    if symbol in _BSE_INDICES or str(security_id).startswith("2000000"):
        return "BSE_INDEX"
    return "NSE_INDEX"


def _bse_copies(rows):
    """BSE security id -> (underlying, rupee strike), from the NSE_FNO copies."""
    copies = {}
    for row in rows:
        if row.get("exchangeSegment") != "NSE_FNO":
            continue
        try:
            sid = int(row.get("securityId") or 0)
        except ValueError:
            continue
        if sid >= _BSE_COPY_OFFSET and row.get("symbol"):
            copies[str(sid - _BSE_COPY_OFFSET)] = (row["symbol"], float(row.get("strike") or 0))
    return copies


def to_openalgo(row, bse_copies=None):
    """One master row (any of the three layouts) -> a symtoken dict, or None to skip."""
    seg = row.get("exchangeSegment") or row.get("exchange_segment")
    token = row.get("securityId") or row.get("security_id")
    base = (row.get("symbol") or row.get("tradingSymbol") or row.get("trading_symbol") or "").strip()
    if seg not in _EXCH or not token or not base:
        return None
    if seg == "NSE_FNO" and str(token).isdigit() and int(token) >= _BSE_COPY_OFFSET:
        return None
    itype = (row.get("instrumentType") or row.get("instrument_type") or "").upper()
    # The compact list says FUTIDX, FUTSTK, FUTCOM, OPTIDX and so on.
    if itype.startswith("FUT"):
        itype = "FUT"
    elif itype.startswith("OPT"):
        itype = "OPT"
    expiry = _expiry_parts(row.get("expiry"))
    strike = float(row.get("strike") or 0) / _STRIKE_DIVISOR.get(seg, 1.0)
    if seg == "BSE_FNO":
        copy = (bse_copies or {}).get(str(token))
        if copy:
            base, strike = copy[0], copy[1] or strike
        else:
            base = _BSE_FNO_CODES.get(base.upper(), base)
    opt = (row.get("optionType") or "").upper()
    exchange = _EXCH[seg]
    expiry_text = expiry_symbol = ""
    if expiry:
        expiry_symbol = f"{expiry.day:02d}{_MONTHS[expiry.month - 1]}{expiry.year % 100:02d}"
        expiry_text = f"{expiry.day:02d}-{_MONTHS[expiry.month - 1]}-{expiry.year % 100:02d}"
    compact = base.upper().replace(" ", "")

    if seg == "IDX_I":
        symbol = _INDEX_NAMES.get(base.upper(), compact)
        exchange = _index_exchange(symbol, token)
        instrumenttype = "INDEX"
    elif itype == "OPT" and expiry and opt in ("CE", "PE"):
        symbol = f"{compact}{expiry_symbol}{_strike_text(strike)}{opt}"
        instrumenttype = opt
    elif itype == "FUT" and expiry:
        symbol = f"{compact}{expiry_symbol}FUT"
        instrumenttype = "FUT"
    elif itype == "FUT":
        # Platform instruments such as NIFTY-FUT carry no expiry; keep the
        # SMIFS symbol as it is, but still type the row as a future.
        symbol = compact
        instrumenttype = "FUT"
    else:
        symbol = compact
        instrumenttype = "EQ"
    return {
        "symbol": symbol, "brsymbol": base, "token": str(token),
        "exchange": exchange, "brexchange": seg,
        "name": row.get("name") or base,
        "expiry": expiry_text, "strike": strike,
        "lotsize": max(1, int(float(row.get("lotSize") or row.get("lot_size") or 1))),
        "tick_size": float(row.get("tickSize") or row.get("tick_size") or 0.05),
        "instrumenttype": instrumenttype,
        "_rank": _SERIES_RANK.get((row.get("series") or "").upper(), 5),
    }


def build_symtokens(rows):
    """Convert and de-duplicate: OpenAlgo needs (symbol, exchange) to be unique."""
    best = {}
    copies = _bse_copies(rows)
    for row in rows:
        rec = to_openalgo(row, copies)
        if rec is None:
            continue
        key = (rec["symbol"], rec["exchange"])
        held = best.get(key)
        if held is None or rec["_rank"] < held["_rank"]:
            best[key] = rec
    out = []
    for rec in best.values():
        rec = dict(rec)
        rec.pop("_rank")
        out.append(rec)
    return out


def _merge_sizes(rows, compact):
    """Copy lot_size and tick_size from the compact list onto master rows."""
    sizes = {}
    for c in compact:
        key = (c.get("exchange_segment"), str(c.get("security_id")))
        sizes[key] = (c.get("lot_size"), c.get("tick_size"))
    for row in rows:
        if row.get("lotSize") or row.get("lot_size"):
            continue
        hit = sizes.get((row.get("exchangeSegment"), str(row.get("securityId"))))
        if hit:
            row["lotSize"], row["tickSize"] = hit
    return rows


def download_rows():
    rows = []
    for seg in SEGMENTS:
        try:
            rows.extend(_fetch(f"/v1/instruments/master?exchangeSegment={seg}"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SMIFS master for {seg} failed: {e}")
    try:
        compact = _fetch("/v1/instruments")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"SMIFS compact instrument list failed: {e}")
        compact = []
    if not rows:
        return compact
    return _merge_sizes(rows, compact)


def master_contract_download():
    try:
        records = build_symtokens(download_rows())
    except Exception as e:  # noqa: BLE001
        logger.error(f"SMIFS master contract download failed: {e}")
        if socketio:
            socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
        return {"status": "error", "message": str(e)}
    if SymToken is None:
        return records  # review/standalone mode
    db_session.query(SymToken).delete()
    db_session.bulk_insert_mappings(SymToken, records)
    db_session.commit()
    logger.info(f"SMIFS master contract loaded: {len(records)} symbols")
    if socketio:
        socketio.emit("master_contract_download",
                      {"status": "success", "message": "Successfully Downloaded"})
    return {"status": "success", "count": len(records)}


def search_symbols(symbol, exchange):
    if SymToken is None:
        return []
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange).all()
