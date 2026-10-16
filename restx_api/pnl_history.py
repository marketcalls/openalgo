# restx_api/pnl_history.py
"""REST resources for multi-day P&L, backed by the tradebook_fills ledger.

Mounted on the existing "/pnl" path as a second Namespace (pnl_symbols_ns
already registers the sandbox-only /pnl/symbols there).

    GET  /api/v1/pnl/history  - realized P&L for a date range
    GET  /api/v1/pnl/trades   - raw fills for a date range, no FIFO -
                                 backs the historical Trade Book view
    POST /api/v1/pnl/import   - backfill the ledger from an exported
                                 tradebook CSV, for history predating the
                                 daily capture job
    GET  /api/v1/pnl/strategy-legs - tracked strategy legs (strategy book)
    PATCH /api/v1/pnl/trades/<id>/strategy - tag one fill with a strategy
"""

import csv
import functools
import io
import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.pnl_history_service import (
    get_pnl_curve,
    get_pnl_history,
    get_pnl_trades,
    get_strategy_legs,
    import_kotak_statement,
    import_trades_csv,
    set_trade_strategy,
)
from utils.kotak_statement import is_kotak_statement
from utils.logging import get_logger

from .pnl_history_schema import (
    PnlCurveSchema,
    PnlHistorySchema,
    PnlImportSchema,
    PnlSetTradeStrategySchema,
    PnlStrategyLegsSchema,
)

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

# Distinct internal namespace name from restx_api/pnl_symbols.py's "pnl", so
# Flask-RESTX/Swagger metadata for the two files never collide even though
# both mount at the same "/pnl" URL path.
api = Namespace("pnl_history", description="Consolidated multi-day P&L")

logger = get_logger(__name__)

pnl_history_schema = PnlHistorySchema()
pnl_curve_schema = PnlCurveSchema()
pnl_import_schema = PnlImportSchema()
pnl_strategy_legs_schema = PnlStrategyLegsSchema()
pnl_set_trade_strategy_schema = PnlSetTradeStrategySchema()

# Column-name aliases across broker tradebook CSV exports (Zerodha Console's
# tradebook export; other brokers can be added here).
_COLUMN_ALIASES = {
    "symbol": ("symbol", "tradingsymbol", "trdsym", "instrument"),
    "exchange": ("exchange", "exch", "exseg"),
    "product": ("product", "prod"),
    "action": ("action", "trade_type", "transaction_type", "side", "trnstp"),
    "quantity": ("quantity", "qty", "traded_quantity", "fldqty"),
    "average_price": ("average_price", "price", "trade_price", "avgprc"),
    "orderid": ("order_id", "orderid", "nordno"),
    "tradeid": ("trade_id", "tradeid", "flid"),
    # A single column already carrying a full date+time is used as-is; exports
    # that split date and time use trade_date + order_execution_time instead.
    "trade_timestamp": ("timestamp", "trade_timestamp", "extm", "fill_timestamp"),
    "trade_date": ("trade_date",),
    "order_execution_time": ("order_execution_time",),
    # Console carries the segment ("EQ"/"FO"/...) directly; exchange alone cannot
    # tell it, since Console reports plain NSE/BSE for F&O rows too.
    "segment": ("segment",),
}

# Broker-CSV segment code -> VALID_SEGMENTS (database/pnl_db.py). An unrecognised
# code is dropped so the caller falls back to derive_segment(exchange).
_SEGMENT_ALIASES = {
    "EQ": "equity",
    "FO": "fno",
    "CD": "currency",
    "COM": "commodity",
    "MF": "mutual_fund",
}


def _normalize_header(header: str) -> str:
    """ "Trade Type" / "Order Execution Time" / "order-id" -> "trade_type" /
    "order_execution_time" / "order_id", so lookup ignores header spacing/casing.
    """
    return (header or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_csv_row(raw_row: dict) -> dict:
    """Map one broker-CSV row (arbitrary header casing/naming) onto the
    common shape services.pnl_history_service.import_trades_csv expects.
    """
    lower_row = {_normalize_header(key): value for key, value in raw_row.items()}

    normalized = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_row and lower_row[alias] not in (None, ""):
                normalized[field] = lower_row[alias]
                break

    trade_date = normalized.pop("trade_date", None)
    order_time = normalized.pop("order_execution_time", None)
    if "trade_timestamp" not in normalized:
        if trade_date and order_time:
            # order_execution_time already containing a date (some exports
            # do combine them despite the column name) would double up the
            # date if naively concatenated - only prepend trade_date when
            # order_time looks like a bare HH:MM:SS.
            if len(str(order_time).strip()) <= 8:
                normalized["trade_timestamp"] = f"{trade_date} {order_time}"
            else:
                normalized["trade_timestamp"] = order_time
        elif trade_date:
            normalized["trade_timestamp"] = trade_date
        elif order_time:
            normalized["trade_timestamp"] = order_time

    raw_segment = str(normalized.get("segment", "")).strip().upper()
    mapped_segment = _SEGMENT_ALIASES.get(raw_segment)
    if mapped_segment:
        normalized["segment"] = mapped_segment
    else:
        # Unrecognized or absent - don't write a guess under the "segment"
        # key; import_trades_csv falls back to derive_segment(exchange)
        # whenever this key is missing.
        normalized.pop("segment", None)

    return normalized


def _handle_errors(view):
    """Shared error mapping: schema failures are 400, anything else a logged 500."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in {request.path}: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )

    return wrapper


@api.route("/history", strict_slashes=False)
class PnlHistory(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def get(self):
        """Realized P&L for one account over a date range."""
        params = pnl_history_schema.load(request.args.to_dict())
        success, response_data, status_code = get_pnl_history(
            api_key=params["apikey"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            symbol=params.get("symbol"),
            segment=params.get("segment"),
            strategy=params.get("strategy"),
        )
        return make_response(jsonify(response_data), status_code)


@api.route("/curve", strict_slashes=False)
class PnlCurve(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def get(self):
        """Daily realized and unrealized P&L per strategy (equity only)."""
        params = pnl_curve_schema.load(request.args.to_dict())
        success, response_data, status_code = get_pnl_curve(
            api_key=params["apikey"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            basis=params["basis"],
            symbol_contains=params.get("symbol_contains"),
        )
        return make_response(jsonify(response_data), status_code)


@api.route("/trades", strict_slashes=False)
class PnlTrades(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def get(self):
        """Raw fills for one account over a date range - no FIFO matching."""
        params = pnl_history_schema.load(request.args.to_dict())
        success, response_data, status_code = get_pnl_trades(
            api_key=params["apikey"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            symbol=params.get("symbol"),
            segment=params.get("segment"),
            strategy=params.get("strategy"),
        )
        return make_response(jsonify(response_data), status_code)


@api.route("/import", strict_slashes=False)
class PnlImport(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def post(self):
        """Backfill the ledger from an uploaded broker tradebook CSV."""
        form_data = pnl_import_schema.load(request.form.to_dict())

        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return make_response(
                jsonify({"status": "error", "message": "A CSV file is required"}), 400
            )

        try:
            text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return make_response(
                jsonify({"status": "error", "message": "CSV must be UTF-8 encoded"}), 400
            )

        reader = csv.DictReader(io.StringIO(text))

        # The file itself says which format it is: Kotak's Transaction
        # Statement has Security Name / Market Rate columns no other
        # export has. The service then also checks the account's broker,
        # so a Kotak file can't be written into a Zerodha ledger.
        if is_kotak_statement(reader.fieldnames):
            success, response_data, status_code = import_kotak_statement(
                api_key=form_data["apikey"], raw_rows=list(reader)
            )
            return make_response(jsonify(response_data), status_code)

        rows = [_normalize_csv_row(row) for row in reader]

        success, response_data, status_code = import_trades_csv(
            api_key=form_data["apikey"], rows=rows
        )
        return make_response(jsonify(response_data), status_code)


@api.route("/strategy-legs", strict_slashes=False)
class PnlStrategyLegs(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def get(self):
        """Every currently-tracked strategy leg for this account, read from
        the strategy book (database/strategy_book_db.py)."""
        params = pnl_strategy_legs_schema.load(request.args.to_dict())
        success, response_data, status_code = get_strategy_legs(
            api_key=params["apikey"],
            strategy=params.get("strategy"),
        )
        return make_response(jsonify(response_data), status_code)


@api.route("/trades/<int:trade_id>/strategy", strict_slashes=False)
class PnlSetTradeStrategy(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @_handle_errors
    def patch(self, trade_id):
        """Manually tag one historical fill with a strategy (for CSV-imported
        history and fills with no order id to join against the strategy book)."""
        data = pnl_set_trade_strategy_schema.load(request.json or {})
        success, response_data, status_code = set_trade_strategy(
            api_key=data["apikey"],
            trade_id=trade_id,
            strategy=data["strategy"],
        )
        return make_response(jsonify(response_data), status_code)
