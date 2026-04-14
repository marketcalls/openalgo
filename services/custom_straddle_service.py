"""
Custom Straddle Simulation Service
Simulates an intraday short ATM straddle with automated adjustments.

For each trading day:
1. ENTRY at first candle — sell ATM CE + PE
2. ADJUSTMENT when spot moves >= N points from entry strike — exit old, enter new ATM
3. EXIT at last candle — close position

Tracks cumulative PnL across days and returns a time series + trade log.
"""

from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import pytz

from services.history_service import get_history
from services.option_symbol_service import (
    construct_crypto_option_symbol,
    construct_option_symbol,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
)
from services.quotes_service import get_quotes
from services.straddle_chart_service import (
    NSE_INDEX_SYMBOLS,
    BSE_INDEX_SYMBOLS,
    _get_quote_exchange,
    _convert_timestamp_to_ist,
    _calculate_days_to_expiry,
)
from database.token_db_enhanced import fno_search_symbols
from utils.constants import CRYPTO_EXCHANGES, INSTRUMENT_PERPFUT
from utils.logging import get_logger

logger = get_logger(__name__)


def get_custom_straddle_simulation(
    underlying,
    exchange,
    expiry_date,
    interval,
    api_key,
    days=1,
    adjustment_points=50,
    lot_size=65,
    lots=1,
):
    """
    Simulate an intraday short ATM straddle with N-point adjustments.

    Returns:
        Tuple of (success, response_dict, status_code)
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        today = datetime.now(ist).date()
        weekday = today.weekday()
        if weekday == 5:
            today -= timedelta(days=1)
        elif weekday == 6:
            today -= timedelta(days=2)

        end_date_str = today.strftime("%Y-%m-%d")
        start_date_str = (today - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")

        quantity = lot_size * lots
        base_symbol = underlying.upper()
        quote_exchange = _get_quote_exchange(base_symbol, exchange)
        options_exchange = get_option_exchange(quote_exchange)

        # Handle crypto perpetual symbol lookup (e.g. BTC → BTCUSDFUT)
        if exchange.upper() in CRYPTO_EXCHANGES:
            _perp = fno_search_symbols(
                query=f"{base_symbol}USDFUT", exchange=exchange, instrumenttype=INSTRUMENT_PERPFUT, limit=1
            )
            if not _perp:
                return False, {"status": "error", "message": f"No perpetual futures found for {base_symbol}"}, 404
            underlying_quote_symbol = _perp[0]["symbol"]
        else:
            underlying_quote_symbol = base_symbol

        # Get available strikes
        available_strikes = get_available_strikes(
            base_symbol, expiry_date.upper(), "CE", options_exchange
        )
        if not available_strikes:
            return False, {
                "status": "error",
                "message": f"No strikes found for {base_symbol} {expiry_date} on {options_exchange}",
            }, 404

        # Fetch underlying history
        success_u, resp_u, _ = get_history(
            symbol=underlying_quote_symbol, exchange=quote_exchange,
            interval=interval, start_date=start_date_str,
            end_date=end_date_str, api_key=api_key,
        )
        if not success_u:
            return False, {
                "status": "error",
                "message": f"Failed to fetch underlying history: {resp_u.get('message', 'Unknown')}",
            }, 400

        df_underlying = pd.DataFrame(resp_u.get("data", []))
        if df_underlying.empty:
            return False, {"status": "error", "message": "No underlying history data"}, 404

        df_underlying = _convert_timestamp_to_ist(df_underlying)
        if df_underlying is None:
            return False, {"status": "error", "message": "Failed to parse timestamps"}, 500

        # Compute ATM per candle
        atm_per_row = []
        for _, row in df_underlying.iterrows():
            atm = find_atm_strike_from_actual(float(row["close"]), available_strikes)
            atm_per_row.append(atm)
        df_underlying["atm_strike"] = atm_per_row

        unique_strikes = set(s for s in atm_per_row if s is not None)
        if not unique_strikes:
            return False, {"status": "error", "message": "Could not determine ATM strikes"}, 400

        # Fetch option history for all unique ATM strikes
        _build_sym = (
            construct_crypto_option_symbol
            if exchange.upper() in CRYPTO_EXCHANGES
            else construct_option_symbol
        )
        strike_data = {}
        for strike in sorted(unique_strikes):
            ce_symbol = _build_sym(base_symbol, expiry_date.upper(), strike, "CE")
            pe_symbol = _build_sym(base_symbol, expiry_date.upper(), strike, "PE")

            ce_lookup, pe_lookup = {}, {}

            success_ce, resp_ce, _ = get_history(
                symbol=ce_symbol, exchange=options_exchange,
                interval=interval, start_date=start_date_str,
                end_date=end_date_str, api_key=api_key,
            )
            if success_ce:
                df_ce = pd.DataFrame(resp_ce.get("data", []))
                if not df_ce.empty:
                    df_ce = _convert_timestamp_to_ist(df_ce)
                    if df_ce is not None:
                        for ts, row in df_ce.iterrows():
                            ce_lookup[ts] = float(row["close"])

            success_pe, resp_pe, _ = get_history(
                symbol=pe_symbol, exchange=options_exchange,
                interval=interval, start_date=start_date_str,
                end_date=end_date_str, api_key=api_key,
            )
            if success_pe:
                df_pe = pd.DataFrame(resp_pe.get("data", []))
                if not df_pe.empty:
                    df_pe = _convert_timestamp_to_ist(df_pe)
                    if df_pe is not None:
                        for ts, row in df_pe.iterrows():
                            pe_lookup[ts] = float(row["close"])

            strike_data[strike] = {"ce": ce_lookup, "pe": pe_lookup}

        # ── Simulation ──────────────────────────────────────────────
        # Group candles by trading day
        daily_candles = defaultdict(list)
        for ts, row in df_underlying.iterrows():
            daily_candles[ts.date()].append((ts, row))

        cumulative_realized = 0.0
        total_adjustments = 0
        pnl_series = []
        trades = []

        for day in sorted(daily_candles.keys()):
            candles = daily_candles[day]

            entry_strike = None
            entry_ce = None
            entry_pe = None
            day_realized = 0.0
            day_adjustments = 0
            last_unrealized = 0.0

            for i, (ts, row) in enumerate(candles):
                spot = float(row["close"])
                atm = row["atm_strike"]

                if atm is None or atm not in strike_data:
                    continue

                is_last = i == len(candles) - 1

                # ── ENTRY (first valid candle of day) ──
                if entry_strike is None:
                    ce_at_atm = strike_data[atm]["ce"].get(ts)
                    pe_at_atm = strike_data[atm]["pe"].get(ts)
                    if ce_at_atm is None or pe_at_atm is None:
                        continue

                    entry_strike = atm
                    entry_ce = ce_at_atm
                    entry_pe = pe_at_atm

                    trades.append({
                        "time": int(ts.timestamp()),
                        "type": "ENTRY",
                        "strike": atm,
                        "ce_price": round(ce_at_atm, 2),
                        "pe_price": round(pe_at_atm, 2),
                        "straddle": round(ce_at_atm + pe_at_atm, 2),
                        "spot": round(spot, 2),
                        "leg_pnl": 0.0,
                        "cumulative_pnl": round(cumulative_realized, 2),
                    })
                else:
                    # ── ADJUSTMENT check ──
                    if abs(atm - entry_strike) >= adjustment_points:
                        old_ce = strike_data.get(entry_strike, {}).get("ce", {}).get(ts)
                        old_pe = strike_data.get(entry_strike, {}).get("pe", {}).get(ts)
                        new_ce = strike_data[atm]["ce"].get(ts)
                        new_pe = strike_data[atm]["pe"].get(ts)

                        if (
                            old_ce is not None
                            and old_pe is not None
                            and new_ce is not None
                            and new_pe is not None
                        ):
                            leg_pnl = (
                                (entry_ce - old_ce) + (entry_pe - old_pe)
                            ) * quantity
                            day_realized += leg_pnl
                            day_adjustments += 1

                            trades.append({
                                "time": int(ts.timestamp()),
                                "type": "ADJUSTMENT",
                                "old_strike": entry_strike,
                                "strike": atm,
                                "exit_ce": round(old_ce, 2),
                                "exit_pe": round(old_pe, 2),
                                "exit_straddle": round(old_ce + old_pe, 2),
                                "ce_price": round(new_ce, 2),
                                "pe_price": round(new_pe, 2),
                                "straddle": round(new_ce + new_pe, 2),
                                "spot": round(spot, 2),
                                "leg_pnl": round(leg_pnl, 2),
                                "cumulative_pnl": round(
                                    cumulative_realized + day_realized, 2
                                ),
                            })

                            entry_strike = atm
                            entry_ce = new_ce
                            entry_pe = new_pe

                # ── Compute current PnL ──
                cur_ce = strike_data.get(entry_strike, {}).get("ce", {}).get(ts)
                cur_pe = strike_data.get(entry_strike, {}).get("pe", {}).get(ts)

                if cur_ce is not None and cur_pe is not None:
                    unrealized = (
                        (entry_ce - cur_ce) + (entry_pe - cur_pe)
                    ) * quantity
                    last_unrealized = unrealized
                else:
                    unrealized = last_unrealized

                total_pnl = cumulative_realized + day_realized + unrealized

                # Current ATM straddle for display
                atm_ce = strike_data[atm]["ce"].get(ts, 0) or 0
                atm_pe = strike_data[atm]["pe"].get(ts, 0) or 0

                synthetic_future = round(atm + atm_ce - atm_pe, 2) if atm_ce and atm_pe else round(spot, 2)

                pnl_series.append({
                    "time": int(ts.timestamp()),
                    "pnl": round(total_pnl, 2),
                    "spot": round(spot, 2),
                    "atm_strike": atm,
                    "entry_strike": entry_strike,
                    "ce_price": round(atm_ce, 2),
                    "pe_price": round(atm_pe, 2),
                    "straddle": round(atm_ce + atm_pe, 2),
                    "synthetic_future": synthetic_future,
                    "adjustments": total_adjustments + day_adjustments,
                })

                # ── EXIT at last candle ──
                if is_last and entry_strike is not None:
                    exit_ce = strike_data.get(entry_strike, {}).get("ce", {}).get(ts)
                    exit_pe = strike_data.get(entry_strike, {}).get("pe", {}).get(ts)

                    if exit_ce is not None and exit_pe is not None:
                        leg_pnl = (
                            (entry_ce - exit_ce) + (entry_pe - exit_pe)
                        ) * quantity
                    else:
                        leg_pnl = last_unrealized

                    trades.append({
                        "time": int(ts.timestamp()),
                        "type": "EXIT",
                        "strike": entry_strike,
                        "ce_price": round(exit_ce or 0, 2),
                        "pe_price": round(exit_pe or 0, 2),
                        "straddle": round((exit_ce or 0) + (exit_pe or 0), 2),
                        "spot": round(spot, 2),
                        "leg_pnl": round(leg_pnl, 2),
                        "cumulative_pnl": round(
                            cumulative_realized + day_realized + leg_pnl, 2
                        ),
                    })

            # End of day — settle
            if entry_strike is not None:
                last_ts = candles[-1][0]
                final_ce = strike_data.get(entry_strike, {}).get("ce", {}).get(last_ts)
                final_pe = strike_data.get(entry_strike, {}).get("pe", {}).get(last_ts)

                if final_ce is not None and final_pe is not None:
                    final_leg = (
                        (entry_ce - final_ce) + (entry_pe - final_pe)
                    ) * quantity
                else:
                    final_leg = last_unrealized

                cumulative_realized += day_realized + final_leg

            total_adjustments += day_adjustments

        if not pnl_series:
            return False, {
                "status": "error",
                "message": "No simulation data (option history may be missing)",
            }, 404

        # Current LTP
        success_q, quote_resp, _ = get_quotes(
            symbol=underlying_quote_symbol, exchange=quote_exchange, api_key=api_key,
        )
        underlying_ltp = (
            quote_resp.get("data", {}).get("ltp", 0) if success_q else 0
        )

        pnl_values = [p["pnl"] for p in pnl_series]

        return True, {
            "status": "success",
            "data": {
                "underlying": base_symbol,
                "underlying_ltp": underlying_ltp,
                "expiry_date": expiry_date.upper(),
                "interval": interval,
                "days_to_expiry": _calculate_days_to_expiry(expiry_date),
                "adjustment_points": adjustment_points,
                "lot_size": lot_size,
                "lots": lots,
                "quantity": quantity,
                "pnl_series": pnl_series,
                "trades": trades,
                "summary": {
                    "total_pnl": round(cumulative_realized, 2),
                    "total_adjustments": total_adjustments,
                    "max_pnl": round(max(pnl_values), 2),
                    "min_pnl": round(min(pnl_values), 2),
                },
            },
        }, 200

    except Exception as e:
        logger.exception(f"Error in custom straddle simulation: {e}")
        return False, {"status": "error", "message": str(e)}, 500
