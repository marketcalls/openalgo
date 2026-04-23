"""
Multi Strike OI Service.

Fetches a per-leg Open Interest time series for every active option leg in
the Strategy Builder, plus the underlying close. Each leg is returned as a
separate series (no aggregation) so the chart can overlay them with
independent line colors and legend toggles.

The history service (see services/history_service.py) normalizes `oi` to 0
when the broker doesn't supply it — downstream callers should treat an
all-zero leg series as "not available" in the UI.
"""

import pandas as pd
import pytz

from services.history_service import get_history
from services.quotes_service import get_quotes
from services.strategy_chart_service import (
    _cap_last_n_trading_dates,
    _convert_timestamp_to_ist,
    _get_quote_exchange,
    _normalize_leg,
    _resolve_trading_window,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def get_multi_strike_oi_data(
    underlying: str,
    exchange: str,
    legs: list[dict],
    interval: str,
    api_key: str,
    days: int = 5,
):
    """
    Compute Multi Strike OI time series for the Strategy Builder.

    Args:
        underlying: Underlying base symbol (e.g., "NIFTY").
        exchange: Underlying exchange as selected in the builder header.
        legs: List of leg dicts — only active OPTION legs are used.
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
        # Some brokers (e.g., Zerodha) don't return intraday minute-level
        # candles for INDEX tokens. Fall through with an empty underlying
        # series so the OI overlays still render — the UI flags this.
        underlying_missing = False
        underlying_series: list[dict] = []
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
                f"Multi-strike OI: underlying history fetch failed for {base_symbol}/{quote_exchange} @ {interval} — continuing with legs only. Reason: {resp_u.get('message')}"
            )
            underlying_missing = True
        else:
            df_u = pd.DataFrame(resp_u.get("data", []))
            if df_u.empty:
                logger.info(
                    f"Multi-strike OI: empty underlying history for {base_symbol}/{quote_exchange} @ {interval} {start_date_str}..{end_date_str} — broker likely doesn't return {interval} candles for this symbol; continuing with legs only."
                )
                underlying_missing = True
            else:
                df_u = _convert_timestamp_to_ist(df_u)
                if df_u is None:
                    return (
                        False,
                        {"status": "error", "message": "Failed to parse underlying timestamps"},
                        500,
                    )
                for ts, row in df_u.iterrows():
                    try:
                        underlying_series.append(
                            {"time": int(ts.timestamp()), "value": round(float(row["close"]), 2)}
                        )
                    except (KeyError, TypeError, ValueError):
                        continue

        # ── Per-leg OI history, deduped by (symbol, exchange) ─────────
        oi_lookup: dict[tuple[str, str], list[dict]] = {}
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
            series = []
            if success_l:
                df_l = pd.DataFrame(resp_l.get("data", []))
                if not df_l.empty:
                    df_l = _convert_timestamp_to_ist(df_l)
                    if df_l is not None:
                        for ts, row in df_l.iterrows():
                            try:
                                oi_val = float(row.get("oi", 0) or 0)
                            except (TypeError, ValueError):
                                oi_val = 0.0
                            series.append(
                                {"time": int(ts.timestamp()), "value": round(oi_val, 2)}
                            )
            oi_lookup[(symbol, leg_exchange)] = series

        # ── Assemble per-leg response ─────────────────────────────────
        # We pass through the original leg fields the UI needs for labels
        # (strike / optionType / expiry). The frontend keeps the leg order
        # from the Strategy Builder's positions panel so colours stay stable
        # across add/remove.
        # Keep the original leg order from the Strategy Builder so the UI's
        # colour assignment stays stable across add/remove.
        leg_series = []
        for raw in (legs or []):
            norm = _normalize_leg(raw)
            if not norm:
                continue
            key = (norm["symbol"], norm["exchange"])
            series = oi_lookup.get(key, [])
            has_any_nonzero = any(p["value"] > 0 for p in series)
            leg_series.append(
                {
                    "symbol": norm["symbol"],
                    "exchange": norm["exchange"],
                    "side": norm["side"],
                    "strike": raw.get("strike"),
                    "option_type": raw.get("optionType"),
                    "expiry": raw.get("expiry"),
                    "has_oi": has_any_nonzero,
                    "series": series,
                }
            )

        # Cap every series (underlying + each leg) to the last N distinct
        # trading dates actually present. Market-agnostic: counts returned
        # dates rather than hardcoding session close times.
        underlying_series = _cap_last_n_trading_dates(underlying_series, days, ist)
        for leg_entry in leg_series:
            leg_entry["series"] = _cap_last_n_trading_dates(
                leg_entry["series"], days, ist
            )

        # ── Latest underlying LTP ─────────────────────────────────────
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
                    "underlying_available": not underlying_missing,
                    "underlying_series": underlying_series,
                    "legs": leg_series,
                },
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error computing multi-strike OI data: {e}")
        return False, {"status": "error", "message": str(e)}, 500
