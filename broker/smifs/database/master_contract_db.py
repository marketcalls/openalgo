"""Download the SMIFS scrip master into OpenAlgo's shared symtoken table."""
import io
import csv
from utils.httpx_client import get_httpx_client

from broker.smifs.api.baseurl import get_url

try:
    from database.symbol import SymToken, db_session
    from extensions import socketio
except Exception:  # noqa: BLE001 — importable standalone for review
    SymToken = db_session = socketio = None

_EXCH = {"NSE_EQ": ("NSE", "NSE"), "NSE_FNO": ("NFO", "NSE"),
         "NSE_CURRENCY": ("CDS", "NSE"), "BSE_EQ": ("BSE", "BSE"),
         "BSE_FNO": ("BFO", "BSE"), "BSE_CURRENCY": ("BCD", "BSE"),
         "MCX_COMM": ("MCX", "MCX")}


def _rows():
    client = get_httpx_client()
    r = client.get(get_url("/v1/instruments"))
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def master_contract_download():
    rows = _rows()
    if SymToken is None:
        return rows  # review/standalone mode
    db_session.query(SymToken).delete()
    for row in rows:
        seg = row["exchange_segment"]
        oa_exch, brexch = _EXCH.get(seg, ("NSE", "NSE"))
        sym = row["trading_symbol"]
        db_session.add(SymToken(
            symbol=sym, brsymbol=sym, token=row["security_id"],
            exchange=oa_exch, brexchange=seg, name=row.get("name", sym),
            lotsize=int(row.get("lot_size", 1) or 1),
            tick_size=float(row.get("tick_size", 0.05) or 0.05),
            instrumenttype=row.get("instrument_type", "EQ")))
    db_session.commit()
    if socketio:
        socketio.emit("master_contract_download", {"status": "success", "broker": "smifs"})
    return rows


def search_symbols(symbol, exchange):
    if SymToken is None:
        return []
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange).all()
