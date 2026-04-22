"""
Strategy Chart Service.

Computes a per-share "combined premium" time series for a user-built strategy
(N option legs, optionally across multiple expiries for calendar/diagonal
spreads), along with the underlying price on a common IST-aligned timeline.

Combined premium formula (per-share, quantity-independent):

    sign_i      = +1 if leg.side == SELL else -1     (credit vs debit)
    price_i(t)  = close of leg_i.symbol at candle t  (from /history)

    net_premium(t)      = sum_i( sign_i * price_i(t) )
    combined_premium(t) = | net_premium(t) |         (always positive)

The sign of the entry-time net_premium classifies the strategy as a
credit or debit strategy. Only active OPTION legs contribute. Futures
legs are ignored (their price levels are not premia and would blow up
the scale). Timestamps missing for any active leg are dropped.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytz

from services.history_service import get_history
from services.quotes_service import get_quotes
from utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_trading_window(days: int, ist_tz: pytz.BaseTzInfo) -> tuple[str, str]:
    """
    Resolve (start_date_str, end_date_str) as a GENEROUS calendar window
    that is guaranteed to contain at least `days` trading dates' worth of
    data for any market (NSE, MCX, CDS, crypto, ...).

    We intentionally don't hardcode market-close times here — the broker
    decides which calendar days have candles. The caller is expected to
    post-filter the returned series via `_cap_last_n_trading_dates`, which
    keeps only the last N distinct IST dates that actually carry data.

    The buffer `days * 3 + 2` covers worst-case long weekends/holidays for
    weekend-closed markets while staying small for typical UI options
    (1/3/5/10 days → 5/11/17/32 calendar days fetched).
    """
    today = datetime.now(ist_tz).date()
    buffer_calendar_days = max(2, days * 3 + 2)
    start = today - timedelta(days=buffer_calendar_days)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _cap_last_n_trading_dates(series: list[dict], n: int, ist_tz: pytz.BaseTzInfo) -> list[dict]:
    """
    Trim `series` to rows whose IST calendar date is among the last N
    distinct dates present. Market-agnostic — counts actual trading dates
    returned by the broker (empty days are naturally skipped since they
    contribute no rows). Works for 24x7 crypto and weekend-closed markets
    alike.
    """
    if not series or n <= 0:
        return series
    tagged = [
        (datetime.fromtimestamp(r["time"], tz=pytz.UTC).astimezone(ist_tz).date(), r)
        for r in series
    ]
    distinct_dates = sorted({d for d, _ in tagged}, reverse=True)
    keep = set(distinct_dates[:n])
    return [r for d, r in tagged if d in keep]


NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYPHARMA",
    "NIFTYBANK",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def _get_quote_exchange(base_symbol: str, underlying_exchange: str) -> str:
    """Resolve the exchange to use for fetching underlying quotes/history."""
    upper = (underlying_exchange or "").upper()
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if upper == "NFO":
        return "NSE"
    if upper == "BFO":
        return "BSE"
    if upper in ("NSE_INDEX", "BSE_INDEX"):
        return upper
    return upper


def _convert_timestamp_to_ist(df: pd.DataFrame) -> pd.DataFrame | None:
    """Normalize a history dataframe's timestamp column to an IST datetime index."""
    ist = pytz.timezone("Asia/Kolkata")
    try:
        if "timestamp" not in df.columns:
            logger.warning("No timestamp field in history data")
            return None
        try:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            df["datetime"] = df["datetime"].dt.tz_convert(ist)
        except Exception:
            try:
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df["datetime"] = df["datetime"].dt.tz_convert(ist)
            except Exception:
                df["datetime"] = pd.to_datetime(df["timestamp"])
                if df["datetime"].dt.tz is None:
                    df["datetime"] = df["datetime"].dt.tz_localize("UTC").dt.tz_convert(ist)
                else:
                    df["datetime"] = df["datetime"].dt.tz_convert(ist)
        df.set_index("datetime", inplace=True)
        return df.sort_index()
    except Exception as e:
        logger.warning(f"Error converting timestamps: {e}")
        return None


def _normalize_leg(leg: dict) -> dict | None:
    """
    Validate and normalize a single leg payload.

    Returns None for legs that should NOT contribute to the combined premium
    (inactive, non-option, or missing symbol/side).
    """
    if not isinstance(leg, dict):
        return None
    if leg.get("active") is False:
        return None
    segment = (leg.get("segment") or "OPTION").upper()
    # Futures contribute a price level rather than a premium — exclude.
    if segment != "OPTION":
        return None
    symbol = (leg.get("symbol") or "").strip()
    side = (leg.get("side") or "").upper()
    exchange = (leg.get("exchange") or "").strip().upper()
    if not symbol or side not in ("BUY", "SELL") or not exchange:
        return None
    try:
        entry_price = float(leg.get("price") or 0)
    except (TypeError, ValueError):
        entry_price = 0.0
    return {
        "symbol": symbol,
        "exchange": exchange,
        "side": side,
        "sign": 1 if side == "SELL" else -1,
        "entry_price": entry_price,
    }


def get_strategy_chart_data(
    underlying: str,
    exchange: str,
    legs: list[dict],
    interval: str,
    api_key: str,
    days: int = 5,
):
    """
    Build the Strategy Chart time series for a user-defined options strategy.

    Args:
        underlying: Underlying base symbol (e.g., "NIFTY").
        exchange: Underlying exchange as selected in the builder header
                  (e.g., "NSE_INDEX", "BSE_INDEX", "NFO", "BFO").
        legs: List of leg dicts with keys
              {symbol, exchange, side, segment, active, price}.
              Only active OPTION legs are used.
        interval: Candle interval (e.g., "1m", "5m").
        api_key: OpenAlgo API key.
        days: Calendar-day lookback window.

    Returns:
        Tuple of (success: bool, response: dict, status_code: int).
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        start_date_str, end_date_str = _resolve_trading_window(days, ist)

        base_symbol = (underlying or "").strip().upper()
        if not base_symbol:
            return False, {"status": "error", "message": "underlying is required"}, 400

        normalized_legs = [nl for nl in (_normalize_leg(l) for l in (legs or [])) if nl]
        if not normalized_legs:
            return (
                False,
                {"status": "error", "message": "No active option legs provided"},
                400,
            )

        quote_exchange = _get_quote_exchange(base_symbol, exchange)

        # ── Underlying history ────────────────────────────────────────
        # Some brokers (e.g., Zerodha's Kite API) don't return intraday
        # minute-level candles for INDEX tokens (NIFTY, BANKNIFTY, SENSEX).
        # Instead of failing the whole chart, we proceed with an empty
        # underlying series — the combined-premium / OI curves still render
        # from the F&O leg history, which is available at all intervals.
        underlying_missing = False
        df_underlying: pd.DataFrame | None = None
        success_u, resp_u, _ = get_history(
            symbol=base_symbol,
            exchange=quote_exchange,
            interval=interval,
            start_date=start_date_str,
            end_date=end_date_str,
            api_key=api_key,
        )
        if not success_u:
            logger.info(
                f"Strategy chart: underlying history fetch failed for {base_symbol}/{quote_exchange} @ {interval} — continuing with legs only. Reason: {resp_u.get('message')}"
            )
            underlying_missing = True
        else:
            df_tmp = pd.DataFrame(resp_u.get("data", []))
            if df_tmp.empty:
                logger.info(
                    f"Strategy chart: empty underlying history for {base_symbol}/{quote_exchange} @ {interval} {start_date_str}..{end_date_str} — broker likely doesn't return {interval} candles for this symbol; continuing with legs only."
                )
                underlying_missing = True
            else:
                df_underlying = _convert_timestamp_to_ist(df_tmp)
                if df_underlying is None:
                    return (
                        False,
                        {"status": "error", "message": "Failed to parse underlying timestamps"},
                        500,
                    )

        # ── Per-leg history (deduped by (symbol, exchange)) ───────────
        leg_price_lookup: dict[tuple[str, str], dict] = {}
        unique_keys = {(l["symbol"], l["exchange"]) for l in normalized_legs}

        for symbol, leg_exchange in unique_keys:
            success_l, resp_l, _ = get_history(
                symbol=symbol,
                exchange=leg_exchange,
                interval=interval,
                start_date=start_date_str,
                end_date=end_date_str,
                api_key=api_key,
            )
            prices: dict = {}
            if success_l:
                df_l = pd.DataFrame(resp_l.get("data", []))
                if not df_l.empty:
                    df_l = _convert_timestamp_to_ist(df_l)
                    if df_l is not None:
                        for ts, row in df_l.iterrows():
                            try:
                                prices[ts] = float(row["close"])
                            except (KeyError, TypeError, ValueError):
                                continue
            leg_price_lookup[(symbol, leg_exchange)] = prices
            if not prices:
                logger.debug(
                    f"Strategy chart: no history for leg {symbol}/{leg_exchange} — rows where it's missing will be dropped"
                )

        # ── Merge per-candle ──────────────────────────────────────────
        # A timestamp contributes only if EVERY active option leg has a close
        # at that timestamp — this matches straddle_chart_service's policy
        # and prevents forward-fill artefacts on the combined series. When
        # the underlying is missing we iterate the intersection of leg
        # timestamps instead, and drop the underlying column from the row.
        series: list[dict] = []
        if df_underlying is not None:
            ts_source = df_underlying.iterrows()
        else:
            # Intersect timestamps across all legs — the union would produce
            # gaps in the combined series where any one leg was missing.
            ts_sets = [set(prices.keys()) for prices in leg_price_lookup.values()]
            common_ts = sorted(set.intersection(*ts_sets)) if ts_sets else []
            ts_source = ((ts, None) for ts in common_ts)

        for ts, row in ts_source:
            spot: float | None = None
            if row is not None:
                try:
                    spot = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue

            signed_sum = 0.0
            ok = True
            for leg in normalized_legs:
                price = leg_price_lookup.get((leg["symbol"], leg["exchange"]), {}).get(ts)
                if price is None:
                    ok = False
                    break
                signed_sum += leg["sign"] * price
            if not ok:
                continue

            point = {
                "time": int(ts.timestamp()),
                "net_premium": round(signed_sum, 2),
                "combined_premium": round(abs(signed_sum), 2),
            }
            if spot is not None:
                point["underlying"] = round(spot, 2)
            series.append(point)

        if not series:
            return (
                False,
                {
                    "status": "error",
                    "message": "No overlapping history across legs — option data may be unavailable for the selected range",
                },
                404,
            )

        # Cap to the last N distinct trading dates that actually carry data.
        # This gives "last N days" semantics that are correct for any market
        # (NSE equity/F&O, MCX, CDS, crypto 24x7) without hardcoding session
        # close times.
        series = _cap_last_n_trading_dates(series, days, ist)

        # ── Credit / debit classification (static, from entry premia) ─
        entry_net = sum(leg["sign"] * leg["entry_price"] for leg in normalized_legs)
        tag = "credit" if entry_net > 0 else ("debit" if entry_net < 0 else "flat")

        # ── Latest underlying LTP for the info bar ────────────────────
        success_q, quote_resp, _ = get_quotes(
            symbol=base_symbol,
            exchange=quote_exchange,
            api_key=api_key,
        )
        underlying_ltp = quote_resp.get("data", {}).get("ltp", 0) if success_q else 0

        return (
            True,
            {
                "status": "success",
                "data": {
                    "underlying": base_symbol,
                    "underlying_ltp": underlying_ltp,
                    "interval": interval,
                    "tag": tag,
                    "entry_net_premium": round(entry_net, 2),
                    "entry_abs_premium": round(abs(entry_net), 2),
                    "legs_used": len(normalized_legs),
                    "underlying_available": not underlying_missing,
                    "series": series,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error computing strategy chart data: {e}")
        return False, {"status": "error", "message": str(e)}, 500
