"""
IV Smile Service
Computes Implied Volatility smile across strikes for a given expiry
using live option chain data + Black-76 model.

Plots Call IV and Put IV across strikes, calculates ATM IV and Skew.
"""

from typing import Any

from services.option_chain_service import get_option_chain
from services.option_greeks_service import calculate_greeks
from utils.logging import get_logger

logger = get_logger(__name__)


def get_iv_smile_data(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Get IV Smile data for all strikes.

    Fetches option chain, computes IV for each CE/PE using Black-76,
    then returns IV curves along with ATM IV and IV Skew.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NFO, BFO)
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Fetch option chain (25 strikes around ATM - sufficient for IV smile)
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=25,
            api_key=api_key,
        )

        if not success:
            return False, chain_response, status_code

        full_chain = chain_response.get("chain", [])
        atm_strike = chain_response.get("atm_strike")
        spot_price = chain_response.get("underlying_ltp")

        if not spot_price or spot_price <= 0:
            return False, {"status": "error", "message": "Could not determine spot price"}, 500

        # Determine options exchange for symbol parsing
        options_exchange = exchange.upper()
        if options_exchange in ("NSE_INDEX", "NSE"):
            options_exchange = "NFO"
        elif options_exchange in ("BSE_INDEX", "BSE"):
            options_exchange = "BFO"

        iv_chain = []
        atm_ce_iv = None
        atm_pe_iv = None

        for item in full_chain:
            strike = item["strike"]
            ce = item.get("ce")
            pe = item.get("pe")

            ce_iv = None
            pe_iv = None

            # Compute CE IV
            if ce and ce.get("symbol"):
                ce_ltp = ce.get("ltp", 0) or 0
                if ce_ltp > 0:
                    try:
                        ok, greeks_resp, _ = calculate_greeks(
                            option_symbol=ce["symbol"],
                            exchange=options_exchange,
                            spot_price=spot_price,
                            option_price=ce_ltp,
                        )
                        if ok and greeks_resp.get("status") == "success":
                            iv_val = greeks_resp.get("implied_volatility", 0)
                            if iv_val and iv_val > 0:
                                ce_iv = round(iv_val, 2)
                    except Exception:
                        pass

            # Compute PE IV
            if pe and pe.get("symbol"):
                pe_ltp = pe.get("ltp", 0) or 0
                if pe_ltp > 0:
                    try:
                        ok, greeks_resp, _ = calculate_greeks(
                            option_symbol=pe["symbol"],
                            exchange=options_exchange,
                            spot_price=spot_price,
                            option_price=pe_ltp,
                        )
                        if ok and greeks_resp.get("status") == "success":
                            iv_val = greeks_resp.get("implied_volatility", 0)
                            if iv_val and iv_val > 0:
                                pe_iv = round(iv_val, 2)
                    except Exception:
                        pass

            # Track ATM IV
            if strike == atm_strike:
                atm_ce_iv = ce_iv
                atm_pe_iv = pe_iv

            iv_chain.append(
                {
                    "strike": strike,
                    "ce_iv": ce_iv,
                    "pe_iv": pe_iv,
                }
            )

        # Calculate ATM IV (average of CE and PE at ATM)
        atm_iv = None
        if atm_ce_iv is not None and atm_pe_iv is not None:
            atm_iv = round((atm_ce_iv + atm_pe_iv) / 2, 2)
        elif atm_ce_iv is not None:
            atm_iv = atm_ce_iv
        elif atm_pe_iv is not None:
            atm_iv = atm_pe_iv

        # Calculate IV Skew (25-delta approximation)
        # Use strikes approximately 5% OTM from ATM as proxy for 25-delta
        skew = None
        if atm_strike and iv_chain:
            otm_distance = atm_strike * 0.05

            # Find nearest OTM put (below ATM) with IV
            put_iv_for_skew = None
            for item in sorted(
                iv_chain, key=lambda x: abs(x["strike"] - (atm_strike - otm_distance))
            ):
                if item["strike"] < atm_strike and item["pe_iv"] is not None:
                    put_iv_for_skew = item["pe_iv"]
                    break

            # Find nearest OTM call (above ATM) with IV
            call_iv_for_skew = None
            for item in sorted(
                iv_chain, key=lambda x: abs(x["strike"] - (atm_strike + otm_distance))
            ):
                if item["strike"] > atm_strike and item["ce_iv"] is not None:
                    call_iv_for_skew = item["ce_iv"]
                    break

            if put_iv_for_skew is not None and call_iv_for_skew is not None:
                skew = round(put_iv_for_skew - call_iv_for_skew, 2)

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "spot_price": spot_price,
                "atm_strike": atm_strike,
                "atm_iv": atm_iv,
                "skew": skew,
                "expiry_date": expiry_date,
                "chain": iv_chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_iv_smile_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching IV Smile data"},
            500,
        )
