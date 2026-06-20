"""
Gamma Density Service

Computes the "Gamma Density" view (inspired by Vtrender's Gamma Density chart):

  * Density (Γ×OI)   - per-strike dealer gamma exposure = option gamma × open
                       interest, summed across CE and PE legs. The orange curve.
  * Convexity Zone   - a Gaussian centred on spot whose width is the 1σ expected
                       move (from ATM IV). The green bell. Marks where price is
                       statistically expected to gravitate / accelerate.

Two horizons are returned so the UI can show side-by-side panels:
  * Intraday  - gamma computed with a 1-trading-day horizon, narrow expected-move
                band. Highlights today's hedging pressure (sharper ATM peak).
  * To Expiry - gamma computed with the full days-to-expiry, wider expected-move
                band. The terminal pin/gravity view.

Reuses the option chain service for OI + LTP, and the Black-76 model (opengreeks)
- the same model used by option_greeks_service - for IV and gamma. No extra
broker calls beyond the single option-chain fetch.

Functions:
    calculate_gamma_density() - full gamma density payload for an underlying/expiry
"""

import math
from datetime import datetime
from typing import Any

from services.option_chain_service import get_option_chain
from services.option_greeks_service import (
    DEFAULT_INTEREST_RATES,
    _resolve_index_weekly_forward,
    calculate_time_to_expiry,
    get_underlying_exchange,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Trading days per year used to annualise the 1-day (intraday) sigma move.
# Vtrender / standard expected-move convention uses calendar 365 for the
# annualisation factor, so spot * IV * sqrt(1/365) is the 1-day 1σ move.
_DAYS_PER_YEAR = 365.0

# Intraday gamma horizon: one calendar day in years (capped at real DTE).
# A short horizon sharpens the ATM gamma peak - that is the "intraday gamma
# wall" the convexity zone is meant to surface.
_INTRADAY_T_YEARS = 1.0 / _DAYS_PER_YEAR

# Fallback IV (decimal) used only if every strike's IV inversion fails
# (e.g. a fully stale chain with no usable premiums). Keeps the curves drawable.
_FALLBACK_IV = 0.15

_MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _expiry_datetime(expiry_date: str, exchange: str) -> datetime:
    """
    Build an expiry datetime from a DDMMMYY string and exchange.

    Uses the same default expiry times as option_greeks_service.parse_option_symbol:
    NFO/BFO 15:30, CDS 12:30, MCX 23:30.

    Args:
        expiry_date: Expiry in DDMMMYY format (e.g. 30JAN26)
        exchange: Options exchange (NFO, BFO, CDS, MCX, ...)

    Returns:
        Naive datetime at the exchange close (interpreted as IST downstream)
    """
    day = int(expiry_date[:2])
    month = _MONTH_MAP[expiry_date[2:5].upper()]
    year = 2000 + int(expiry_date[5:7])

    ex = exchange.upper()
    if ex == "MCX":
        hour, minute = 23, 30
    elif ex == "CDS":
        hour, minute = 12, 30
    else:  # NFO, BFO, crypto, equity
        hour, minute = 15, 30

    return datetime(year, month, day, hour, minute)


def _safe_iv(black76, price: float, F: float, K: float, r: float, t: float, flag: str) -> float | None:
    """Black-76 implied volatility (decimal), or None if it cannot be inverted."""
    if not price or price <= 0 or F <= 0 or K <= 0 or t <= 0:
        return None
    try:
        # black76.implied_volatility(price, F, K, r, t, flag) -> decimal
        iv = black76.implied_volatility(price, F, K, r, t, flag)
        if iv is None or not math.isfinite(iv) or iv <= 0 or iv > 5:
            return None
        return iv
    except Exception:
        return None


def _safe_gamma(black76, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    """Black-76 gamma, or 0.0 on any numerical failure."""
    if not sigma or sigma <= 0 or F <= 0 or K <= 0 or t <= 0:
        return 0.0
    try:
        g = black76.gamma(flag, F, K, t, r, sigma)
        if g is None or not math.isfinite(g) or g < 0:
            return 0.0
        return g
    except Exception:
        return 0.0


def calculate_gamma_density(
    underlying: str,
    exchange: str,
    expiry_date: str,
    api_key: str,
    interest_rate: float | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Calculate the Gamma Density payload for an underlying / expiry.

    Pipeline:
      1. Fetch the option chain (47 strikes around ATM) with live OI + LTP.
      2. Derive time-to-expiry (years, days) from the expiry date + exchange.
      3. Per strike: invert IV from CE/PE premiums (Black-76), find ATM IV.
      4. Per strike: compute gamma at the intraday and to-expiry horizons and
         multiply by OI -> Γ×OI density for each horizon (CE+PE).
      5. Compute the daily and to-expiry 1σ moves and the ±1σ / ±2σ levels.

    Args:
        underlying: Underlying symbol (e.g. NIFTY, BANKNIFTY)
        exchange: Options exchange (NFO, BFO, CDS, MCX, crypto)
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key
        interest_rate: Optional risk-free rate (annualized %); default per exchange

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        try:
            from opengreeks import black76
        except ImportError:
            logger.error("opengreeks library not installed.")
            return (
                False,
                {
                    "status": "error",
                    "message": "Gamma Density requires the opengreeks library. Install with: pip install opengreeks",
                },
                500,
            )

        # 1. Option chain with OI + LTP. 23 each side of ATM = 47 strikes / 94
        #    symbols, sized to fit broker multiquote OI buckets (see oi_tracker).
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=23,
            api_key=api_key,
        )
        if not success:
            return False, chain_response, status_code

        full_chain = chain_response.get("chain", [])
        spot_price = chain_response.get("underlying_ltp")
        atm_strike = chain_response.get("atm_strike")

        if not spot_price or spot_price <= 0 or not full_chain:
            return (
                False,
                {"status": "error", "message": "Spot price or option chain unavailable"},
                404,
            )

        # 2. Time to expiry
        expiry_dt = _expiry_datetime(expiry_date, exchange)
        t_years, dte_days = calculate_time_to_expiry(expiry_dt)
        t_intraday = min(t_years, _INTRADAY_T_YEARS) if t_years > 0 else _INTRADAY_T_YEARS

        if interest_rate is None:
            interest_rate = DEFAULT_INTEREST_RATES.get(exchange.upper(), 0)
        r = interest_rate / 100.0

        # Forward price for Black-76, consistent with option_greeks_service:
        # index weekly -> per-expiry synthetic future; monthly index / stocks ->
        # spot. The expected-move band and Spot marker still use the cash spot.
        base_for_forward = chain_response.get("underlying", underlying)
        forward = _resolve_index_weekly_forward(
            base_for_forward,
            exchange,
            get_underlying_exchange(base_for_forward, exchange),
            expiry_dt,
            api_key,
        )
        F = forward or spot_price

        # 3. Pass one: per-strike IV (CE / PE) + ATM IV
        strikes: list[dict[str, Any]] = []
        valid_ivs: list[float] = []
        atm_iv: float | None = None

        for item in full_chain:
            K = item.get("strike")
            if not isinstance(K, (int, float)) or K <= 0:
                continue
            ce = item.get("ce") or {}
            pe = item.get("pe") or {}
            ce_oi = ce.get("oi", 0) or 0
            pe_oi = pe.get("oi", 0) or 0
            ce_ltp = ce.get("ltp", 0) or 0
            pe_ltp = pe.get("ltp", 0) or 0

            ce_iv = _safe_iv(black76, ce_ltp, F, K, r, t_years, "c")
            pe_iv = _safe_iv(black76, pe_ltp, F, K, r, t_years, "p")

            side_ivs = [v for v in (ce_iv, pe_iv) if v is not None]
            strike_iv = sum(side_ivs) / len(side_ivs) if side_ivs else None
            if strike_iv is not None:
                valid_ivs.append(strike_iv)
            if atm_strike is not None and K == atm_strike and strike_iv is not None:
                atm_iv = strike_iv

            strikes.append(
                {
                    "strike": K,
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                    "ce_iv": ce_iv,
                    "pe_iv": pe_iv,
                    "strike_iv": strike_iv,
                }
            )

        # ATM IV fallback: median of valid strike IVs, else a sane default.
        if atm_iv is None:
            if valid_ivs:
                s = sorted(valid_ivs)
                atm_iv = s[len(s) // 2]
            else:
                atm_iv = _FALLBACK_IV
                logger.warning(
                    f"No invertible IV for {underlying} {expiry_date}; using fallback IV {_FALLBACK_IV}"
                )

        # 4. Pass two: gamma at both horizons -> Γ×OI density
        density_chain: list[dict[str, Any]] = []
        max_intraday = 0.0
        max_expiry = 0.0
        peak_intraday_strike = None
        peak_expiry_strike = None

        for s in strikes:
            K = s["strike"]
            ce_sigma = s["ce_iv"] or atm_iv
            pe_sigma = s["pe_iv"] or atm_iv

            ce_g_exp = _safe_gamma(black76, "c", F, K, t_years, r, ce_sigma)
            pe_g_exp = _safe_gamma(black76, "p", F, K, t_years, r, pe_sigma)
            ce_g_intra = _safe_gamma(black76, "c", F, K, t_intraday, r, ce_sigma)
            pe_g_intra = _safe_gamma(black76, "p", F, K, t_intraday, r, pe_sigma)

            density_expiry = ce_g_exp * s["ce_oi"] + pe_g_exp * s["pe_oi"]
            density_intraday = ce_g_intra * s["ce_oi"] + pe_g_intra * s["pe_oi"]

            if density_expiry > max_expiry:
                max_expiry = density_expiry
                peak_expiry_strike = K
            if density_intraday > max_intraday:
                max_intraday = density_intraday
                peak_intraday_strike = K

            density_chain.append(
                {
                    "strike": K,
                    "ce_oi": s["ce_oi"],
                    "pe_oi": s["pe_oi"],
                    "iv": round(s["strike_iv"] * 100, 2) if s["strike_iv"] is not None else None,
                    "density_intraday": density_intraday,
                    "density_expiry": density_expiry,
                }
            )

        # 5. Expected-move bands. Daily (intraday) and to-expiry 1σ moves.
        sqrt_intraday = math.sqrt(_INTRADAY_T_YEARS)
        sqrt_expiry = math.sqrt(max(t_years, 1e-9))
        sigma_intraday = spot_price * atm_iv * sqrt_intraday
        sigma_expiry = spot_price * atm_iv * sqrt_expiry

        def _band(sigma: float) -> dict[str, float]:
            return {
                "sigma_move": round(sigma, 2),
                "one_sigma_low": round(spot_price - sigma, 2),
                "one_sigma_high": round(spot_price + sigma, 2),
                "two_sigma_low": round(spot_price - 2 * sigma, 2),
                "two_sigma_high": round(spot_price + 2 * sigma, 2),
            }

        intraday_band = _band(sigma_intraday)
        expiry_band = _band(sigma_expiry)

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "exchange": exchange,
                "expiry_date": expiry_date,
                "spot_price": round(spot_price, 2),
                "forward_price": round(F, 2),
                "atm_strike": atm_strike,
                "atm_iv": round(atm_iv * 100, 2),
                "dte_days": round(dte_days, 2),
                "interest_rate": round(interest_rate, 2),
                "peak_intraday_strike": peak_intraday_strike,
                "peak_expiry_strike": peak_expiry_strike,
                # Default band shown in the stat cards = daily (intraday) 1σ,
                # matching the Vtrender-style 1-day expected move.
                "sigma_move": intraday_band["sigma_move"],
                "one_sigma_low": intraday_band["one_sigma_low"],
                "one_sigma_high": intraday_band["one_sigma_high"],
                "two_sigma_low": intraday_band["two_sigma_low"],
                "two_sigma_high": intraday_band["two_sigma_high"],
                "intraday_band": intraday_band,
                "expiry_band": expiry_band,
                "chain": density_chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in calculate_gamma_density: {e}")
        return (
            False,
            {"status": "error", "message": "Error computing gamma density"},
            500,
        )
