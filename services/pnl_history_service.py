# services/pnl_history_service.py
"""Compute-on-read realized P&L for the P&L Analysis page.

Backs the /api/v1/pnl/* REST resources (restx_api/pnl_history.py). Nothing
computed is persisted: each request re-reads the fills in db/tradebook.db and
re-runs utils/pnl_fifo.py, as the intraday PnL Tracker does for one day.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

from database.auth_db import get_auth_token_broker
from database.pnl_db import (
    VALID_SEGMENTS,
    TradebookFill,
    db_session,
    derive_segment,
    fill_exists,
    lookup_order_strategy,
    make_dedup_key,
    normalize_fno_exchange,
    parse_trade_timestamp,
)
from database.strategy_book_db import StrategyBookUnavailable, get_order_tag
from services.pnl_curve import VALID_BASES, build_curve, symbols_needing_closes
from utils.kotak_statement import normalize_company_name, normalize_statement_row
from utils.logging import get_logger
from utils.pnl_fifo import compute_realized_pnl, summarize_by_day
from utils.thread_safe_cache import LockedTTLCache

logger = get_logger(__name__)

# get_pnl_history's FIFO lookback (see fifo_lookback below): F&O contracts
# (and currency/commodity, also expiry-based) always expire well within a
# year, so a leg that's still open can't be older than this - unlike
# equity/mutual_fund holdings, which can genuinely be years old. Keeps the
# widened FIFO query from scanning the whole ledger for the common,
# expiry-bounded segments.
_FNO_LOOKBACK_DAYS = 365
_LONG_HOLD_SEGMENTS = ("equity", "mutual_fund")

_IST = ZoneInfo("Asia/Kolkata")


def _live_open_rows(api_key, end_date, segment=None):
    """What is open right now, valued at the live price: the source of the
    report's unrealized P&L.

    Equity comes from the broker's holdings, everything else (F&O, currency,
    commodity) from its position book, the way Zerodha Console's Unrealised
    view reads open holdings and positions. The FIFO replay of the ledger is
    deliberately not used here: it cannot see fills from before the ledger
    began and never sees an option settling at expiry, so it invents open
    positions that the broker does not hold.

    Each broker row is split into per-strategy slices by
    services/strategy_attribution.py (an unexplained remainder is untagged).
    Returns (rows, total_unrealized_or_None). The total is None - and rows
    empty - when the range ends before today (unrealized P&L exists only at
    the live price) or the broker rows cannot be read. A row whose price
    cannot be fetched carries ltp/unrealized_pnl of None and is left out of
    the total.
    """
    if end_date < datetime.now(_IST).date().isoformat():
        return [], None

    try:
        from services.holdings_service import get_holdings
        from services.positionbook_service import get_positionbook
        from services.quotes_service import get_multiquotes
        from services.strategy_attribution import KIND_HOLDINGS, KIND_POSITIONS, attribute

        try:
            from database.strategy_book_db import get_strategy_legs as _get_strategy_legs

            legs = _get_strategy_legs()
        except StrategyBookUnavailable:
            # Unknown ownership only costs the strategy label, not the P&L.
            legs = []

        ok, response, _status = get_holdings(api_key=api_key)
        if not ok:
            return [], None
        data = response.get("data")
        holdings = data.get("holdings") if isinstance(data, dict) else data
        holdings = holdings if isinstance(holdings, list) else []

        ok, response, _status = get_positionbook(api_key=api_key)
        if not ok:
            return [], None
        positions = response.get("data")
        positions = positions if isinstance(positions, list) else []
        # Equity is read from holdings only; an open intraday equity position
        # is squared off the same day and would double a same-day delivery buy.
        positions = [r for r in positions if derive_segment(r.get("exchange")) != "equity"]

        open_rows = []
        for kind, raw_rows in ((KIND_HOLDINGS, holdings), (KIND_POSITIONS, positions)):
            attributed = attribute(raw_rows, legs, kind)["rows"]
            for raw, row in zip(raw_rows, attributed, strict=True):
                if abs(row["quantity"]) <= 1e-9:
                    continue
                if segment and derive_segment(row["exchange"]) != segment:
                    continue
                open_rows.append((kind, raw, row))

        wanted = sorted({(row["symbol"], row["exchange"]) for _k, _r, row in open_rows})
        ltps = {}
        if wanted:
            ok, quotes, _status = get_multiquotes(
                [{"symbol": sym, "exchange": exch} for sym, exch in wanted], api_key=api_key
            )
            if ok:
                for item in quotes.get("results", []):
                    quote = item.get("data")
                    if isinstance(quote, dict) and quote.get("ltp"):
                        ltps[(item.get("symbol"), item.get("exchange"))] = float(quote["ltp"])

        rows = []
        total = 0.0
        for kind, raw, row in open_rows:
            ltp = ltps.get((row["symbol"], row["exchange"]))
            if ltp is None:
                try:
                    ltp = float(raw.get("ltp")) or None
                except (TypeError, ValueError):
                    ltp = None
            for part in row["slices"]:
                quantity = part["quantity"]
                if abs(quantity) <= 1e-9:
                    continue
                unrealized = None
                if ltp is not None:
                    unrealized = round((ltp - part["average_price"]) * quantity, 2)
                    total += unrealized
                rows.append(
                    {
                        "symbol": row["symbol"],
                        "exchange": row["exchange"],
                        "product": row["product"],
                        "source": kind,
                        "action": "BUY" if quantity > 0 else "SELL",
                        "quantity": abs(quantity),
                        "average_price": round(part["average_price"], 2),
                        "strategy": part["strategy"] if part["attributed"] else None,
                        "ltp": None if ltp is None else round(ltp, 2),
                        "unrealized_pnl": unrealized,
                    }
                )
        return rows, round(total, 2)
    except Exception:
        logger.exception("Could not read live holdings and positions for unrealized P&L")
        return [], None


def _parse_range_and_build_query(
    start_date, end_date, symbol=None, segment=None, strategy=None, fifo_lookback=False
):
    """Shared by get_pnl_history and get_pnl_trades: parse the date range,
    validate segment, and build the base TradebookFill query. Returns
    (error_response_or_None, query_or_None, start, end).

    strategy is a pre-filter, same as segment/symbol: applied to TradebookFill
    rows *before* get_pnl_history's FIFO matching ever runs, not threaded
    through utils/pnl_fifo.py's lot objects. A closed_trades/daily/scrip
    response filtered to one strategy is therefore already guaranteed
    single-strategy by construction - no ambiguity about which strategy a
    given closed lot (which can span two physical fills) belongs to,
    because only that one strategy's fills were ever in the query.

    fifo_lookback=True (get_pnl_history only) widens the query's lower
    bound past start_date: FIFO matching needs to see a position's actual
    entry fill even when it happened long before the requested range, or a
    sell that's really closing a months/years-old buy gets misread as
    opening a brand-new short and reports the wrong (often zero) realized
    P&L - Zerodha's own convention is to still book it. How far back
    depends on the segment: equity/mutual_fund get no lower bound at all
    (a holding can be years old); everything else (fno/currency/commodity,
    all expiry-based) is capped at _FNO_LOOKBACK_DAYS before end_date,
    since a still-open leg there can't be older than that. get_pnl_trades
    (raw historical fills, no FIFO involved) never sets this - it always
    wants the exact requested range.
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        return (
            (False, {"status": "error", "message": "start_date/end_date must be YYYY-MM-DD"}, 400),
            None,
            None,
            None,
        )

    if segment and segment not in VALID_SEGMENTS:
        return (
            (
                False,
                {"status": "error", "message": f"segment must be one of {VALID_SEGMENTS}"},
                400,
            ),
            None,
            None,
            None,
        )

    if fifo_lookback:
        lookback_cutoff = end - timedelta(days=_FNO_LOOKBACK_DAYS)
        query = db_session.query(TradebookFill).filter(
            TradebookFill.trade_timestamp <= end,
            or_(
                TradebookFill.segment.in_(_LONG_HOLD_SEGMENTS),
                # Unknown/pre-migration segment: err on the side of
                # scanning more, not silently truncating a real position.
                TradebookFill.segment.is_(None),
                TradebookFill.trade_timestamp >= lookback_cutoff,
            ),
        )
    else:
        query = db_session.query(TradebookFill).filter(
            TradebookFill.trade_timestamp >= start, TradebookFill.trade_timestamp <= end
        )

    if symbol:
        query = query.filter(TradebookFill.symbol == symbol)
    if segment:
        # Filters on the stored segment column (derive_segment(), set once
        # at write time by both writers) rather than re-deriving from
        # exchange on every read. Safe as a pre-filter for get_pnl_history's
        # FIFO matching specifically because exchange - and therefore
        # segment, which is a pure function of it - is already part of the
        # FIFO grouping key (utils/pnl_fifo.py groups by
        # symbol+exchange); for get_pnl_trades it's just a plain row
        # filter with no matching involved at all.
        query = query.filter(TradebookFill.segment == segment)
    if strategy:
        query = query.filter(TradebookFill.strategy == strategy)

    return None, query, start, end


def get_pnl_history(
    api_key: str,
    start_date: str,
    end_date: str,
    symbol: str | None = None,
    segment: str | None = None,
    strategy: str | None = None,
):
    """Realized P&L for one account over [start_date, end_date] (inclusive,
    "YYYY-MM-DD"), optionally narrowed to one symbol, one segment (one of
    database.pnl_db.VALID_SEGMENTS), and/or one strategy (a free-text name
    from database.strategy_book_db - see TradebookFill.strategy's docstring).

    Returns (success, response_dict, status_code) - same tuple shape as
    every other service in services/ (docs/design/27-service-layer).
    """
    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    error, query, start, end = _parse_range_and_build_query(
        start_date, end_date, symbol=symbol, segment=segment, strategy=strategy, fifo_lookback=True
    )
    if error:
        return error

    try:
        # Chronological order matters for FIFO correctness (utils/pnl_fifo.py
        # sorts again internally, but ties on an identical timestamp then
        # fall back to this insertion/id order rather than an arbitrary one).
        # fifo_lookback=True means these rows can reach back well before
        # start_date - deliberately, so a lot that opened long ago but
        # closed inside the requested range is matched against its real
        # entry fill rather than being misread as a brand-new position.
        rows = query.order_by(TradebookFill.trade_timestamp.asc(), TradebookFill.id.asc()).all()

        trades = [
            {
                "symbol": row.symbol,
                "exchange": row.exchange,
                "product": row.product,
                "segment": row.segment,
                "action": row.action,
                "quantity": row.quantity,
                "average_price": row.average_price,
                "trade_timestamp": row.trade_timestamp.isoformat(),
                "strategy": row.strategy,
            }
            for row in rows
        ]

        result = compute_realized_pnl(trades)

        # Only report lots that actually closed within [start_date,
        # end_date] - fills from outside the range were pulled in solely so
        # FIFO could see a position's true entry (see
        # _parse_range_and_build_query's fifo_lookback docstring). A lot
        # that closed last year (or, for F&O, last month) is real,
        # correctly-computed P&L, just not part of *this* report; it will
        # show up when that lot's own date range is queried instead.
        lots_in_range = [
            lot
            for lot in result.realized_lots
            if lot.exit_timestamp and start_date <= str(lot.exit_timestamp)[:10] <= end_date
        ]
        daily = summarize_by_day(lots_in_range)
        open_rows, total_unrealised = _live_open_rows(api_key, end_date, segment)

        # Raw-fill count inside the requested range specifically (not the
        # wider fifo_lookback query above) - matches what "N trades this
        # week" should mean to whoever's reading it.
        trade_count = sum(1 for row in rows if start <= row.trade_timestamp <= end)

        return (
            True,
            {
                "status": "success",
                "data": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "total_realized_pnl": round(sum(lot.realized_pnl for lot in lots_in_range), 2),
                    "trade_count": trade_count,
                    "daily": [
                        {
                            "date": day["date"],
                            "realized_pnl": round(day["realized_pnl"], 2),
                            "trade_count": day["trade_count"],
                        }
                        for day in daily
                    ],
                    "closed_trades": [
                        {
                            "symbol": lot.symbol,
                            "exchange": lot.exchange,
                            "product": lot.product,
                            "entry_action": lot.entry_action,
                            "quantity": lot.quantity,
                            "entry_price": round(lot.entry_price, 2),
                            "entry_timestamp": str(lot.entry_timestamp),
                            "exit_price": round(lot.exit_price, 2),
                            "exit_timestamp": str(lot.exit_timestamp),
                            "realized_pnl": round(lot.realized_pnl, 2),
                            "strategy": lot.strategy,
                        }
                        for lot in lots_in_range
                    ],
                    "open_positions": open_rows,
                    # None when the range ends before today: unrealized P&L
                    # exists only at the live LTP.
                    "total_unrealized_pnl": total_unrealised,
                },
            },
            200,
        )
    except Exception as e:
        logger.exception(f"Error computing PnL history: {e}")
        return False, {"status": "error", "message": str(e)}, 500
    finally:
        db_session.remove()


def get_pnl_trades(
    api_key: str,
    start_date: str,
    end_date: str,
    symbol: str | None = None,
    segment: str | None = None,
    strategy: str | None = None,
):
    """Raw fills for one account over [start_date, end_date] - no FIFO
    matching, just the ledger rows as-is. Backs the historical Tradebook
    view (frontend/src/pages/TradeBook.tsx switches to this endpoint once
    the selected date range isn't "today"; the live view keeps using the
    broker's own tradebook API via services/tradebook_service.py, since
    today's trades aren't in the ledger yet - the daily capture job runs
    at 16:00 IST, after close).

    Returns each row in the same shape frontend/src/types/trading.ts's
    Trade interface expects, so the existing Trade Book table needs no
    per-source branching to render either kind of data. `id` is included
    (unlike get_pnl_history's trade shapes) so the frontend can address a
    specific row for the manual strategy-tag fallback
    (set_trade_strategy below).
    """
    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    error, query, start, end = _parse_range_and_build_query(
        start_date, end_date, symbol=symbol, segment=segment, strategy=strategy
    )
    if error:
        return error

    try:
        rows = query.order_by(TradebookFill.trade_timestamp.desc(), TradebookFill.id.desc()).all()
        data = [
            {
                "id": row.id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "product": row.product or "",
                "action": row.action,
                "quantity": row.quantity,
                "average_price": row.average_price,
                "trade_value": row.trade_value or 0,
                "orderid": row.orderid or "",
                "tradeid": row.tradeid or "",
                "segment": row.segment,
                "strategy": row.strategy,
                # Plain isoformat() (T separator) - matches get_pnl_history's
                # closed_trades entry/exit timestamps above (line ~129) and
                # the canonical ISO 8601 shape every timestamp on the wire
                # now uses (see database/pnl_db.py's parse_trade_timestamp
                # and the broker-side normalization in
                # broker/{zerodha,kotak}/mapping/order_data.py). Used to be
                # isoformat(sep=" "), a silent format mismatch between two
                # sibling endpoints for the same underlying column.
                "timestamp": row.trade_timestamp.isoformat(),
            }
            for row in rows
        ]
        return True, {"status": "success", "data": data}, 200
    except Exception as e:
        logger.exception(f"Error fetching PnL trades: {e}")
        return False, {"status": "error", "message": str(e)}, 500
    finally:
        db_session.remove()


def _normalize_action(value) -> str:
    """ "B"/"S" (Kotak's raw trnsTp) or "buy"/"sell"/"BUY"/"SELL" -> "BUY"/
    "SELL". Anything else is returned upper-cased unchanged so the caller's
    ``action in ("BUY", "SELL")`` validation still rejects it explicitly
    rather than this function guessing.
    """
    normalized = (value or "").strip().upper()
    return {"B": "BUY", "S": "SELL"}.get(normalized, normalized)


def import_trades_csv(api_key: str, rows: list[dict]) -> tuple[bool, dict, int]:
    """Backfill the ledger from an already-parsed CSV (list of dict rows -
    the REST resource owns CSV parsing/validation; this owns normalization,
    dedup, and persistence, matching the service-layer boundary).

    Expects each row to carry at least: symbol, exchange, action ("BUY"/
    "SELL"), quantity, average_price/price, and a trade date/time. Column
    naming varies by broker export (e.g. Zerodha's own tradebook CSV columns
    differ from Kotak's); the REST resource maps broker-specific column
    names to this common shape before calling here, so this function stays
    broker-agnostic.

    Dedup uses the same make_dedup_key as the daily capture job: a CSV
    covering dates the capture job already captured live is a safe,
    idempotent no-op rather than a double-count.
    """
    auth_token, _broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    return _persist_import_rows(rows)


def _statement_equity_resolver():
    """Build ``resolve(company_name, exchange) -> symbol | None`` from the
    symbol master: the one symbol whose master name equals the statement's
    company name once both are normalized, else None (never a guess)."""
    from database.symbol import SymToken

    by_exchange = {}

    def resolve(company_name, exchange):
        if exchange not in by_exchange:
            index = {}
            for symbol, name in (
                SymToken.query.with_entities(SymToken.symbol, SymToken.name)
                .filter(SymToken.exchange == exchange, SymToken.instrumenttype == "EQ")
                .all()
            ):
                index.setdefault(normalize_company_name(name), set()).add(symbol)
            by_exchange[exchange] = index
        matches = by_exchange[exchange].get(normalize_company_name(company_name), set())
        return next(iter(matches)) if len(matches) == 1 else None

    return resolve


def import_kotak_statement(api_key: str, raw_rows: list[dict]) -> tuple[bool, dict, int]:
    """Backfill the ledger from a Kotak "Transaction Statement" CSV (see
    utils/kotak_statement.py for the format and how it differs from the
    Zerodha tradebook).

    Two safeguards the Zerodha path doesn't need:

    - The account's broker must be Kotak. A statement is only meaningful for
      the Kotak account it was exported from; sending it to a Zerodha account
      would write another person's trades into that ledger.
    - Days the daily capture job already holds are skipped. The statement has
      no trade ids and one line per order (the capture stores individual
      fills), so an overlapping day cannot be deduplicated and would be
      double-counted. Only days the capture never saw are imported.
    """
    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
    if (broker or "").lower() != "kotak":
        return (
            False,
            {
                "status": "error",
                "message": f"This is a Kotak statement but this account's broker is "
                f"'{broker}'. Upload it to the Kotak account it was exported from.",
            },
            400,
        )

    resolve_equity = _statement_equity_resolver()
    rows = []
    rejected = {}
    unresolved = set()
    for raw in raw_rows:
        row, reason = normalize_statement_row(raw, resolve_equity)
        if row is None:
            rejected[reason] = rejected.get(reason, 0) + 1
            if reason == "unresolved_symbol":
                unresolved.add((raw.get("Security Name") or "").strip())
            continue
        rows.append(row)

    success, body, status = _persist_import_rows(rows, skip_days_with_capture=True)
    if success:
        body["data"]["skipped_invalid"] += sum(rejected.values())
        if rejected:
            body["data"]["rejected_reasons"] = rejected
        if unresolved:
            body["data"]["unresolved_symbols"] = sorted(unresolved)
    return success, body, status


def _persist_import_rows(rows, skip_days_with_capture=False):
    """Validate, dedup and store already-normalized rows (shared by both CSV
    formats). With ``skip_days_with_capture`` a row is skipped when the daily
    capture job already holds any fill for that day."""
    imported = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    skipped_covered = 0
    # The session has autoflush off, so a row added earlier in this same file
    # is invisible to fill_exists(); track its key here or a repeated row
    # would only fail at commit and roll the whole file back.
    seen_keys = set()

    try:
        captured_days = set()
        if skip_days_with_capture:
            captured_days = {
                str(day)
                for (day,) in db_session.query(func.date(TradebookFill.trade_timestamp))
                .filter(TradebookFill.source == "capture")
                .distinct()
                .all()
            }

        for row in rows:
            symbol = row.get("symbol")
            exchange = row.get("exchange")
            # Some broker exports use single-letter codes (Kotak's raw
            # trnsTp: "B"/"S") rather than the full word.
            action = _normalize_action(row.get("action"))
            quantity = row.get("quantity")
            price = row.get("average_price")

            if not (symbol and exchange and action in ("BUY", "SELL") and quantity and price):
                skipped_invalid += 1
                continue

            parsed_timestamp = parse_trade_timestamp(row.get("trade_timestamp"))

            if captured_days and parsed_timestamp.strftime("%Y-%m-%d") in captured_days:
                skipped_covered += 1
                continue

            dedup_key = make_dedup_key(
                tradeid=row.get("tradeid"),
                orderid=row.get("orderid"),
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                average_price=price,
                timestamp=parsed_timestamp,
            )

            if dedup_key in seen_keys or fill_exists(db_session, dedup_key):
                skipped_duplicate += 1
                continue
            seen_keys.add(dedup_key)

            # A CSV that carries its own segment (e.g. Zerodha Console's
            # EQ/FO column, already mapped to VALID_SEGMENTS by the REST
            # resource) wins over the exchange guess - Console sets exchange
            # to the plain NSE/BSE code even for F&O rows, which
            # derive_segment alone would mis-tag as equity. The daily capture
            # job's own rows never carry a "segment" key at all, so this is
            # a no-op for that path.
            segment = row.get("segment") or derive_segment(exchange)

            db_session.add(
                TradebookFill(
                    dedup_key=dedup_key,
                    tradeid=row.get("tradeid") or None,
                    orderid=row.get("orderid") or None,
                    symbol=symbol,
                    # Stored as NFO/BFO for an F&O row Console labelled
                    # NSE/BSE, matching what the capture job stores. The
                    # dedup key above deliberately keeps the raw exchange.
                    exchange=normalize_fno_exchange(segment, exchange),
                    product=row.get("product"),
                    segment=segment,
                    # Best-effort - a CSV row's orderid only matches the
                    # strategy book when it happens to be a real OpenAlgo
                    # order still within the order-tag's 30-day retention;
                    # older/pre-OpenAlgo history stays unattributed unless
                    # manually tagged later (set_trade_strategy below).
                    strategy=lookup_order_strategy(row.get("orderid")),
                    action=action,
                    quantity=float(quantity),
                    average_price=float(price),
                    trade_value=float(quantity) * float(price),
                    trade_timestamp=parsed_timestamp,
                    source="import",
                )
            )
            imported += 1

        db_session.commit()
        data = {
            "imported": imported,
            "skipped_duplicate": skipped_duplicate,
            "skipped_invalid": skipped_invalid,
        }
        if skip_days_with_capture:
            data["skipped_covered_by_capture"] = skipped_covered
        return True, {"status": "success", "data": data}, 200
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error importing PnL CSV: {e}")
        return False, {"status": "error", "message": str(e)}, 500
    finally:
        db_session.remove()


def get_strategy_legs(api_key: str, strategy: str | None = None):
    """Every currently tracked strategy leg for this account, read from the
    strategy book (database/strategy_book_db.py). Not scoped by date: the book
    tracks current open legs."""
    from database.strategy_book_db import get_strategy_legs as _get_strategy_legs

    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    try:
        legs = _get_strategy_legs(strategy=strategy)
        return True, {"status": "success", "data": legs}, 200
    except StrategyBookUnavailable as e:
        # An unavailable book is not the same as "no legs".
        return False, {"status": "error", "message": str(e)}, 503
    except Exception as e:
        logger.exception(f"Error reading strategy legs: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def set_trade_strategy(api_key: str, trade_id: int, strategy: str):
    """Manual strategy-tag fallback for one historical trade row - for
    CSV-imported history and any trade with no orderid to automatically
    join against the strategy book (see TradebookFill.strategy's docstring).
    Overwrites whatever strategy value (if any) the row already has,
    automatic or manual, and does the same for every other fill of the same
    order and symbol (the reply lists them in `updated_ids`).
    """
    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    strategy = (strategy or "").strip()
    if not strategy:
        return False, {"status": "error", "message": "strategy is required"}, 400

    try:
        row = db_session.query(TradebookFill).filter_by(id=trade_id).one_or_none()
        if row is None:
            return False, {"status": "error", "message": "Trade not found"}, 404

        row.strategy = strategy
        # One order is filled in many pieces, each its own row with its own
        # trade id. The tag belongs to the order, so it goes onto every fill
        # of the same order and symbol in one step. Rows with no order id
        # (some CSV imports) have nothing to group on and stay single.
        sibling_ids = []
        if row.orderid:
            siblings = (
                db_session.query(TradebookFill)
                .filter(
                    TradebookFill.orderid == row.orderid,
                    TradebookFill.symbol == row.symbol,
                    TradebookFill.id != row.id,
                )
                .all()
            )
            for sibling in siblings:
                sibling.strategy = strategy
                sibling_ids.append(sibling.id)
        db_session.commit()
        return (
            True,
            {
                "status": "success",
                "data": {
                    "id": row.id,
                    "strategy": row.strategy,
                    "updated_ids": [row.id, *sibling_ids],
                },
            },
            200,
        )
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error setting strategy tag on trade {trade_id}: {e}")
        return False, {"status": "error", "message": str(e)}, 500
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# P&L curve: daily realized + unrealized per strategy (equity only)
# ---------------------------------------------------------------------------

# Daily closes per instrument and span, as {date: close}. Past closes never
# change; a short TTL keeps today's bar fresh.
_daily_close_cache = LockedTTLCache(maxsize=512, ttl=900)

_INDEX_FOR_CALENDAR = ("NIFTY", "NSE_INDEX")


def _bars_to_closes(records) -> dict[date, float]:
    """{trading date: close} from a broker daily history response.

    A daily bar's epoch is midnight IST written either as 00:00 UTC of that
    date or as 18:30 UTC of the day before; adding 5h30m lands on the right
    date for both.
    """
    out: dict[date, float] = {}
    for rec in records or []:
        try:
            ts = int(rec["timestamp"])
            close = float(rec["close"])
        except (KeyError, TypeError, ValueError):
            continue
        out[datetime.fromtimestamp(ts + 19800, tz=UTC).date()] = close
    return out


def _daily_closes(api_key: str, symbol: str, exchange: str, start: date, end: date):
    """Daily closes for one instrument over [start, end], or {} when the broker
    has none. Cached by span, so a re-fetch of the same page costs no broker
    calls.
    """
    from services.history_service import get_history

    key = (symbol, exchange, start.isoformat(), end.isoformat())
    cached = _daily_close_cache.get(key)
    if cached is not None:
        return cached
    try:
        ok, response, _ = get_history(
            symbol=symbol,
            exchange=exchange,
            interval="D",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            api_key=api_key,
        )
    except Exception:
        logger.exception(f"Daily history failed for {exchange}:{symbol}")
        return {}
    closes = _bars_to_closes(response.get("data")) if ok else {}
    if closes:
        _daily_close_cache[key] = closes
    return closes


def get_pnl_curve(
    api_key: str,
    start_date: str,
    end_date: str,
    basis: str = "range_start",
    symbol_contains: str | None = None,
):
    """Daily realized and unrealized P&L per strategy, equity segment only.

    Returns {dates, by_strategy: {name: {realized: [...], unrealized: [...]}},
    basis, base_date, notes}. realized is a daily amount; unrealized is the
    level of the open lots at that day's close. Everything is derived from the
    ledger and the broker's daily closes on every call; nothing is stored.
    """
    auth_token, broker = get_auth_token_broker(api_key)
    if not auth_token:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403
    if basis not in VALID_BASES:
        return False, {"status": "error", "message": f"basis must be one of {VALID_BASES}"}, 400

    error, query, start_dt, end_dt = _parse_range_and_build_query(
        start_date, end_date, segment="equity", fifo_lookback=True
    )
    if error:
        return error
    start, end = start_dt.date(), end_dt.date()
    if end < start:
        return False, {"status": "error", "message": "end_date is before start_date"}, 400

    try:
        rows = query.order_by(TradebookFill.trade_timestamp.asc(), TradebookFill.id.asc()).all()
        fills = [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "product": r.product,
                "action": r.action,
                "quantity": r.quantity,
                "average_price": r.average_price,
                "timestamp": r.trade_timestamp,
                "strategy": r.strategy,
            }
            for r in rows
        ]
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reading fills for the P&L curve: {e}")
        return False, {"status": "error", "message": str(e)}, 500
    finally:
        db_session.remove()

    # A symbol filter is safe before matching: a position is one symbol.
    needle = (symbol_contains or "").strip().upper()
    if needle:
        fills = [f for f in fills if needle in (f["symbol"] or "").upper()]

    # Trading days: the index's own daily bars (holidays and special sessions
    # come for free); weekdays when the broker returns none.
    lookback_start = start - timedelta(days=10)
    index_closes = _daily_closes(api_key, *_INDEX_FOR_CALENDAR, lookback_start, end)
    calendar_note = None
    if index_closes:
        all_days = sorted(index_closes)
    else:
        calendar_note = "weekdays (no index history from the broker)"
        span = (end - lookback_start).days + 1
        all_days = [
            d for d in (lookback_start + timedelta(days=i) for i in range(span)) if d.weekday() < 5
        ]
    trading_dates = [d for d in all_days if start <= d <= end]
    prior = [d for d in all_days if d < start]
    base_date = prior[-1] if prior else None

    closes = {}
    if trading_dates:
        span_start = base_date or start
        for symbol, exchange in sorted(symbols_needing_closes(fills, span_start, end)):
            got = _daily_closes(api_key, symbol, exchange, span_start, end)
            if got:
                closes[(symbol, exchange)] = got

    result = build_curve(fills, closes, trading_dates, base_date, basis)
    if calendar_note:
        result["notes"]["calendar"] = calendar_note
    return (
        True,
        {
            "status": "success",
            "data": {
                "basis": basis,
                "segment": "equity",
                "base_date": base_date.isoformat() if base_date else None,
                **result,
            },
        },
        200,
    )
